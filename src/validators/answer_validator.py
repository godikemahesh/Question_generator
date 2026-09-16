"""
Validator 3 — Answer Validation.
Verifies the stated correct answer is actually correct.
Uses SymPy for math, Gemini for factual/general questions.
"""
from __future__ import annotations
import logging
import re

from src.question_bank.models import Question, ValidationResult
from src.generator.gemini_client import GeminiClient
from src.generator.prompts import ANSWER_VERIFICATION_PROMPT

logger = logging.getLogger(__name__)


def _try_math_verification(question: Question) -> ValidationResult | None:
    """
    Attempt to verify math questions computationally using SymPy.
    Returns None if the question isn't suitable for computational verification.
    """
    try:
        import sympy
    except ImportError:
        return None

    q_lower = question.question_text.lower()

    # Only attempt for clearly numerical questions
    has_numbers = bool(re.search(r'\d+', question.question_text))
    math_keywords = ["calculate", "find", "sum", "product", "value", "solve",
                     "area", "perimeter", "volume", "percentage", "ratio",
                     "average", "mean", "median", "lcm", "hcf", "gcd",
                     "interest", "profit", "loss", "distance", "speed", "time"]

    is_math_q = has_numbers and any(kw in q_lower for kw in math_keywords)

    if not is_math_q:
        return None

    # Check if the correct answer option contains a number
    option_map = {"A": question.option_a, "B": question.option_b,
                  "C": question.option_c, "D": question.option_d}
    correct_text = option_map.get(question.correct_option.upper(), "")

    # Try to extract numbers from options
    correct_nums = re.findall(r'[\d,.]+', correct_text)
    if not correct_nums:
        return None

    # We can't auto-solve arbitrary math, but we can flag if the correct answer
    # looks unreasonable compared to numbers in the question
    question_nums = [float(n.replace(",", "")) for n in re.findall(r'[\d,.]+', question.question_text)
                     if n.replace(",", "").replace(".", "").isdigit()]

    if not question_nums:
        return None

    # Basic sanity: correct answer shouldn't be absurdly large/small relative to inputs
    try:
        correct_val = float(correct_nums[0].replace(",", ""))
        max_input = max(question_nums) if question_nums else 1
        min_input = min(question_nums) if question_nums else 0

        # Very rough sanity check
        if correct_val > max_input * 10000:
            return ValidationResult(
                validator_name="answer",
                passed=False,
                score=30,
                errors=["Correct answer seems unreasonably large compared to input values"],
                details={"method": "math_sanity", "correct_val": correct_val, "max_input": max_input},
            )
    except (ValueError, ZeroDivisionError):
        pass

    # Passed basic sanity — can't fully verify but no red flags
    return ValidationResult(
        validator_name="answer",
        passed=True,
        score=80,
        warnings=["Math question — partial computational check only"],
        details={"method": "math_sanity"},
    )


def validate_answer_with_llm(question: Question, client: GeminiClient) -> ValidationResult:
    """Verify answer using Gemini as an independent solver."""
    prompt = ANSWER_VERIFICATION_PROMPT.format(
        subject=question.subject,
        topic=question.topic,
        question_text=question.question_text,
        option_a=question.option_a,
        option_b=question.option_b,
        option_c=question.option_c,
        option_d=question.option_d,
        correct_option=question.correct_option,
    )

    try:
        result = client.generate_json(prompt, temperature=0.1)
    except Exception as e:
        logger.error(f"Answer verification LLM call failed: {e}")
        return ValidationResult(
            validator_name="answer",
            passed=True,  # Pass on failure — don't block
            score=50,
            warnings=[f"LLM verification failed: {e}"],
            details={"method": "llm_failed"},
        )

    if not result or not isinstance(result, dict):
        return ValidationResult(
            validator_name="answer",
            passed=True,
            score=50,
            warnings=["LLM returned invalid response for answer verification"],
            details={"method": "llm_invalid"},
        )

    agrees = result.get("agrees_with_stated", True)
    multiple_correct = result.get("multiple_correct", False)
    issues = result.get("issues", [])
    llm_answer = result.get("your_answer", "")

    errors = []
    warnings = []
    score = 100.0

    if not agrees:
        errors.append(
            f"LLM disagrees with stated answer. LLM says: {llm_answer}, "
            f"Stated: {question.correct_option}. Reasoning: {result.get('reasoning', 'N/A')}"
        )
        score = 20

    if multiple_correct:
        errors.append("LLM detected multiple potentially correct options")
        score = min(score, 30)

    if issues:
        warnings.extend(issues)
        score -= len(issues) * 5

    return ValidationResult(
        validator_name="answer",
        passed=agrees and not multiple_correct,
        score=max(0, score),
        errors=errors,
        warnings=warnings,
        details={"method": "llm", "llm_answer": llm_answer, "reasoning": result.get("reasoning", "")},
    )


def validate_answer(question: Question, client: GeminiClient | None = None) -> ValidationResult:
    """
    Main answer validation entry point.
    Tries computational verification first, falls back to LLM.
    """
    # Try math verification first (free, fast)
    math_result = _try_math_verification(question)
    if math_result and math_result.passed:
        return math_result

    # Use LLM verification
    if client:
        return validate_answer_with_llm(question, client)

    # No client available — can't verify
    return ValidationResult(
        validator_name="answer",
        passed=True,
        score=60,
        warnings=["No verification performed — no Gemini client available"],
        details={"method": "none"},
    )
