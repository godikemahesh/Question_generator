"""
Validator 4 — Distractor Validation.
Checks that wrong options (distractors) are plausible and well-crafted.
"""
from __future__ import annotations
import logging
import re
from difflib import SequenceMatcher

from src.question_bank.models import Question, ValidationResult

logger = logging.getLogger(__name__)


def _similarity(a: str, b: str) -> float:
    """String similarity ratio between two texts."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def validate_distractors(question: Question) -> ValidationResult:
    """
    Check distractor quality:
    - Are distractors plausible?
    - Are they distinct from each other?
    - Is one option obviously absurd?
    - Could more than one be arguably correct?
    """
    errors = []
    warnings = []
    score = 100.0

    options = {
        "A": question.option_a,
        "B": question.option_b,
        "C": question.option_c,
        "D": question.option_d,
    }

    correct_key = question.correct_option.upper()
    correct_text = options.get(correct_key, "")

    # Get distractor texts
    distractors = {k: v for k, v in options.items() if k != correct_key}

    # 1. Check for near-identical options (exclude standard Assertion-Reason / Statement evaluation boilerplate)
    is_statement_or_ar = any(
        kw in question.question_text.lower()
        for kw in ["assertion", "reason (r)", "statement i", "statement ii", "which of the statements"]
    ) or any(
        all(term in v.lower() for term in ["statement", "correct"]) or
        ("assertion" in v.lower() and "reason" in v.lower())
        for v in options.values()
    )

    if not is_statement_or_ar:
        option_list = list(options.items())
        for i in range(len(option_list)):
            for j in range(i + 1, len(option_list)):
                k1, v1 = option_list[i]
                k2, v2 = option_list[j]
                sim = _similarity(v1, v2)
                if sim > 0.95:
                    errors.append(f"Options {k1} and {k2} are nearly identical ({sim:.2f})")
                    score -= 25
                elif sim > 0.85:
                    warnings.append(f"Options {k1} and {k2} are very similar ({sim:.2f})")
                    score -= 10

    # 2. Check for length disparity & wording giveaways (Distractor Parity)
    correct_len = len(correct_text)
    dist_lens = [len(v) for v in distractors.values()]
    avg_dist_len = sum(dist_lens) / max(len(dist_lens), 1)

    if correct_len > 25 and avg_dist_len > 0:
        length_ratio = correct_len / avg_dist_len
        if length_ratio > 1.6:
            warnings.append(
                f"Correct answer ({correct_len} chars) is noticeably longer than average distractor "
                f"({avg_dist_len:.0f} chars) — potential wording clue"
            )
            score -= 15
        elif length_ratio < 0.5:
            warnings.append(
                f"Correct answer ({correct_len} chars) is noticeably shorter than average distractor "
                f"({avg_dist_len:.0f} chars) — potential wording clue"
            )
            score -= 10

    for k, v in distractors.items():
        dist_len = len(v)
        if correct_len > 0:
            ratio = dist_len / correct_len
            if ratio < 0.35 and correct_len > 15:
                warnings.append(f"Option {k} is much shorter than correct answer — low plausibility distractor")
                score -= 8
            elif ratio > 2.5 and dist_len > 60:
                warnings.append(f"Option {k} is disproportionately longer than other options")
                score -= 8

    # 3. Check for "None of the above" / "All of the above" patterns
    for k, v in options.items():
        v_lower = v.lower().strip()
        if v_lower in ("none of the above", "all of the above", "none", "all"):
            warnings.append(f"Option {k} uses 'none/all of the above' — consider replacing")
            score -= 5

    # 4. Check for numeric distractors in math questions — are they reasonable?
    correct_nums = re.findall(r'[\d,.]+', correct_text)
    if correct_nums:
        try:
            correct_val = float(correct_nums[0].replace(",", ""))
            for k, v in distractors.items():
                dist_nums = re.findall(r'[\d,.]+', v)
                if dist_nums:
                    try:
                        dist_val = float(dist_nums[0].replace(",", ""))
                        if correct_val != 0:
                            ratio = dist_val / correct_val
                            if ratio > 100 or ratio < 0.01:
                                warnings.append(
                                    f"Option {k} ({dist_val}) is wildly different from "
                                    f"correct ({correct_val}) — may be obviously wrong"
                                )
                                score -= 5
                    except ValueError:
                        pass
        except ValueError:
            pass

    # 5. Check all options have consistent format (e.g., all numbers or all text)
    has_number = [bool(re.search(r'\d', v)) for v in options.values()]
    if any(has_number) and not all(has_number):
        # Mixed format might be fine, but worth noting
        pass

    passed = len(errors) == 0 and score >= 60

    return ValidationResult(
        validator_name="distractor",
        passed=passed,
        score=max(0, min(100, score)),
        errors=errors,
        warnings=warnings,
    )
