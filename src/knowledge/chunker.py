"""
Knowledge Base — Text Chunker.
Splits syllabus text into meaningful chunks for RAG-based generation.
"""
from __future__ import annotations
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import SYLLABUS_DIR

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    """A chunk of syllabus text with metadata."""
    chunk_id: str = ""
    subject: str = ""
    topic: str = ""
    subtopic: str = ""
    text: str = ""
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.chunk_id and self.text:
            self.chunk_id = hashlib.md5(self.text.encode()).hexdigest()[:12]


def chunk_syllabus_text(text: str, subject: str, chunk_size: int = 1000, overlap: int = 200) -> list[TextChunk]:
    """
    Split syllabus text into overlapping chunks.
    Tries to split on paragraph/section boundaries first.
    """
    if not text.strip():
        return []

    # Split by double newlines (paragraphs) or section headers
    sections = re.split(r'\n\s*\n|\n(?=[A-Z][A-Za-z\s]+:)', text)
    sections = [s.strip() for s in sections if s.strip()]

    chunks = []
    current_chunk = ""
    current_topic = ""

    for section in sections:
        # Try to detect topic headers
        header_match = re.match(r'^([A-Z][A-Za-z\s\-&]+)[\s:]*$', section.split('\n')[0])
        if header_match:
            current_topic = header_match.group(1).strip()

        if len(current_chunk) + len(section) <= chunk_size:
            current_chunk += "\n" + section if current_chunk else section
        else:
            # Save current chunk
            if current_chunk:
                chunks.append(TextChunk(
                    subject=subject,
                    topic=current_topic,
                    text=current_chunk,
                ))
            current_chunk = section

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(TextChunk(
            subject=subject,
            topic=current_topic,
            text=current_chunk,
        ))

    # If chunks are still too large, do a sliding window split
    final_chunks = []
    for chunk in chunks:
        if len(chunk.text) > chunk_size * 2:
            # Split large chunks with sliding window
            words = chunk.text.split()
            window_words = chunk_size // 5  # rough word count
            overlap_words = overlap // 5
            i = 0
            while i < len(words):
                end = min(i + window_words, len(words))
                sub_text = " ".join(words[i:end])
                final_chunks.append(TextChunk(
                    subject=chunk.subject,
                    topic=chunk.topic,
                    text=sub_text,
                ))
                i += window_words - overlap_words
        else:
            final_chunks.append(chunk)

    logger.info(f"Chunked {subject}: {len(final_chunks)} chunks from {len(text)} chars")
    return final_chunks


def chunk_all_syllabi() -> dict[str, list[TextChunk]]:
    """Load and chunk all syllabus text files. Returns dict keyed by subject name."""
    all_chunks: dict[str, list[TextChunk]] = {}

    if not SYLLABUS_DIR.exists():
        logger.warning(f"Syllabus directory not found: {SYLLABUS_DIR}")
        return all_chunks

    for filepath in sorted(SYLLABUS_DIR.glob("*.txt")):
        subject = filepath.stem.replace("_", " ").title()
        try:
            text = filepath.read_text(encoding="utf-8")
            chunks = chunk_syllabus_text(text, subject)
            all_chunks[subject] = chunks
        except Exception as e:
            logger.error(f"Failed to chunk {filepath}: {e}")

    return all_chunks
