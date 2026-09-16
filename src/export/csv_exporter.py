"""
CSV Exporter.
Exports questions and tests to CSV files — one CSV per subject.
Format: question_text, correct_answer, explanation
"""
from __future__ import annotations
import csv
import logging
from datetime import datetime
from pathlib import Path

from config.settings import OUTPUT_DIR, TESTS_OUTPUT_DIR, DUMPS_OUTPUT_DIR
from src.question_bank.models import Question, AssembledTest

logger = logging.getLogger(__name__)


def export_questions_to_csv(
    questions: list[Question],
    subject: str,
    output_dir: Path | None = None,
    filename: str | None = None,
    include_timestamp: bool = False,
) -> Path:
    """
    Export questions to a CSV file.
    Format: question_text, correct_answer, explanation
    
    Args:
        questions: List of Question objects
        subject: Subject name (used in filename)
        output_dir: Output directory (defaults to output/question_dumps/)
        filename: Custom filename (optional)
        include_timestamp: Whether to append a timestamp to the filename (default: False)
    
    Returns:
        Path to the created CSV file
    """
    out_dir = output_dir or DUMPS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        safe_subject = subject.lower().replace(" ", "_")
        if include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_subject}_questions_{timestamp}.csv"
        else:
            filename = f"{safe_subject}_questions.csv"

    filepath = out_dir / filename

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["question_text", "correct_answer", "explanation"])

        for q in questions:
            correct_text = _get_correct_answer_text(q)
            writer.writerow([
                q.question_text,
                correct_text,
                q.explanation,
            ])

    logger.info(f"Exported {len(questions)} questions to {filepath}")
    return filepath


def export_test_to_csv(test: AssembledTest, output_dir: Path | None = None) -> Path:
    """
    Export an assembled test to a CSV file.
    Format: question_text, correct_answer, explanation
    """
    out_dir = output_dir or TESTS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_subject = test.subject.lower().replace(" ", "_")
    filename = f"{safe_subject}_test_{test.test_date}_{test.test_id[:8]}.csv"
    filepath = out_dir / filename

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["question_text", "correct_answer", "explanation"])

        for q in test.questions:
            correct_text = _get_correct_answer_text(q)
            writer.writerow([
                q.question_text,
                correct_text,
                q.explanation,
            ])

    logger.info(f"Exported test ({len(test.questions)} questions) to {filepath}")
    return filepath


def export_all_subjects_to_csv(
    store,
    output_dir: Path | None = None,
    include_timestamp: bool = False,
) -> list[Path]:
    """
    Export all approved questions to separate CSV files per subject.
    
    Returns list of created file paths.
    """
    from src.question_bank.models import QuestionStatus

    out_dir = output_dir or DUMPS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    created_files = []
    subjects = store.get_all_subjects()

    for subject in subjects:
        approved = store.load_questions_by_status(subject, QuestionStatus.APPROVED.value)
        used = store.load_questions_by_status(subject, QuestionStatus.USED.value)
        all_questions = approved + used

        if not all_questions:
            logger.info(f"No questions for {subject}, skipping")
            continue

        filepath = export_questions_to_csv(
            all_questions,
            subject,
            out_dir,
            include_timestamp=include_timestamp,
        )
        created_files.append(filepath)

    logger.info(f"Exported {len(created_files)} subject CSV files")
    return created_files


def _get_correct_answer_text(question: Question) -> str:
    """Get the text of the correct answer option."""
    if question.correct_answer_text:
        return question.correct_answer_text

    option_map = {
        "A": question.option_a,
        "B": question.option_b,
        "C": question.option_c,
        "D": question.option_d,
    }
    return option_map.get(question.correct_option.upper(), "")
