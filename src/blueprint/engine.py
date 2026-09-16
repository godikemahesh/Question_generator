"""
Blueprint Engine.
Converts syllabus structure + distribution rules into concrete GenerationJob lists.
"""
from __future__ import annotations
import json
import logging
import math
from pathlib import Path

from config.settings import (
    BLUEPRINTS_DIR,
    DEFAULT_DIFFICULTY_DISTRIBUTION,
    DEFAULT_QUESTION_TYPE_DISTRIBUTION,
)
from src.syllabus.models import Subject
from src.question_bank.models import GenerationJob, TestBlueprint

logger = logging.getLogger(__name__)


def create_auto_blueprint(
    subject: Subject,
    total_questions: int = 120,
    difficulty_dist: dict[str, float] | None = None,
    qtype_dist: dict[str, float] | None = None,
) -> TestBlueprint:
    """
    Automatically create a blueprint from a parsed syllabus.
    Distributes questions proportionally across topics based on concept count.
    """
    difficulty_dist = difficulty_dist or DEFAULT_DIFFICULTY_DISTRIBUTION
    qtype_dist = qtype_dist or DEFAULT_QUESTION_TYPE_DISTRIBUTION

    # Calculate topic weights based on concept count
    topic_concepts = {}
    total_concepts = 0
    for topic in subject.topics:
        count = len(topic.all_concepts)
        topic_concepts[topic.name] = max(count, 1)  # At least 1
        total_concepts += max(count, 1)

    # Distribute questions proportionally
    topic_distribution = {}
    assigned = 0
    topics_list = list(topic_concepts.keys())

    for i, topic_name in enumerate(topics_list):
        if i == len(topics_list) - 1:
            # Last topic gets the remainder
            topic_distribution[topic_name] = total_questions - assigned
        else:
            count = round(total_questions * topic_concepts[topic_name] / total_concepts)
            count = max(count, 2)  # At least 2 questions per topic
            topic_distribution[topic_name] = count
            assigned += count

    # Difficulty distribution (absolute counts)
    difficulty_counts = {}
    d_assigned = 0
    diff_items = list(difficulty_dist.items())
    for i, (level, ratio) in enumerate(diff_items):
        if i == len(diff_items) - 1:
            difficulty_counts[level] = total_questions - d_assigned
        else:
            count = round(total_questions * ratio)
            difficulty_counts[level] = count
            d_assigned += count

    # Question type distribution (absolute counts)
    qtype_counts = {}
    q_assigned = 0
    qtype_items = list(qtype_dist.items())
    for i, (qtype, ratio) in enumerate(qtype_items):
        if i == len(qtype_items) - 1:
            qtype_counts[qtype] = total_questions - q_assigned
        else:
            count = round(total_questions * ratio)
            qtype_counts[qtype] = count
            q_assigned += count

    blueprint = TestBlueprint(
        subject=subject.name,
        total_questions=total_questions,
        topic_distribution=topic_distribution,
        difficulty_distribution=difficulty_counts,
        question_type_distribution=qtype_counts,
    )

    logger.info(f"Auto-blueprint for {subject.name}: {total_questions} questions across {len(topic_distribution)} topics")
    return blueprint


def blueprint_to_generation_jobs(
    blueprint: TestBlueprint,
    subject: Subject,
    batch_size: int = 8,
    overgenerate_factor: float = 1.5,
) -> list[GenerationJob]:
    """
    Convert a blueprint into a list of concrete GenerationJobs.
    Over-generates by the specified factor to account for rejections.
    
    Args:
        blueprint: The test blueprint with distributions
        subject: Parsed subject with topics/concepts
        batch_size: Questions per generation call
        overgenerate_factor: Multiply target by this (1.5 = generate 50% extra)
    """
    jobs = []
    difficulties = list(blueprint.difficulty_distribution.keys())
    qtypes = list(blueprint.question_type_distribution.keys())

    diff_idx = 0
    qtype_idx = 0

    for topic_name, target_count in blueprint.topic_distribution.items():
        # Find matching topic in subject
        topic = None
        for t in subject.topics:
            if t.name.lower() == topic_name.lower():
                topic = t
                break

        if not topic:
            logger.warning(f"Topic '{topic_name}' not found in subject structure, using topic name only")

        # Calculate actual generation count (with overgeneration)
        gen_count = math.ceil(target_count * overgenerate_factor)

        # Get subtopics/concepts for this topic
        subtopics = topic.subtopics if topic else []

        # Create jobs in batches
        remaining = gen_count
        while remaining > 0:
            batch = min(remaining, batch_size)

            # Cycle through difficulties and question types
            difficulty = difficulties[diff_idx % len(difficulties)]
            diff_idx += 1
            qtype = qtypes[qtype_idx % len(qtypes)]
            qtype_idx += 1

            # Pick a subtopic if available
            subtopic_name = ""
            concept_id = ""
            if subtopics:
                st = subtopics[(diff_idx + qtype_idx) % len(subtopics)]
                subtopic_name = st.name
                if st.concepts:
                    concept = st.concepts[(diff_idx + qtype_idx) % len(st.concepts)]
                    concept_id = concept.concept_id

            job = GenerationJob(
                subject=blueprint.subject,
                topic=topic_name,
                subtopic=subtopic_name,
                concept_id=concept_id,
                num_questions=batch,
                difficulty=difficulty,
                question_type=qtype,
            )
            jobs.append(job)
            remaining -= batch

    logger.info(f"Created {len(jobs)} generation jobs for {blueprint.subject} ({sum(j.num_questions for j in jobs)} total questions)")
    return jobs


def save_blueprint(blueprint: TestBlueprint):
    """Save a blueprint as JSON."""
    path = BLUEPRINTS_DIR / f"{blueprint.subject.lower().replace(' ', '_')}_blueprint.json"
    path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
    logger.info(f"Saved blueprint: {path}")


def load_blueprint(subject: str) -> TestBlueprint | None:
    """Load a saved blueprint for a subject."""
    path = BLUEPRINTS_DIR / f"{subject.lower().replace(' ', '_')}_blueprint.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TestBlueprint(**data)
    except Exception as e:
        logger.error(f"Failed to load blueprint {path}: {e}")
        return None
