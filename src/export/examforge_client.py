"""
ExamForge API Ingestion Client.
Formats and transmits 100-question batches to ExamForge mock test platform.
"""
from __future__ import annotations
import logging
import time
from typing import Any
import httpx

from config.settings import (
    EXAMFORGE_API_URL,
    EXAMFORGE_API_KEY,
)

logger = logging.getLogger(__name__)


class ExamForgeClient:
    """Handles communication with the ExamForge ai-ingest webhook endpoint."""

    def __init__(self, endpoint_url: str = "", api_key: str = ""):
        self.endpoint_url = endpoint_url or EXAMFORGE_API_URL
        self.api_key = api_key or EXAMFORGE_API_KEY

    def format_question_for_ingest(self, q: dict) -> dict:
        """Format a single question to the exact ExamForge schema."""
        # Normalize correct_answer to letter 'A', 'B', 'C', or 'D'
        ca = str(q.get("correct_answer") or q.get("correctAnswer") or "A").strip().upper()
        if ca in ["0", "1", "2", "3"]:
            ca = ["A", "B", "C", "D"][int(ca)]
        elif ca not in ["A", "B", "C", "D"]:
            ca = "A"

        # Normalize difficulty: 'Easy', 'Medium', or 'Hard'
        diff = str(q.get("difficulty", "Medium")).strip().capitalize()
        if diff not in ["Easy", "Medium", "Hard"]:
            diff = "Medium"

        # Normalize tags (comma-separated string or list)
        tags = q.get("tags")
        if isinstance(tags, list):
            tags = ", ".join(str(t).strip() for t in tags if t)
        elif not tags:
            subj = q.get("subject_name", "") or q.get("subjectName", "")
            top = q.get("topic_name", "") or q.get("topicName", "")
            tags_list = [t.strip().lower() for t in [subj, top] if t]
            tags = ", ".join(tags_list) if tags_list else "general"

        return {
            "questionText": q.get("question_text") or q.get("questionText", ""),
            "optionA": q.get("option_a") or q.get("optionA", ""),
            "optionB": q.get("option_b") or q.get("optionB", ""),
            "optionC": q.get("option_c") or q.get("optionC", ""),
            "optionD": q.get("option_d") or q.get("optionD", ""),
            "correctAnswer": ca,
            "explanation": q.get("explanation", ""),
            "difficulty": diff,
            "tags": tags,
        }

    def dispatch_batch(
        self,
        questions: list[dict],
        subject_name: str,
        topic_name: str = "General",
        exam_code: str = "RRB",
        endpoint_url: str = "",
        api_key: str = "",
    ) -> tuple[bool, int, Any]:
        """
        Send a batch of questions to ExamForge.
        Returns: (success: bool, status_code: int, response_data: Any)
        """
        target_url = endpoint_url or self.endpoint_url
        target_key = api_key or self.api_key

        formatted_questions = [self.format_question_for_ingest(q) for q in questions]

        payload = {
            "examCode": exam_code or "RRB",
            "subjectName": subject_name,
            "topicName": topic_name,
            "questions": formatted_questions,
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": target_key,
        }

        logger.info(f"Sending batch of {len(formatted_questions)} questions to {target_url}...")

        # Retry with exponential backoff up to 3 attempts
        last_error = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(target_url, json=payload, headers=headers)
                    status = resp.status_code

                    try:
                        resp_json = resp.json()
                    except Exception:
                        resp_json = {"raw_text": resp.text}

                    if status in [200, 201]:
                        logger.info(f"Successfully ingested batch into ExamForge! Status: {status}")
                        return True, status, resp_json
                    elif status >= 500:
                        logger.warning(f"ExamForge server error ({status}) on attempt {attempt}: {resp.text[:150]}")
                        time.sleep(attempt * 2)
                    else:
                        logger.error(f"ExamForge rejected payload with client error ({status}): {resp.text[:200]}")
                        return False, status, resp_json

            except Exception as e:
                last_error = e
                logger.warning(f"Connection error to {target_url} on attempt {attempt}: {e}")
                time.sleep(attempt * 2)

        return False, 0, {"error": f"Failed to connect after 3 attempts: {last_error}"}

    def test_connection(self, endpoint_url: str = "", api_key: str = "", exam_code: str = "RRB") -> tuple[bool, str]:
        """
        Send a lightweight dummy question test payload to verify endpoint connectivity.
        """
        dummy_q = [{
            "questionText": "What is the speed of light in a vacuum?",
            "optionA": "3 x 10^8 m/s",
            "optionB": "3 x 10^6 m/s",
            "optionC": "3 x 10^5 km/s",
            "optionD": "Both A and C",
            "correctAnswer": "D",
            "explanation": "3 x 10^8 m/s is equivalent to 3 x 10^5 km/s.",
            "difficulty": "Easy",
            "tags": "physics, optics, rrb",
        }]

        success, status, data = self.dispatch_batch(
            dummy_q,
            subject_name="General Science",
            topic_name="Physics",
            exam_code=exam_code or "RRB",
            endpoint_url=endpoint_url,
            api_key=api_key,
        )

        if success:
            return True, f"Connection successful! Server responded with HTTP {status}."
        else:
            return False, f"Connection failed (HTTP {status}): {data}"
