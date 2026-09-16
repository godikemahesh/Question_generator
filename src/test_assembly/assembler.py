"""
Test Assembly Engine.
Assembles balanced tests from approved questions with answer-position balancing.
"""
from __future__ import annotations
import logging
import random
from collections import Counter
from datetime import datetime

from config.settings import MAX_SAME_CONCEPT_PER_TEST, ANSWER_BALANCE_TOLERANCE
from src.question_bank.models import Question, TestBlueprint, AssembledTest, QuestionStatus
from src.question_bank.store import QuestionStore

logger = logging.getLogger(__name__)


class TestAssembler:
    """Assembles tests from the question bank with balancing constraints."""

    def __init__(self, store: QuestionStore):
        self.store = store

    def assemble_test(
        self,
        blueprint: TestBlueprint,
        reuse_days: int = 60,
    ) -> AssembledTest:
        """
        Assemble a test from approved questions following the blueprint.
        
        Steps:
        1. Load candidate pool (approved + used questions)
        2. Filter by reuse policy
        3. Apply topic quotas
        4. Apply difficulty quotas
        5. Apply question-type quotas
        6. Balance answer positions
        7. Shuffle and validate
        """
        logger.info(f"Assembling test for {blueprint.subject}: {blueprint.total_questions} questions")

        # 1. Load candidate pool
        approved = self.store.load_questions_by_status(blueprint.subject, QuestionStatus.APPROVED.value)
        used = self.store.load_questions_by_status(blueprint.subject, QuestionStatus.USED.value)

        # Filter used questions by reuse policy
        now = datetime.now()
        reusable_used = []
        for q in used:
            if q.last_used_at:
                try:
                    last_used = datetime.fromisoformat(q.last_used_at)
                    days_since = (now - last_used).days
                    if days_since >= reuse_days:
                        reusable_used.append(q)
                except (ValueError, TypeError):
                    pass

        candidates = approved + reusable_used
        logger.info(f"Candidate pool: {len(approved)} approved + {len(reusable_used)} reusable = {len(candidates)}")

        if len(candidates) < blueprint.total_questions:
            logger.warning(
                f"Not enough questions! Need {blueprint.total_questions}, "
                f"have {len(candidates)}. Will use what's available."
            )

        # 2. Select questions by topic quota
        selected = self._select_by_topic(candidates, blueprint.topic_distribution)

        # 3. Ensure difficulty balance (swap if needed)
        selected = self._balance_difficulty(selected, candidates, blueprint.difficulty_distribution)

        # 4. Limit to target count
        if len(selected) > blueprint.total_questions:
            selected = selected[:blueprint.total_questions]

        # 5. Balance answer positions
        selected = self._balance_answer_positions(selected)

        # 6. Shuffle (but avoid answer-position streaks)
        selected = self._shuffle_avoid_streaks(selected)

        # Build the test
        test = AssembledTest(
            subject=blueprint.subject,
            test_date=datetime.now().strftime("%Y-%m-%d"),
            total_questions=len(selected),
            question_ids=[q.question_id for q in selected],
            questions=selected,
        )

        logger.info(f"Assembled test: {len(selected)} questions")
        return test

    def _select_by_topic(
        self, candidates: list[Question], topic_dist: dict[str, int]
    ) -> list[Question]:
        """Select questions matching topic quotas."""
        selected = []
        remaining = list(candidates)
        random.shuffle(remaining)

        for topic_name, quota in topic_dist.items():
            topic_matches = [
                q for q in remaining
                if q.topic.lower() == topic_name.lower()
            ]

            # Also try partial matching
            if not topic_matches:
                topic_matches = [
                    q for q in remaining
                    if topic_name.lower() in q.topic.lower() or q.topic.lower() in topic_name.lower()
                ]

            picked = topic_matches[:quota]
            selected.extend(picked)

            # Remove picked from remaining
            picked_ids = {q.question_id for q in picked}
            remaining = [q for q in remaining if q.question_id not in picked_ids]

        # If we haven't filled the total, add from remaining
        if remaining and len(selected) < sum(topic_dist.values()):
            deficit = sum(topic_dist.values()) - len(selected)
            selected.extend(remaining[:deficit])

        return selected

    def _balance_difficulty(
        self,
        selected: list[Question],
        candidates: list[Question],
        difficulty_dist: dict[str, int],
    ) -> list[Question]:
        """Try to match the difficulty distribution by swapping questions."""
        current_diff = Counter(q.difficulty.lower() for q in selected)
        selected_ids = {q.question_id for q in selected}

        for difficulty, target in difficulty_dist.items():
            current = current_diff.get(difficulty, 0)
            if current < target:
                # Need more of this difficulty
                deficit = target - current
                available = [
                    q for q in candidates
                    if q.question_id not in selected_ids
                    and q.difficulty.lower() == difficulty
                ]
                add_count = min(deficit, len(available))
                if add_count > 0:
                    random.shuffle(available)
                    selected.extend(available[:add_count])
                    for q in available[:add_count]:
                        selected_ids.add(q.question_id)

        return selected

    def _balance_answer_positions(self, questions: list[Question]) -> list[Question]:
        """
        Redistribute correct answer positions to achieve ~25% each.
        Swaps option positions while preserving correctness.
        """
        n = len(questions)
        target_per_option = n / 4
        tolerance = n * ANSWER_BALANCE_TOLERANCE

        # Count current distribution
        position_counts = Counter(q.correct_option.upper() for q in questions)

        # Identify over/under-represented positions
        for q in questions:
            current_pos = q.correct_option.upper()
            if position_counts.get(current_pos, 0) > target_per_option + tolerance:
                # Find an under-represented position to swap to
                for target_pos in ["A", "B", "C", "D"]:
                    if position_counts.get(target_pos, 0) < target_per_option - tolerance:
                        # Swap the options
                        self._swap_option_position(q, current_pos, target_pos)
                        position_counts[current_pos] -= 1
                        position_counts[target_pos] = position_counts.get(target_pos, 0) + 1
                        break

        return questions

    def _swap_option_position(self, question: Question, from_pos: str, to_pos: str):
        """Swap the correct answer to a different option position."""
        options = {
            "A": question.option_a,
            "B": question.option_b,
            "C": question.option_c,
            "D": question.option_d,
        }

        # Swap the content of the two positions
        options[from_pos], options[to_pos] = options[to_pos], options[from_pos]

        question.option_a = options["A"]
        question.option_b = options["B"]
        question.option_c = options["C"]
        question.option_d = options["D"]
        question.correct_option = to_pos
        question.set_correct_answer_text()

    def _shuffle_avoid_streaks(self, questions: list[Question], max_streak: int = 3) -> list[Question]:
        """Shuffle questions while avoiding long streaks of same answer position."""
        random.shuffle(questions)

        # Check for streaks and fix them
        for attempt in range(10):  # Max 10 reshuffling attempts
            has_streak = False
            for i in range(len(questions) - max_streak):
                positions = [questions[j].correct_option.upper() for j in range(i, i + max_streak + 1)]
                if len(set(positions)) == 1:
                    has_streak = True
                    # Swap with a random position
                    swap_idx = random.randint(0, len(questions) - 1)
                    if swap_idx != i + max_streak:
                        questions[i + max_streak], questions[swap_idx] = questions[swap_idx], questions[i + max_streak]

            if not has_streak:
                break

        return questions
