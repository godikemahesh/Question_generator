"""
DSC AI Question Generation & Mock Test Platform - CLI Entry Point.
"""
from __future__ import annotations
import sys
import logging
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    SYLLABUS_DIR,
    QUESTION_BANK_DIR,
    OUTPUT_DIR,
    TESTS_OUTPUT_DIR,
    DUMPS_OUTPUT_DIR,
    PAUSE_BETWEEN_BATCHES_SECONDS,
    GENERATION_BATCH_SIZE,
)
from src.generator.gemini_client import GeminiClient
from src.syllabus.parser import parse_all_syllabi, load_all_parsed_subjects, load_parsed_subject, discover_syllabus_files
from src.syllabus.models import Subject
from src.blueprint.engine import create_auto_blueprint, blueprint_to_generation_jobs, save_blueprint, load_blueprint
from src.generator.generator import QuestionGenerator
from src.validators.pipeline import ValidationPipeline
from src.validators.duplicate_detector import DuplicateDetector
from src.question_bank.store import QuestionStore
from src.question_bank.models import QuestionStatus, TestBlueprint
from src.test_assembly.assembler import TestAssembler
from src.test_assembly.test_validator import validate_test
from src.export.csv_exporter import export_questions_to_csv, export_test_to_csv, export_all_subjects_to_csv

