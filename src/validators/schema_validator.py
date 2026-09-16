"""
Validator 1 — Schema Validation.
Pure deterministic structural checks using Pydantic. No LLM calls.
"""
from __future__ import annotations
import logging

from src.question_bank.models import Question, ValidationResult

logger = logging.getLogger(__name__)

VALID_OPTIONS = {"A", "B", "C", "D"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_QUESTION_TYPES = {"conceptual", "application", "problem_solving", "scenario_based", "analytical"}


def validate_schema(question: Question) -> ValidationResult:
    """
    Check structural integrity of a question.
    Returns ValidationResult with pass/fail and specific errors.
    """
    errors = []
    warnings = []

    # Question text
    if not question.question_text or len(question.question_text.strip()) < 10:
        errors.append("Question text is missing or too short (< 10 chars)")

    # Options — all 4 must exist and be non-empty
    options = {
        "A": question.option_a,
        "B": question.option_b,
        "C": question.option_c,
        "D": question.option_d,
    }
    for label, text in options.items():
        if not text or not text.strip():
            errors.append(f"Option {label} is empty")

    # Check for duplicate options
    option_values = [v.strip().lower() for v in options.values() if v and v.strip()]
    if len(option_values) != len(set(option_values)):
        errors.append("Duplicate options detected")

    # Correct option
    if not question.correct_option:
        errors.append("Correct option is missing")
    elif question.correct_option.upper() not in VALID_OPTIONS:
        errors.append(f"Invalid correct option: '{question.correct_option}' (must be A/B/C/D)")

    # Explanation
    if not question.explanation or len(question.explanation.strip()) < 5:
        errors.append("Explanation is missing or too short")

    # Difficulty
    if question.difficulty and question.difficulty.lower() not in VALID_DIFFICULTIES:
        warnings.append(f"Non-standard difficulty: '{question.difficulty}'")

    # Question type
    if question.question_type and question.question_type.lower() not in VALID_QUESTION_TYPES:
        warnings.append(f"Non-standard question type: '{question.question_type}'")

    # Subject
    if not question.subject:
        errors.append("Subject is missing")

    # Topic
    if not question.topic:
        warnings.append("Topic is missing")

    # Length checks
    if len(question.question_text) > 2000:
        warnings.append("Question text is very long (> 2000 chars)")

    for label, text in options.items():
        if text and len(text) > 500:
            warnings.append(f"Option {label} is very long (> 500 chars)")

    passed = len(errors) == 0
    score = 100.0 if passed else max(0, 100 - len(errors) * 25)

    return ValidationResult(
        validator_name="schema",
        passed=passed,
        score=score,
        errors=errors,
        warnings=warnings,
    )
