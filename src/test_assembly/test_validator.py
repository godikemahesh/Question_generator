"""
Test-level Validation.
Even if every question is good, the whole test can be bad.
Validates distribution, balance, repetition at the test level.
"""
from __future__ import annotations
import logging
from collections import Counter

from config.settings import MAX_SAME_CONCEPT_PER_TEST
from src.question_bank.models import AssembledTest

logger = logging.getLogger(__name__)


def validate_test(test: AssembledTest) -> dict:
    """
    Run test-level QA checks.
    Returns a report dict with pass/fail and details.
    """
    report = {
        "passed": True,
        "total_questions": len(test.questions),
        "checks": {},
        "warnings": [],
        "errors": [],
    }

    questions = test.questions

    # 1. Total count
    report["checks"]["total_count"] = len(questions)

    # 2. Topic distribution
    topic_counts = Counter(q.topic for q in questions)
    report["checks"]["topic_distribution"] = dict(topic_counts)

    # Check for extreme imbalance
    if topic_counts:
        max_topic_count = max(topic_counts.values())
        if max_topic_count > len(questions) * 0.5:
            report["warnings"].append(
                f"Topic '{topic_counts.most_common(1)[0][0]}' has {max_topic_count} questions "
                f"({max_topic_count/len(questions)*100:.0f}% of test)"
            )

    # 3. Difficulty distribution
    diff_counts = Counter(q.difficulty.lower() for q in questions)
    report["checks"]["difficulty_distribution"] = dict(diff_counts)

    medium_pct = diff_counts.get("medium", 0) / max(len(questions), 1)
    if medium_pct > 0.85:
        report["warnings"].append(f"Too many medium questions: {medium_pct*100:.0f}%")

    # 4. Question-type distribution
    type_counts = Counter(q.question_type for q in questions)
    report["checks"]["question_type_distribution"] = dict(type_counts)

    # 5. Concept repetition
    concept_counts = Counter(q.concept_id for q in questions if q.concept_id)
    over_repeated = {c: n for c, n in concept_counts.items() if n > MAX_SAME_CONCEPT_PER_TEST}
    report["checks"]["concept_repetition"] = dict(concept_counts)
    if over_repeated:
        report["warnings"].append(
            f"Concepts repeated > {MAX_SAME_CONCEPT_PER_TEST} times: {over_repeated}"
        )

    # 6. Answer position balance
    answer_counts = Counter(q.correct_option.upper() for q in questions)
    report["checks"]["answer_distribution"] = dict(answer_counts)

    expected = len(questions) / 4
    for opt in ["A", "B", "C", "D"]:
        count = answer_counts.get(opt, 0)
        deviation = abs(count - expected) / max(expected, 1)
        if deviation > 0.3:
            report["warnings"].append(
                f"Answer position {opt} is imbalanced: {count} "
                f"(expected ~{expected:.0f})"
            )

    # 7. Answer-position streaks
    max_streak = 1
    current_streak = 1
    for i in range(1, len(questions)):
        if questions[i].correct_option == questions[i-1].correct_option:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1

    report["checks"]["max_answer_streak"] = max_streak
    if max_streak >= 4:
        report["warnings"].append(f"Answer position streak of {max_streak} detected")

    # 8. Duplicate question check (within test)
    q_texts = [q.question_text.lower().strip() for q in questions]
    duplicates = [t for t, c in Counter(q_texts).items() if c > 1]
    if duplicates:
        report["errors"].append(f"Duplicate questions within test: {len(duplicates)}")
        report["passed"] = False

    # Final pass/fail
    if report["errors"]:
        report["passed"] = False

    test.validation_passed = report["passed"]
    test.validation_report = report

    status = "PASSED" if report["passed"] else "FAILED"
    logger.info(f"Test validation {status}: {len(report['warnings'])} warnings, {len(report['errors'])} errors")

    return report