console = Console(safe_box=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "platform.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("main")


@click.group()
def cli():
    """AI DSC Question Generation & Mock Test Platform CLI"""
    pass


@cli.command("parse-syllabus")
@click.option("--force", is_flag=True, help="Force re-parsing even if cached JSON exists")
def cmd_parse_syllabus(force: bool):
    """Parse syllabus text files from the syllabus/ directory into structured JSON."""
    console.print(Panel.fit("[bold cyan]DSC Syllabus Parser[/bold cyan]\nScanning syllabus/ folder for text files...", border_style="cyan"))
    
    files = discover_syllabus_files()
    if not files:
        console.print("[bold red]No .txt files found in syllabus/ folder![/bold red]")
        console.print(f"[yellow]Please place your subject syllabus text files in: {SYLLABUS_DIR}[/yellow]")
        console.print("[yellow]Example: syllabus/Mathematics.txt, syllabus/Science.txt[/yellow]")
        return

    console.print(f"Found [green]{len(files)}[/green] syllabus files:")
    for f in files:
        console.print(f"  * {f.name}")

    client = GeminiClient()
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Parsing syllabi with Gemini...", total=None)
        syllabus = parse_all_syllabi(client=client, force=force)
        progress.update(task, completed=True)

    table = Table(title="Parsed Syllabus Hierarchy", show_header=True, header_style="bold magenta")
    table.add_column("Subject", style="cyan")
    table.add_column("Topics Count", justify="right")
    table.add_column("Concepts Count", justify="right")

    for s in syllabus.subjects:
        table.add_row(s.name, str(len(s.topics)), str(len(s.all_concepts)))

    console.print(table)
    console.print("[bold green][OK] Syllabus parsing complete![/bold green]")


@cli.command("generate")
@click.option("--subject", "-s", default=None, help="Subject name (e.g. Mathematics). If not provided, all subjects are processed.")
@click.option("--count", "-c", default=120, type=int, help="Target question count to generate for the subject.")
@click.option("--batch-size", "-b", default=GENERATION_BATCH_SIZE, type=int, help="Number of questions generated per API batch call.")
@click.option("--pause", "-p", default=PAUSE_BETWEEN_BATCHES_SECONDS, type=int, help="Seconds to pause between batches for rate limiting.")
def cmd_generate(subject: str | None, count: int, batch_size: int, pause: int):
    """Generate high-quality MCQs continuously with rate limiting and automated validation."""
    console.print(Panel.fit(f"[bold cyan]AI Question Generation Run[/bold cyan]\nTarget: {count} questions per subject | Pause: {pause}s", border_style="cyan"))

    subjects = load_all_parsed_subjects()
    if not subjects:
        console.print("[yellow]No parsed syllabus found. Running syllabus parser first...[/yellow]")
        client = GeminiClient()
        syllabus = parse_all_syllabi(client=client)
        subjects = syllabus.subjects
        if not subjects:
            console.print("[bold red]Failed to find or parse syllabus files. Please check syllabus/ directory.[/bold red]")
            return

    if subject:
        matched = [s for s in subjects if s.name.lower() == subject.lower() or s.subject_id == subject.lower()]
        if not matched:
            console.print(f"[bold red]Subject '{subject}' not found in parsed syllabus![/bold red]")
            console.print(f"Available: {[s.name for s in subjects]}")
            return
        subjects = matched

    client = GeminiClient()
    generator = QuestionGenerator(client=client)
    store = QuestionStore()

    for s in subjects:
        console.print(f"\n[bold yellow]=== Processing Subject: {s.name} ===[/bold yellow]")
        
        # Load or create blueprint
        blueprint = load_blueprint(s.name)
        if not blueprint:
            blueprint = create_auto_blueprint(s, total_questions=count)
            save_blueprint(blueprint)

        jobs = blueprint_to_generation_jobs(blueprint, s, batch_size=batch_size, overgenerate_factor=1.3)
        total_target_q = sum(j.num_questions for j in jobs)
        console.print(f"Generated [cyan]{len(jobs)}[/cyan] generation jobs (~{total_target_q} candidate questions).")

        # Setup validation & duplicate detector with existing approved questions
        existing_approved = store.load_all_approved(s.name)
        detector = DuplicateDetector()
        detector.build_index(existing_approved)
        pipeline = ValidationPipeline(duplicate_detector=detector, client=client)

        approved_count = 0
        rejected_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Generating for {s.name}...", total=len(jobs))

            for idx, job in enumerate(jobs, 1):
                progress.update(task, description=f"Job {idx}/{len(jobs)}: {job.topic} ({job.difficulty})")
                
                # Generate candidates
                raw_questions = generator.generate_batch(job)
                
                # Validate through pipeline
                for q in raw_questions:
                    pipeline.validate_single(q, subject=s)
                    store.save_question(q)
                    if q.status == QuestionStatus.APPROVED.value:
                        approved_count += 1
                    else:
                        rejected_count += 1

                progress.advance(task)

                # Stop early if we hit approved quota
                if approved_count >= count:
                    console.print(f"[bold green]Reached target of {count} approved questions for {s.name}![/bold green]")
                    break

                if idx < len(jobs):
                    progress.update(task, description=f"Pausing {pause}s for rate limit...")
                    import time
                    time.sleep(pause)

        console.print(f"[green]Subject {s.name} Complete:[/green] [bold cyan]{approved_count}[/bold cyan] Approved, [bold red]{rejected_count}[/bold red] Rejected/Revision")

    # Automatically export approved questions to CSV
    console.print("\n[bold cyan]Automatically updating question bank CSV...[/bold cyan]")
    for s in subjects:
        approved = store.load_all_approved(s.name)
        used = store.load_questions_by_status(s.name, QuestionStatus.USED.value)
        all_q = approved + used
        if all_q:
            csv_path = export_questions_to_csv(all_q, s.name)
            console.print(f"[bold green][OK] CSV updated ({len(all_q)} questions):[/bold green] [cyan]{csv_path.name}[/cyan]")


@cli.command("status")
def cmd_status():
    """Display question bank inventory and statistics."""
    store = QuestionStore()
    stats = store.get_stats()

    if not stats:
        console.print("[yellow]Question bank is currently empty.[/yellow]")
        return

    table = Table(title="Question Bank Inventory", show_header=True, header_style="bold blue")
    table.add_column("Subject", style="cyan")
    table.add_column("Approved", style="green", justify="right")
    table.add_column("Used", style="blue", justify="right")
    table.add_column("Rejected", style="red", justify="right")
    table.add_column("Revision", style="yellow", justify="right")
    table.add_column("Total", style="bold white", justify="right")

    for subject, s_stats in stats.items():
        approved = s_stats.get(QuestionStatus.APPROVED.value, 0)
        used = s_stats.get(QuestionStatus.USED.value, 0)
        rejected = s_stats.get(QuestionStatus.REJECTED.value, 0)
        rev = s_stats.get(QuestionStatus.REVISION_REQUIRED.value, 0)
        total = s_stats.get("total", 0)
        table.add_row(subject, str(approved), str(used), str(rejected), str(rev), str(total))

    console.print(table)


@cli.command("assemble-test")
@click.option("--subject", "-s", required=True, help="Subject name for the mock test")
@click.option("--count", "-c", default=120, type=int, help="Total questions for the mock test (default 120)")
@click.option("--export-csv/--no-export-csv", default=True, help="Automatically export assembled test to CSV")
def cmd_assemble_test(subject: str, count: int, export_csv: bool):
    """Assemble a balanced mock test from approved questions and validate."""
    console.print(Panel.fit(f"[bold cyan]Assembling Mock Test: {subject}[/bold cyan]\nQuestion Count: {count}", border_style="cyan"))

    store = QuestionStore()
    s_obj = load_parsed_subject(subject.lower().replace(" ", "_"))
    
    blueprint = load_blueprint(subject)
    if not blueprint:
        if s_obj:
            blueprint = create_auto_blueprint(s_obj, total_questions=count)
        else:
            blueprint = TestBlueprint(subject=subject, total_questions=count)

    assembler = TestAssembler(store=store)
    test = assembler.assemble_test(blueprint=blueprint)

    # Validate test
    report = validate_test(test)

    # Print summary
    table = Table(title=f"Test Assembly Summary - {test.subject}", show_header=True, header_style="bold green")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total Questions", str(test.total_questions))
    table.add_row("Test Date", test.test_date)
    table.add_row("Validation Status", "[green]PASSED[/green]" if report["passed"] else "[yellow]PASSED WITH WARNINGS[/yellow]")
    
    # Answer positions
    ans_dist = report["checks"].get("answer_distribution", {})
    ans_str = ", ".join(f"{k}: {v}" for k, v in sorted(ans_dist.items()))
    table.add_row("Answer Position Balance", ans_str)
    
    diff_dist = report["checks"].get("difficulty_distribution", {})
    diff_str = ", ".join(f"{k}: {v}" for k, v in diff_dist.items())
    table.add_row("Difficulty Distribution", diff_str)

    console.print(table)

    if report.get("warnings"):
        console.print("\n[yellow]Test Warnings:[/yellow]")
        for w in report["warnings"]:
            console.print(f"  * {w}")

    # Mark used in question bank
    for q in test.questions:
        store.mark_used(q.question_id, subject, test.test_id)

    # Export to CSV
    if export_csv:
        csv_path = export_test_to_csv(test)
        console.print(f"\n[bold green][OK] Test exported to CSV:[/bold green] [cyan]{csv_path}[/cyan]")


@cli.command("export")
@click.option("--subject", "-s", default=None, help="Export a specific subject (or all subjects if omitted)")
@click.option("--output-folder", "-o", default=None, help="Custom output directory")
@click.option("--timestamp", "-t", is_flag=True, default=False, help="Include timestamp in filename")
def cmd_export(subject: str | None, output_folder: str | None, timestamp: bool):
    """Export approved questions to separate CSV files per subject (question_text, correct_answer, explanation)."""
    store = QuestionStore()
    out_dir = Path(output_folder) if output_folder else DUMPS_OUTPUT_DIR

    console.print(Panel.fit(f"[bold cyan]Exporting Question Bank to CSV[/bold cyan]\nDestination: {out_dir}", border_style="cyan"))

    if subject:
        approved = store.load_all_approved(subject)
        used = store.load_questions_by_status(subject, QuestionStatus.USED.value)
        all_q = approved + used
        if not all_q:
            console.print(f"[yellow]No approved questions found for subject '{subject}'.[/yellow]")
            return
        path = export_questions_to_csv(all_q, subject, output_dir=out_dir, include_timestamp=timestamp)
        console.print(f"[bold green][OK] Exported {len(all_q)} questions to {path.name}[/bold green]")
    else:
        files = export_all_subjects_to_csv(store, output_dir=out_dir, include_timestamp=timestamp)
        if not files:
            console.print("[yellow]No approved questions available across any subject to export.[/yellow]")
            return
        console.print(f"[bold green][OK] Successfully exported {len(files)} subject CSV files:[/bold green]")
        for f in files:
            console.print(f"  * {f.name}")


@cli.command("full-run")
@click.option("--count", "-c", default=120, type=int, help="Questions per subject")
def cmd_full_run(count: int):
    """End-to-end automated pipeline: parse syllabus -> generate -> validate -> assemble tests -> export CSVs."""
    console.print(Panel.fit(
        f"[bold green]DSC AI End-to-End Automated Pipeline[/bold green]\n"
        f"1. Parse Syllabus Text\n"
        f"2. Generate & Validate Questions ({count}/subject)\n"
        f"3. Assemble Balanced Mock Tests\n"
        f"4. Export Subject CSVs",
        border_style="green"
    ))

    # 1. Parse
    console.print("\n[bold cyan]Step 1/4: Parsing Syllabus Files...[/bold cyan]")
    client = GeminiClient()
    syllabus = parse_all_syllabi(client=client)
    if not syllabus.subjects:
        console.print("[bold red]No syllabus subjects available. Please add .txt files to syllabus/ directory.[/bold red]")
        return

    # 2. Generate for each subject
    console.print("\n[bold cyan]Step 2/4: Generating & Validating Questions...[/bold cyan]")
    store = QuestionStore()
    generator = QuestionGenerator(client=client)

    for s in syllabus.subjects:
        blueprint = create_auto_blueprint(s, total_questions=count)
        save_blueprint(blueprint)
        jobs = blueprint_to_generation_jobs(blueprint, s, batch_size=GENERATION_BATCH_SIZE, overgenerate_factor=1.3)
        
        detector = DuplicateDetector()
        detector.build_index(store.load_all_approved(s.name))
        pipeline = ValidationPipeline(duplicate_detector=detector, client=client)

        approved = 0
        for idx, job in enumerate(jobs, 1):
            raw = generator.generate_batch(job)
            for q in raw:
                pipeline.validate_single(q, subject=s)
                store.save_question(q)
                if q.status == QuestionStatus.APPROVED.value:
                    approved += 1
            if approved >= count:
                break
            if idx < len(jobs):
                import time
                time.sleep(PAUSE_BETWEEN_BATCHES_SECONDS)

    # 3. Assemble tests
    console.print("\n[bold cyan]Step 3/4: Assembling Balanced Mock Tests...[/bold cyan]")
    assembler = TestAssembler(store=store)
    for s in syllabus.subjects:
        bp = load_blueprint(s.name) or create_auto_blueprint(s, total_questions=count)
        test = assembler.assemble_test(blueprint=bp)
        validate_test(test)
        export_test_to_csv(test)

    # 4. Export all CSV dumps
    console.print("\n[bold cyan]Step 4/4: Exporting CSV Files per Subject...[/bold cyan]")
    files = export_all_subjects_to_csv(store)

    console.print("\n[bold green][DONE] FULL PIPELINE COMPLETED SUCCESSFULLY![/bold green]")
    console.print(f"Generated CSVs available in: [cyan]{OUTPUT_DIR}[/cyan]")


if __name__ == "__main__":
    cli()
