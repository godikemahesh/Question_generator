"""
Validator 5 — Duplicate Detection.
Three-level duplicate detection: exact hash, semantic similarity, concept/pattern.
"""
from __future__ import annotations
import hashlib
import logging
import re
import unicodedata
from typing import Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import DUPLICATE_SEMANTIC_THRESHOLD, DUPLICATE_SEMANTIC_REVIEW_THRESHOLD
from src.question_bank.models import Question, ValidationResult

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """Normalize text for exact duplicate comparison."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text


def compute_hash(question: Question) -> str:
    """Compute SHA-256 hash of normalized question text."""
    normalized = _normalize_text(question.question_text)
    return hashlib.sha256(normalized.encode()).hexdigest()


class DuplicateDetector:
    """Three-level duplicate detection engine."""

    def __init__(self):
        self._hash_index: dict[str, str] = {}  # hash → question_id
        self._questions: list[Question] = []
        self._texts: list[str] = []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._tfidf_matrix = None
        self._concept_counts: dict[str, int] = {}  # concept_id → count

    def build_index(self, existing_questions: list[Question]):
        """Build the duplicate detection index from existing approved questions."""
        self._questions = existing_questions
        self._texts = [q.question_text for q in existing_questions]

        # Level 1: Hash index
        for q in existing_questions:
            h = compute_hash(q)
            self._hash_index[h] = q.question_id

        # Level 2: TF-IDF index for semantic similarity
        if self._texts:
            self._vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
            self._tfidf_matrix = self._vectorizer.fit_transform(self._texts)

        # Level 3: Concept pattern counts
        for q in existing_questions:
            key = f"{q.concept_id}_{q.template_id}_{q.question_type}"
            self._concept_counts[key] = self._concept_counts.get(key, 0) + 1

        logger.info(f"Duplicate index built: {len(existing_questions)} questions indexed")

    def check_duplicate(self, question: Question) -> ValidationResult:
        """
        Run all three levels of duplicate detection.
        Returns ValidationResult with details about any matches found.
        """
        errors = []
        warnings = []
        details = {}
        score = 100.0

        # ── Level 1: Exact duplicate (hash match) ──
        q_hash = compute_hash(question)
        question.normalized_hash = q_hash

        if q_hash in self._hash_index:
            dup_id = self._hash_index[q_hash]
            errors.append(f"Exact duplicate of question {dup_id}")
            details["exact_duplicate"] = dup_id
            return ValidationResult(
                validator_name="duplicate",
                passed=False,
                score=0,
                errors=errors,
                details=details,
            )

        # ── Level 2: Semantic similarity ──
        if self._vectorizer and self._tfidf_matrix is not None and self._texts:
            try:
                query_vec = self._vectorizer.transform([question.question_text])
                similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
                max_sim = float(similarities.max()) if len(similarities) > 0 else 0.0
                max_idx = int(similarities.argmax()) if len(similarities) > 0 else -1

                details["max_semantic_similarity"] = round(max_sim, 4)

                if max_sim >= DUPLICATE_SEMANTIC_THRESHOLD:
                    similar_q = self._questions[max_idx]
                    errors.append(
                        f"Semantic duplicate (similarity={max_sim:.3f}) of: "
                        f"{similar_q.question_text[:80]}..."
                    )
                    details["semantic_duplicate_id"] = similar_q.question_id
                    score = 10
                elif max_sim >= DUPLICATE_SEMANTIC_REVIEW_THRESHOLD:
                    similar_q = self._questions[max_idx]
                    warnings.append(
                        f"Potentially similar (similarity={max_sim:.3f}) to: "
                        f"{similar_q.question_text[:80]}..."
                    )
                    details["similar_question_id"] = similar_q.question_id
                    score -= 20
            except Exception as e:
                logger.warning(f"Semantic similarity check failed: {e}")

        # ── Level 3: Concept/pattern duplication ──
        pattern_key = f"{question.concept_id}_{question.template_id}_{question.question_type}"
        pattern_count = self._concept_counts.get(pattern_key, 0)
        details["pattern_count"] = pattern_count

        if pattern_count >= 10:
            warnings.append(
                f"High pattern repetition: {pattern_count} questions with same "
                f"concept/template/type combination"
            )
            score -= 10
        elif pattern_count >= 5:
            warnings.append(f"Moderate pattern repetition: {pattern_count} similar questions exist")
            score -= 5

        passed = len(errors) == 0
        return ValidationResult(
            validator_name="duplicate",
            passed=passed,
            score=max(0, score),
            errors=errors,
            warnings=warnings,
            details=details,
        )

    def add_to_index(self, question: Question):
        """Add a newly approved question to the index."""
        h = compute_hash(question)
        self._hash_index[h] = question.question_id
        self._questions.append(question)
        self._texts.append(question.question_text)

        # Rebuild TF-IDF (could be optimized for large sets)
        if len(self._texts) > 0:
            self._vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
            self._tfidf_matrix = self._vectorizer.fit_transform(self._texts)

        pattern_key = f"{question.concept_id}_{question.template_id}_{question.question_type}"
        self._concept_counts[pattern_key] = self._concept_counts.get(pattern_key, 0) + 1
