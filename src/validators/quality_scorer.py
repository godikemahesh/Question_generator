"""
Validator 6 — Quality Scoring.
Scores each question on 6 dimensions and determines final status.
Can use LLM for detailed review or rely on aggregated validator scores.
"""
from __future__ import annotations
import logging

from config.settings import (
    QUALITY_APPROVE_THRESHOLD,
    QUALITY_MONITOR_THRESHOLD,
    QUALITY_REVISION_THRESHOLD,
)
from src.question_bank.models import Question, QualityScores, ValidationResult, QuestionStatus
from src.generator.gemini_client import GeminiClient
from src.generator.prompts import QUALITY_REVIEW_PROMPT

logger = logging.getLogger(__name__)


def score_from_validators(question: Question) -> QualityScores:
    """
    Build quality scores from the individual validator results
    already attached to the question.
    """
    scores = QualityScores()
    
    for vr in question.validation_results:
        if vr.validator_name == "schema":
            scores.clarity = vr.score
        elif vr.validator_name == "syllabus":
            scores.syllabus_alignment = vr.score
        elif vr.validator_name == "answer":
            scores.correctness = vr.score
        elif vr.validator_name == "distractor":
            scores.distractor_quality = vr.score
        elif vr.validator_name == "duplicate":
            scores.originality = vr.score

    # Difficulty accuracy defaults to 80 (hard to assess without LLM)
    if scores.difficulty_accuracy == 0:
        scores.difficulty_accuracy = 80.0

    # Fill in defaults for any missing scores
    if scores.clarity == 0:
        scores.clarity = 75.0
    if scores.correctness == 0:
        scores.correctness = 75.0

    return scores


def score_with_llm(question: Question, client: GeminiClient) -> QualityScores | None:
    """
    Use Gemini for detailed quality review.
    Only use for borderline questions to save API costs.
    """
    prompt = QUALITY_REVIEW_PROMPT.format(
        subject=question.subject,
        topic=question.topic,
        question_text=question.question_text,
        option_a=question.option_a,
        option_b=question.option_b,
        option_c=question.option_c,
        option_d=question.option_d,
        correct_option=question.correct_option,
        explanation=question.explanation,
        difficulty=question.difficulty,
    )

    try:
        result = client.generate_json(prompt, temperature=0.1)
    except Exception as e:
        logger.error(f"Quality review LLM call failed: {e}")
        return None

    if not result or not isinstance(result, dict):
        return None

    return QualityScores(
        correctness=float(result.get("correctness", 75)),
        syllabus_alignment=float(result.get("syllabus_alignment", 75)),
        clarity=float(result.get("clarity", 75)),
        distractor_quality=float(result.get("distractor_quality", 75)),
        difficulty_accuracy=float(result.get("difficulty_accuracy", 75)),
        originality=float(result.get("originality", 75)),
    )


def compute_quality_score(
    question: Question,
    client: GeminiClient | None = None,
    use_llm_for_borderline: bool = True,
) -> ValidationResult:
    """
    Compute the final quality score and determine question status.
    
    Strategy:
    1. First compute scores from validator results (free)
    2. If borderline (70-90), optionally use LLM for detailed review
    3. Set final status based on weighted score
    """
    # Step 1: Score from validators
    scores = score_from_validators(question)
    total = scores.weighted_total

    # Step 2: LLM review for borderline questions
    if (use_llm_for_borderline and client and 
            QUALITY_REVISION_THRESHOLD <= total <= QUALITY_APPROVE_THRESHOLD):
        logger.info(f"Borderline question (score={total:.1f}), running LLM quality review...")
        llm_scores = score_with_llm(question, client)
        if llm_scores:
            # Average the two scores
            scores.correctness = (scores.correctness + llm_scores.correctness) / 2
            scores.syllabus_alignment = (scores.syllabus_alignment + llm_scores.syllabus_alignment) / 2
            scores.clarity = (scores.clarity + llm_scores.clarity) / 2
            scores.distractor_quality = (scores.distractor_quality + llm_scores.distractor_quality) / 2
            scores.difficulty_accuracy = (scores.difficulty_accuracy + llm_scores.difficulty_accuracy) / 2
            scores.originality = (scores.originality + llm_scores.originality) / 2
            total = scores.weighted_total

    # Step 3: Determine status
    question.quality_scores = scores
    question.quality_score = round(total, 2)

    if total >= QUALITY_APPROVE_THRESHOLD:
        status_label = "APPROVED"
        question.update_status(QuestionStatus.APPROVED)
    elif total >= QUALITY_MONITOR_THRESHOLD:
        status_label = "APPROVED (monitor)"
        question.update_status(QuestionStatus.APPROVED)
    elif total >= QUALITY_REVISION_THRESHOLD:
        status_label = "REVISION_REQUIRED"
        question.update_status(QuestionStatus.REVISION_REQUIRED)
    else:
        status_label = "REJECTED"
        question.update_status(QuestionStatus.REJECTED)

    logger.info(f"Quality score: {total:.1f} → {status_label}")

    return ValidationResult(
        validator_name="quality",
        passed=total >= QUALITY_REVISION_THRESHOLD,
        score=total,
        details={
            "status": status_label,
            "correctness": scores.correctness,
            "syllabus_alignment": scores.syllabus_alignment,
            "clarity": scores.clarity,
            "distractor_quality": scores.distractor_quality,
            "difficulty_accuracy": scores.difficulty_accuracy,
            "originality": scores.originality,
            "weighted_total": round(total, 2),
        },
    )
