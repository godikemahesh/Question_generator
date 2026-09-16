"""
Validation Pipeline Orchestrator.
Chains together all 6 validators:
1. Schema Validation (Deterministic)
2. Syllabus Validation (Deterministic / Keywords)
3. Answer Validation (SymPy math solver + optional LLM verification)
4. Distractor Validation (Heuristics + plausibility)
5. Duplicate Detection (Level 1: Exact Hash, Level 2: TF-IDF Semantic, Level 3: Pattern)
6. Quality Scoring (Weighted multi-dimension scoring & status assignment)
"""
from __future__ import annotations
import logging
from typing import Optional

from src.question_bank.models import Question, QuestionStatus, ValidationResult
from src.syllabus.models import Subject
from src.generator.gemini_client import GeminiClient
from src.validators.schema_validator import validate_schema
from src.validators.syllabus_validator import validate_syllabus
from src.validators.answer_validator import validate_answer
from src.validators.distractor_validator import validate_distractors
from src.validators.duplicate_detector import DuplicateDetector
from src.validators.quality_scorer import compute_quality_score

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """Orchestrates all validation stages for generated questions."""

    def __init__(
        self,
        duplicate_detector: Optional[DuplicateDetector] = None,
        client: Optional[GeminiClient] = None,
    ):
        self.duplicate_detector = duplicate_detector or DuplicateDetector()
        self.client = client

    def validate_single(
        self,
        question: Question,
        subject: Optional[Subject] = None,
        verify_answers_with_llm: bool = False,
    ) -> Question:
        """
        Run a single question through all stages of the validation pipeline.
        Updates question.validation_results and question.status in-place.
        """
        question.update_status(QuestionStatus.VALIDATING)
        question.validation_results = []

        # 1. Schema Validation
        res_schema = validate_schema(question)
        question.validation_results.append(res_schema)
        if not res_schema.passed:
            question.update_status(QuestionStatus.REJECTED)
            question.quality_score = 0.0
            return question

        # 2. Syllabus Validation
        res_syllabus = validate_syllabus(question, subject=subject)
        question.validation_results.append(res_syllabus)

        # 3. Answer Validation
        ans_client = self.client if verify_answers_with_llm else None
        res_answer = validate_answer(question, client=ans_client)
        question.validation_results.append(res_answer)

        # 4. Distractor Validation
        res_distractor = validate_distractors(question)
        question.validation_results.append(res_distractor)

        # 5. Duplicate Detection
        res_duplicate = self.duplicate_detector.check_duplicate(question)
        question.validation_results.append(res_duplicate)
        if not res_duplicate.passed:
            question.update_status(QuestionStatus.REJECTED)
            question.quality_score = 10.0
            return question

        # 6. Quality Scoring
        res_quality = compute_quality_score(
            question,
            client=self.client,
            use_llm_for_borderline=False,  # Keep fast and low cost
        )
        question.validation_results.append(res_quality)

        # If approved, add to duplicate detector index so future questions compare against it
        if question.status == QuestionStatus.APPROVED.value:
            self.duplicate_detector.add_to_index(question)

        return question

    def validate_batch(
        self,
        questions: list[Question],
        subject: Optional[Subject] = None,
        verify_answers_with_llm: bool = False,
    ) -> list[Question]:
        """Validate a list of questions."""
        validated = []
        for q in questions:
            v_q = self.validate_single(
                q,
                subject=subject,
                verify_answers_with_llm=verify_answers_with_llm,
            )
            validated.append(v_q)
        return validated
