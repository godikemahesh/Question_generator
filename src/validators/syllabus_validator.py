"""
Validator 2 — Syllabus Validation.
Verifies question matches the requested topic/concept and is within DSC exam scope.
"""
from __future__ import annotations
import logging

from src.question_bank.models import Question, ValidationResult
from src.syllabus.models import Subject

logger = logging.getLogger(__name__)


def validate_syllabus(question: Question, subject: Subject | None = None) -> ValidationResult:
    """
    Check that the question aligns with its stated topic and subject.
    Uses keyword matching against the parsed syllabus structure.
    """
    errors = []
    warnings = []
    score = 100.0

    # Basic checks
    if not question.subject:
        errors.append("No subject specified")
        return ValidationResult(
            validator_name="syllabus", passed=False, score=0, errors=errors
        )

    if not question.topic:
        warnings.append("No topic specified — cannot verify syllabus alignment")
        score -= 10

    # If we have the parsed subject structure, do deeper validation
    if subject:
        # Check topic exists in syllabus
        topic_names = [t.name.lower() for t in subject.topics]
        if question.topic and question.topic.lower() not in topic_names:
            # Fuzzy check — topic might be worded differently
            found = False
            for tn in topic_names:
                if question.topic.lower() in tn or tn in question.topic.lower():
                    found = True
                    break
            if not found:
                warnings.append(
                    f"Topic '{question.topic}' not found in parsed syllabus. "
                    f"Available: {[t.name for t in subject.topics]}"
                )
                score -= 15

        # Check question text contains relevant keywords
        all_keywords = set()
        for topic in subject.topics:
            for st in topic.subtopics:
                for concept in st.concepts:
                    all_keywords.update(kw.lower() for kw in concept.keywords)
                    all_keywords.add(concept.name.lower())

        if all_keywords:
            q_lower = question.question_text.lower()
            matching_keywords = [kw for kw in all_keywords if kw in q_lower]
            if not matching_keywords:
                warnings.append("No syllabus keywords found in question text")
                score -= 10
    else:
        # Without parsed syllabus, do basic sanity check
        # At least verify the question text mentions something related to the topic
        if question.topic:
            topic_words = question.topic.lower().split()
            q_lower = question.question_text.lower()
            matching = [w for w in topic_words if w in q_lower and len(w) > 3]
            if not matching:
                warnings.append(
                    f"Question text may not be related to topic '{question.topic}'"
                )
                score -= 10

    passed = len(errors) == 0 and score >= 70

    return ValidationResult(
        validator_name="syllabus",
        passed=passed,
        score=max(0, score),
        errors=errors,
        warnings=warnings,
    )
