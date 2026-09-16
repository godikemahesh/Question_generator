"""
Knowledge Base — Context Retriever.
Retrieves relevant syllabus chunks for a given topic/concept using keyword matching.
(No vector DB — uses TF-IDF similarity for now.)
"""
from __future__ import annotations
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.knowledge.chunker import TextChunk, chunk_all_syllabi

logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """Retrieves relevant syllabus context for question generation."""

    def __init__(self):
        self._chunks: dict[str, list[TextChunk]] = {}
        self._vectorizers: dict[str, TfidfVectorizer] = {}
        self._tfidf_matrices: dict[str, object] = {}
        self._initialized = False

    def initialize(self):
        """Load and index all syllabus chunks."""
        if self._initialized:
            return

        self._chunks = chunk_all_syllabi()

        for subject, chunks in self._chunks.items():
            if not chunks:
                continue
            texts = [c.text for c in chunks]
            vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
            tfidf_matrix = vectorizer.fit_transform(texts)
            self._vectorizers[subject] = vectorizer
            self._tfidf_matrices[subject] = tfidf_matrix

        self._initialized = True
        total = sum(len(c) for c in self._chunks.values())
        logger.info(f"Knowledge base initialized: {total} chunks across {len(self._chunks)} subjects")

    def retrieve(self, subject: str, query: str, top_k: int = 3) -> str:
        """
        Retrieve the most relevant syllabus context for a query.
        
        Args:
            subject: Subject name to search within
            query: Search query (topic name, concept, etc.)
            top_k: Number of top chunks to return
            
        Returns:
            Combined text of the most relevant chunks
        """
        self.initialize()

        # Find the subject (case-insensitive)
        matched_subject = None
        for s in self._chunks:
            if s.lower() == subject.lower():
                matched_subject = s
                break

        if not matched_subject or matched_subject not in self._vectorizers:
            logger.warning(f"No knowledge base for subject: {subject}")
            return ""

        chunks = self._chunks[matched_subject]
        vectorizer = self._vectorizers[matched_subject]
        tfidf_matrix = self._tfidf_matrices[matched_subject]

        # Transform the query
        query_vec = vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()

        # Get top-k indices
        top_indices = similarities.argsort()[-top_k:][::-1]

        # Combine the top chunks
        relevant_texts = []
        for idx in top_indices:
            if similarities[idx] > 0.05:  # Minimum relevance threshold
                relevant_texts.append(chunks[idx].text)

        combined = "\n\n---\n\n".join(relevant_texts)
        logger.debug(f"Retrieved {len(relevant_texts)} chunks for '{query}' in {subject}")
        return combined

    def get_all_text_for_subject(self, subject: str) -> str:
        """Get all syllabus text for a subject (for small syllabi)."""
        self.initialize()

        for s, chunks in self._chunks.items():
            if s.lower() == subject.lower():
                return "\n\n".join(c.text for c in chunks)
        return ""
