"""
Syllabus data models.
Represents the hierarchical structure: Subject → Topic → Subtopic → Concept
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Concept(BaseModel):
    """Lowest level of the syllabus hierarchy — a single testable concept."""
    concept_id: str = Field(..., description="Unique ID e.g. MATH_ALG_LINEAR_001")
    name: str
    description: str = ""
    learning_objective: str = ""
    difficulty_range: list[str] = Field(default_factory=lambda: ["easy", "medium", "hard"])
    allowed_question_types: list[str] = Field(
        default_factory=lambda: ["conceptual", "application", "problem_solving"]
    )
    keywords: list[str] = Field(default_factory=list)


class Subtopic(BaseModel):
    """A subtopic groups related concepts."""
    subtopic_id: str
    name: str
    description: str = ""
    concepts: list[Concept] = Field(default_factory=list)


class Topic(BaseModel):
    """A topic is a major division within a subject."""
    topic_id: str
    name: str
    description: str = ""
    subtopics: list[Subtopic] = Field(default_factory=list)

    @property
    def all_concepts(self) -> list[Concept]:
        """Flatten all concepts across subtopics."""
        concepts = []
        for st in self.subtopics:
            concepts.extend(st.concepts)
        return concepts


class Subject(BaseModel):
    """A subject is the top-level division (e.g., Mathematics, Science)."""
    subject_id: str
    name: str
    source_file: str = ""
    description: str = ""
    topics: list[Topic] = Field(default_factory=list)

    @property
    def all_concepts(self) -> list[Concept]:
        """Flatten all concepts across all topics."""
        concepts = []
        for t in self.topics:
            concepts.extend(t.all_concepts)
        return concepts

    @property
    def topic_names(self) -> list[str]:
        return [t.name for t in self.topics]


class ParsedSyllabus(BaseModel):
    """The complete parsed syllabus for an exam."""
    exam_name: str = "DSC"
    subjects: list[Subject] = Field(default_factory=list)

    def get_subject(self, name: str) -> Optional[Subject]:
        """Find a subject by name (case-insensitive)."""
        for s in self.subjects:
            if s.name.lower() == name.lower():
                return s
        return None

    @property
    def subject_names(self) -> list[str]:
        return [s.name for s in self.subjects]
