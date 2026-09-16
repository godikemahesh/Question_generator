"""
Question Generator — Orchestrator.
Manages the end-to-end generation flow: job → context → prompt → Gemini → questions.
Runs continuously with pauses between batches to respect API rate limits.
"""
from __future__ import annotations
import logging
import time
from datetime import datetime

from config.settings import GENERATION_BATCH_SIZE, PAUSE_BETWEEN_BATCHES_SECONDS
from src.generator.gemini_client import GeminiClient
from src.generator.prompts import QUESTION_GENERATION_PROMPT
from src.knowledge.retriever import KnowledgeRetriever
from src.templates.engine import TemplateEngine
from src.question_bank.models import Question, GenerationJob, QuestionStatus

logger = logging.getLogger(__name__)


class QuestionGenerator:
    """Orchestrates AI question generation with rate-limited continuous operation."""

    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient()
        self.retriever = KnowledgeRetriever()
        self.template_engine = TemplateEngine()
        self.template_engine.load_custom_templates()

        # Stats
        self.total_generated = 0
        self.total_failed = 0
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def generate_batch(self, job: GenerationJob) -> list[Question]:
        """
        Generate a batch of questions for a single GenerationJob.
        
        Returns list of Question objects (not yet validated).
        """
        logger.info(
            f"Generating {job.num_questions} questions: "
            f"{job.subject} / {job.topic} / {job.difficulty} / {job.question_type}"
        )

        # 1. Retrieve syllabus context
        query = f"{job.topic} {job.subtopic}".strip()
        reference_context = self.retriever.retrieve(job.subject, query)
        if not reference_context:
            reference_context = f"Topic: {job.topic}. Subtopic: {job.subtopic}."

        # 2. Get template instruction
        template = self.template_engine.get_template_for_job(job.subject, job.question_type)
        template_instruction = self.template_engine.get_template_instruction(template)
        template_id = template.get("template_id", "") if template else ""

        # 3. Build prompt
        prompt = QUESTION_GENERATION_PROMPT.format(
            num_questions=job.num_questions,
            subject=job.subject,
            topic=job.topic,
            subtopic=job.subtopic or "General",
            difficulty=job.difficulty,
            question_type=job.question_type,
            template_instruction=template_instruction,
            reference_context=reference_context[:4000],  # Cap context size
        )

        # 4. Call Gemini
        try:
            result = self.client.generate_json(prompt, temperature=0.7)
        except Exception as e:
            logger.error(f"Generation failed for job {job.job_id}: {e}")
            self.total_failed += 1
            job.status = "failed"
            return []

        if not result or not isinstance(result, list):
            logger.error(f"Invalid response format for job {job.job_id}")
            self.total_failed += 1
            job.status = "failed"
            return []

        # 5. Parse into Question objects
        questions = []
        for i, item in enumerate(result):
            try:
                q = Question(
                    exam_id="dsc",
                    subject=job.subject,
                    topic=job.topic,
                    subtopic=job.subtopic,
                    concept_id=job.concept_id,
                    question_text=item.get("question_text", ""),
                    option_a=item.get("option_a", ""),
                    option_b=item.get("option_b", ""),
                    option_c=item.get("option_c", ""),
                    option_d=item.get("option_d", ""),
                    correct_option=item.get("correct_option", "").upper(),
                    explanation=item.get("explanation", ""),
                    difficulty=item.get("difficulty", job.difficulty),
                    question_type=item.get("question_type", job.question_type),
                    template_id=template_id,
                    status=QuestionStatus.GENERATED.value,
                    generation_model=self.client.model_name,
                    generation_run_id=self.run_id,
                )
                q.set_correct_answer_text()
                questions.append(q)
            except Exception as e:
                logger.warning(f"Failed to parse question {i}: {e}")

        self.total_generated += len(questions)
        job.generated_count = len(questions)
        job.status = "completed"

        logger.info(f"Generated {len(questions)}/{job.num_questions} questions for {job.topic}")
        return questions

    def run_generation_jobs(
        self,
        jobs: list[GenerationJob],
        pause_seconds: int | None = None,
    ) -> list[Question]:
        """
        Run multiple generation jobs continuously with pauses between batches.
        
        Args:
            jobs: List of generation jobs to execute
            pause_seconds: Seconds to pause between batches (defaults to config)
            
        Returns:
            All generated questions (not yet validated)
        """
        pause = pause_seconds or PAUSE_BETWEEN_BATCHES_SECONDS
        all_questions = []
        total_jobs = len(jobs)

        logger.info(f"Starting generation run: {total_jobs} jobs, {sum(j.num_questions for j in jobs)} target questions")
        logger.info(f"Pause between batches: {pause}s")

        for i, job in enumerate(jobs, 1):
            logger.info(f"--- Job {i}/{total_jobs} ---")
            job.status = "running"

            questions = self.generate_batch(job)
            all_questions.extend(questions)

            # Pause between batches to stay within API limits
            if i < total_jobs:
                logger.info(f"Pausing {pause}s before next batch... (generated so far: {len(all_questions)})")
                time.sleep(pause)

        logger.info(
            f"Generation run complete: {len(all_questions)} questions generated, "
            f"{self.total_failed} failed jobs"
        )
        return all_questions

    def get_stats(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_generated": self.total_generated,
            "total_failed": self.total_failed,
            "api_stats": self.client.get_stats(),
        }
