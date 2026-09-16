"""
Question Template Engine.
Provides reusable question patterns for controlled variation.
"""
from __future__ import annotations
import json
import logging
import random
from pathlib import Path

from config.settings import TEMPLATES_DIR

logger = logging.getLogger(__name__)


# Built-in generic templates that work across subjects
BUILTIN_TEMPLATES = {
    "definition": {
        "template_id": "T_DEFINITION",
        "pattern": "What is the definition of {concept}?",
        "description": "Test knowledge of a definition",
        "question_types": ["conceptual"],
    },
    "identify": {
        "template_id": "T_IDENTIFY",
        "pattern": "Which of the following best describes {concept}?",
        "description": "Identify the correct description",
        "question_types": ["conceptual"],
    },
    "example": {
        "template_id": "T_EXAMPLE",
        "pattern": "Which of the following is an example of {concept}?",
        "description": "Identify a correct example",
        "question_types": ["conceptual", "application"],
    },
    "not_example": {
        "template_id": "T_NOT_EXAMPLE",
        "pattern": "Which of the following is NOT an example of {concept}?",
        "description": "Identify the incorrect example",
        "question_types": ["conceptual", "analytical"],
    },
    "comparison": {
        "template_id": "T_COMPARISON",
        "pattern": "What is the difference between {concept_a} and {concept_b}?",
        "description": "Compare two related concepts",
        "question_types": ["conceptual", "analytical"],
    },
    "application": {
        "template_id": "T_APPLICATION",
        "pattern": "In a real-world scenario involving {context}, how would {concept} apply?",
        "description": "Apply concept to a real scenario",
        "question_types": ["application", "scenario_based"],
    },
    "calculation": {
        "template_id": "T_CALCULATION",
        "pattern": "Calculate {target} given {given_values}.",
        "description": "Mathematical calculation question",
        "question_types": ["problem_solving"],
    },
    "cause_effect": {
        "template_id": "T_CAUSE_EFFECT",
        "pattern": "What is the result of {action} on {subject}?",
        "description": "Understand cause and effect",
        "question_types": ["application", "analytical"],
    },
    "sequence": {
        "template_id": "T_SEQUENCE",
        "pattern": "Arrange the following steps of {process} in correct order.",
        "description": "Sequence ordering question",
        "question_types": ["conceptual", "application"],
    },
    "true_false_identify": {
        "template_id": "T_TRUE_FALSE",
        "pattern": "Which of the following statements about {concept} is correct?",
        "description": "Identify the true statement",
        "question_types": ["conceptual"],
    },
    "assertion_reason": {
        "template_id": "T_ASSERTION_REASON",
        "pattern": "Assertion (A): [Proposition about {concept}]\nReason (R): [Scientific/causal reasoning]\nChoose the correct option:",
        "description": "Assertion-Reason format evaluating logical cause-and-effect in DSC exams",
        "question_types": ["analytical", "conceptual"],
    },
    "statement_evaluation": {
        "template_id": "T_STATEMENT_EVALUATION",
        "pattern": "Consider the following two statements regarding {concept}:\nStatement I: [Proposition 1]\nStatement II: [Proposition 2]\nWhich of the following is correct?",
        "description": "Statement I and Statement II comparative truth/falsity analysis",
        "question_types": ["analytical", "conceptual"],
    },
    "multi_statement_selection": {
        "template_id": "T_MULTI_STATEMENT_SELECTION",
        "pattern": "Consider the following statements regarding {concept}:\n1. [Statement 1]\n2. [Statement 2]\n3. [Statement 3]\nWhich of the statements given above is/are correct?",
        "description": "Multi-statement selection question (e.g., '1 and 2 only', '1, 2 and 3')",
        "question_types": ["analytical", "application"],
    },
    "match_columns": {
        "template_id": "T_MATCH_COLUMNS",
        "pattern": "Match List I ({concept} characteristics/terms) with List II (Functions/Examples):\nList I: A. ... B. ... C. ... D. ...\nList II: 1. ... 2. ... 3. ... 4. ...\nSelect the correct matching code:",
        "description": "Match List I with List II testing interconnected knowledge",
        "question_types": ["conceptual", "application"],
    },
    "multi_concept_synthesis": {
        "template_id": "T_MULTI_CONCEPT_SYNTHESIS",
        "pattern": "How does {concept} dynamically interact with or regulate a related biological/physical phenomenon under specific conditions?",
        "description": "Multi-concept synthesis linking two related principles in the syllabus",
        "question_types": ["analytical", "application", "problem_solving"],
    },
}


class TemplateEngine:
    """Manages question templates for controlled variation."""

    def __init__(self):
        self._templates: dict[str, dict] = dict(BUILTIN_TEMPLATES)
        self._custom_templates: dict[str, list[dict]] = {}  # subject → templates

    def load_custom_templates(self):
        """Load custom templates from the templates/ directory."""
        if not TEMPLATES_DIR.exists():
            return

        for path in TEMPLATES_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                subject = path.stem.replace("_templates", "").replace("_", " ").title()

                if isinstance(data, list):
                    self._custom_templates[subject] = data
                elif isinstance(data, dict) and "templates" in data:
                    self._custom_templates[subject] = data["templates"]

                logger.info(f"Loaded {len(self._custom_templates.get(subject, []))} custom templates for {subject}")
            except Exception as e:
                logger.error(f"Failed to load templates from {path}: {e}")

    def get_template_for_job(self, subject: str, question_type: str) -> dict | None:
        """
        Get a suitable template for a generation job.
        Prefers custom templates, falls back to built-in.
        """
        # Check custom templates first
        if subject in self._custom_templates:
            matching = [
                t for t in self._custom_templates[subject]
                if question_type in t.get("question_types", [])
            ]
            if matching:
                return random.choice(matching)

        # Fall back to built-in templates
        matching = [
            t for t in self._templates.values()
            if question_type in t.get("question_types", [])
        ]
        if matching:
            return random.choice(matching)

        return None

    def get_template_instruction(self, template: dict | None) -> str:
        """Convert a template to an instruction string for the prompt."""
        if not template:
            return ""

        parts = []
        if "pattern" in template:
            parts.append(f"Follow this question pattern: {template['pattern']}")
        if "description" in template:
            parts.append(f"Pattern description: {template['description']}")
        if "template_id" in template:
            parts.append(f"Template ID: {template['template_id']}")

        return "\n".join(parts)

    @property
    def all_template_ids(self) -> list[str]:
        ids = [t["template_id"] for t in self._templates.values()]
        for templates in self._custom_templates.values():
            ids.extend(t.get("template_id", "") for t in templates)
        return ids
