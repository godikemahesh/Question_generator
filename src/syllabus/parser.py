"""
Syllabus Parser.
Reads .txt files from the syllabus/ folder and uses Gemini to structure them
into a hierarchical JSON: Subject → Topic → Subtopic → Concept.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path

from config.settings import SYLLABUS_DIR, PARSED_SYLLABUS_DIR
from src.syllabus.models import Subject, Topic, Subtopic, Concept, ParsedSyllabus
from src.generator.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


PARSE_SYLLABUS_PROMPT = """You are an expert education curriculum analyst. 

I will give you the raw text content of a syllabus for the subject: "{subject_name}".
This is for the DSC (District Selection Committee) exam.

Your task: Parse this syllabus text into a structured hierarchy.

Return a JSON object with this EXACT structure:
{{
  "subject_id": "<lowercase_subject_name>",
  "name": "{subject_name}",
  "description": "Brief description of this subject in the DSC exam",
  "topics": [
    {{
      "topic_id": "<subject_prefix>_<topic_short>",
      "name": "Topic Name",
      "description": "Brief description",
      "subtopics": [
        {{
          "subtopic_id": "<topic_id>_<subtopic_short>",
          "name": "Subtopic Name", 
          "description": "Brief description",
          "concepts": [
            {{
              "concept_id": "<subtopic_id>_001",
              "name": "Concept Name",
              "description": "What this concept covers",
              "learning_objective": "What a student should know",
              "keywords": ["keyword1", "keyword2"]
            }}
          ]
        }}
      ]
    }}
  ]
}}

Rules:
- Extract ALL topics, subtopics, and concepts mentioned in the syllabus
- Use short, clean IDs (uppercase, underscores, no spaces)
- Every concept should be a single testable unit of knowledge
- If the syllabus is vague, break it into logical concepts based on standard educational structure
- Include 3-8 concepts per subtopic typically
- Include 2-5 subtopics per topic typically
- Be thorough — don't skip any content from the syllabus

Here is the syllabus text:

---
{syllabus_text}
---

Return ONLY the JSON. No markdown, no explanation.
"""


def discover_syllabus_files() -> list[Path]:
    """Find all .txt files in the syllabus/ directory."""
    if not SYLLABUS_DIR.exists():
        logger.warning(f"Syllabus directory not found: {SYLLABUS_DIR}")
        return []
    
    files = sorted(SYLLABUS_DIR.glob("*.txt"))
    logger.info(f"Found {len(files)} syllabus files: {[f.name for f in files]}")
    return files


def extract_subject_name(filepath: Path) -> str:
    """Extract subject name from filename. e.g., 'Mathematics.txt' → 'Mathematics'"""
    return filepath.stem.replace("_", " ").title()


def parse_single_subject(filepath: Path, client: GeminiClient) -> Subject | None:
    """Parse a single syllabus text file into a structured Subject."""
    subject_name = extract_subject_name(filepath)
    logger.info(f"Parsing syllabus for: {subject_name}")

    # Read the text file
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
        return None

    if not text.strip():
        logger.warning(f"Empty syllabus file: {filepath}")
        return None

    # Truncate very long files (keep within Gemini context)
    max_chars = 30000
    if len(text) > max_chars:
        logger.warning(f"Syllabus text truncated from {len(text)} to {max_chars} chars")
        text = text[:max_chars]

    # Ask Gemini to structure it
    prompt = PARSE_SYLLABUS_PROMPT.format(
        subject_name=subject_name,
        syllabus_text=text,
    )

    result = client.generate_json(prompt, temperature=0.2)

    if not result or not isinstance(result, dict):
        logger.error(f"Failed to parse syllabus for {subject_name}")
        return None

    try:
        # Build the Subject model
        subject = Subject(
            subject_id=result.get("subject_id", subject_name.lower().replace(" ", "_")),
            name=result.get("name", subject_name),
            source_file=str(filepath),
            description=result.get("description", ""),
            topics=_parse_topics(result.get("topics", [])),
        )

        concept_count = len(subject.all_concepts)
        topic_count = len(subject.topics)
        logger.info(
            f"Parsed {subject_name}: {topic_count} topics, {concept_count} concepts"
        )
        return subject

    except Exception as e:
        logger.error(f"Error building Subject model for {subject_name}: {e}")
        return None


def _parse_topics(topics_data: list[dict]) -> list[Topic]:
    """Parse topic dicts into Topic models."""
    topics = []
    for td in topics_data:
        topic = Topic(
            topic_id=td.get("topic_id", ""),
            name=td.get("name", ""),
            description=td.get("description", ""),
            subtopics=_parse_subtopics(td.get("subtopics", [])),
        )
        topics.append(topic)
    return topics


def _parse_subtopics(subtopics_data: list[dict]) -> list[Subtopic]:
    """Parse subtopic dicts into Subtopic models."""
    subtopics = []
    for sd in subtopics_data:
        subtopic = Subtopic(
            subtopic_id=sd.get("subtopic_id", ""),
            name=sd.get("name", ""),
            description=sd.get("description", ""),
            concepts=_parse_concepts(sd.get("concepts", [])),
        )
        subtopics.append(subtopic)
    return subtopics


def _parse_concepts(concepts_data: list[dict]) -> list[Concept]:
    """Parse concept dicts into Concept models."""
    concepts = []
    for cd in concepts_data:
        concept = Concept(
            concept_id=cd.get("concept_id", ""),
            name=cd.get("name", ""),
            description=cd.get("description", ""),
            learning_objective=cd.get("learning_objective", ""),
            keywords=cd.get("keywords", []),
        )
        concepts.append(concept)
    return concepts


def save_parsed_subject(subject: Subject):
    """Save a parsed subject as JSON."""
    output_path = PARSED_SYLLABUS_DIR / f"{subject.subject_id}.json"
    output_path.write_text(
        subject.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info(f"Saved parsed syllabus: {output_path}")


def load_parsed_subject(subject_id: str) -> Subject | None:
    """Load a previously parsed subject from JSON."""
    path = PARSED_SYLLABUS_DIR / f"{subject_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Subject(**data)
    except Exception as e:
        logger.error(f"Failed to load parsed syllabus {path}: {e}")
        return None


def load_all_parsed_subjects() -> list[Subject]:
    """Load all previously parsed subjects."""
    subjects = []
    for path in sorted(PARSED_SYLLABUS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            subjects.append(Subject(**data))
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
    return subjects


def parse_all_syllabi(client: GeminiClient, force: bool = False) -> ParsedSyllabus:
    """
    Parse all syllabus .txt files into structured JSON.
    
    Args:
        client: Gemini API client
        force: If True, re-parse even if parsed JSON already exists
    
    Returns:
        ParsedSyllabus with all subjects
    """
    files = discover_syllabus_files()
    if not files:
        logger.warning("No syllabus files found. Add .txt files to the syllabus/ folder.")
        return ParsedSyllabus()

    subjects = []
    for filepath in files:
        subject_id = filepath.stem.lower().replace(" ", "_")

        # Check if already parsed
        if not force:
            existing = load_parsed_subject(subject_id)
            if existing:
                logger.info(f"Using cached parsed syllabus for: {existing.name}")
                subjects.append(existing)
                continue

        # Parse with Gemini
        subject = parse_single_subject(filepath, client)
        if subject:
            save_parsed_subject(subject)
            subjects.append(subject)
            client.pause_between_batches()

    syllabus = ParsedSyllabus(subjects=subjects)
    logger.info(
        f"Total parsed: {len(subjects)} subjects, "
        f"{sum(len(s.all_concepts) for s in subjects)} concepts"
    )
    return syllabus
