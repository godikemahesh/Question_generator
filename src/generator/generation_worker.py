"""
Background Balanced Generation Worker.
Runs an asynchronous round-robin fair loop over active subjects,
validates questions, prevents duplicates, and auto-dispatches batches of 100 to ExamForge.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.database.supabase_client import StorageManager
from src.generator.llm_manager import MultiProviderLLM
from src.export.examforge_client import ExamForgeClient
from src.services.web_search_manager import WebSearchManager

logger = logging.getLogger(__name__)


def compute_normalized_hash(question_text: str) -> str:
    """Compute SHA-256 hash of normalized text for zero duplicate questions."""
    text = unicodedata.normalize("NFKD", question_text).lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return hashlib.sha256(text.encode()).hexdigest()


class GenerationWorker:
    """Orchestrates balanced background generation across toggled subjects."""

    def __init__(self, storage: StorageManager, llm: MultiProviderLLM, examforge: ExamForgeClient):
        self.storage = storage
        self.llm = llm
        self.examforge = examforge
        self.search_manager = WebSearchManager()
        try:
            self.search_manager.reload_config(self.storage.get_config())
        except Exception:
            pass

        self.is_running = False
        self.is_paused = False
        self._task: Optional[asyncio.Task] = None

        # Live status tracking for Admin UI
        self.current_subject: str = ""
        self.current_topic: str = ""
        self.last_action: str = "Idle"
        self.activity_logs: list[dict] = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def log_event(self, message: str, level: str = "info"):
        """Log event to memory for live UI streaming and terminal stdout."""
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }
        self.activity_logs.append(entry)
        if len(self.activity_logs) > 60:
            self.activity_logs.pop(0)
        logger.info(message)
        print(f"[{entry['timestamp']}] [WORKER-{level.upper()}] {message}", flush=True)

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start the background generation worker."""
        if not self.is_running:
            self.is_running = True
            self.is_paused = False
            self.log_event("Generation worker started.", "success")
            target_loop = loop or self.loop
            if target_loop and target_loop.is_running():
                self._task = target_loop.create_task(self._run_loop())
            else:
                try:
                    running_loop = asyncio.get_running_loop()
                    self._task = running_loop.create_task(self._run_loop())
                except RuntimeError:
                    try:
                        main_loop = asyncio.get_event_loop()
                        self._task = asyncio.run_coroutine_threadsafe(self._run_loop(), main_loop)
                    except Exception as e:
                        logger.error(f"Failed to schedule generation task: {e}")

    def pause(self):
        """Pause generation gracefully."""
        self.is_paused = True
        self.log_event("Generation worker paused.", "warning")

    def resume(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Resume generation."""
        if not self.is_running:
            self.start(loop=loop)
        else:
            self.is_paused = False
            self.log_event("Generation worker resumed.", "success")

    def stop(self):
        """Stop worker completely."""
        self.is_running = False
        self.is_paused = False
        if self._task:
            self._task.cancel()
            self._task = None
        self.log_event("Generation worker stopped.", "error")

    async def _run_loop(self):
        """Main round-robin loop."""
        while self.is_running:
            try:
                if self.is_paused:
                    self.last_action = "Paused"
                    await asyncio.sleep(2)
                    continue

                # Fetch all active subjects
                all_subjects = self.storage.get_subjects()
                active_subjects = [s for s in all_subjects if s.get("is_active")]

                if not active_subjects:
                    self.last_action = "Waiting for active subjects..."
                    await asyncio.sleep(4)
                    continue

                # Interleave generation: 1 batch per active subject in round-robin order
                for s in active_subjects:
                    if not self.is_running or self.is_paused:
                        break

                    # Re-verify subject is still active before generating
                    current_s = next((x for x in self.storage.get_subjects() if x["name"] == s["name"]), None)
                    if not current_s or not current_s.get("is_active"):
                        continue

                    subject_name = s["name"]
                    exam_code = s.get("exam_code", "RRB")
                    speed_delay = s.get("speed_delay_seconds", 15)

                    self.current_subject = subject_name
                    self.last_action = f"Generating for {subject_name}..."

                    await self._generate_for_subject(subject_name, exam_code)

                    # Check if 100 questions reached for dispatch
                    await self._check_and_dispatch(subject_name, exam_code)

                    # Respect subject rate limit delay
                    await asyncio.sleep(speed_delay)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log_event(f"Worker exception: {str(e)[:150]}", "error")
                await asyncio.sleep(5)

        self.last_action = "Stopped"

    async def _generate_for_subject(self, subject_name: str, exam_code: str):
        """Generate a batch of 5-8 verified MCQs for a given subject."""
        # 1. Determine Topic from Syllabus if available
        syllabus = self.storage.get_syllabus(subject_name)
        topic_name = "General"
        concepts_list = []

        if syllabus and syllabus.get("parsed_hierarchy"):
            topics = syllabus["parsed_hierarchy"]
            if isinstance(topics, list) and len(topics) > 0:
                # Pick topic cyclically or random
                import random
                chosen_topic = random.choice(topics)
                topic_name = chosen_topic.get("name") or chosen_topic.get("topic") or "General"
                concepts_list = chosen_topic.get("concepts", [])

        self.current_topic = topic_name

        # 2. Smart Real-World Intent Detection (Any subject requiring online real-world context)
        is_gk = "knowledge" in subject_name.lower() or "current" in subject_name.lower() or "gk" in subject_name.lower()
        needs_search, search_query = self.search_manager.detect_realworld_need(subject_name, topic_name, concepts_list)
        if not needs_search and is_gk and self.search_manager.enabled:
            needs_search = True
            search_query = f"{subject_name} {topic_name} current affairs developments facts 2024 2025"

        search_context = ""
        loop = asyncio.get_running_loop()

        if needs_search and self.search_manager.enabled:
            self.log_event(f"[SMART-SEARCH] Real-world online context detected for [{subject_name} -> {topic_name}]. Cascading Tavily → Brave → Exa...")
            try:
                search_res = await loop.run_in_executor(
                    None, lambda: self.search_manager.search(search_query, num_results=4)
                )
                if search_res.get("snippets"):
                    search_context = search_res.get("formatted_context", "")
                    prov_used = search_res.get("provider_used", "none").capitalize()
                    self.log_event(f"Online ground-truth retrieved via {prov_used} ({len(search_res['snippets'])} snippets).", "success")
            except Exception as e:
                logger.warning(f"Web search execution error: {e}")

        # 3. Build Prompt with grounded search context
        prompt = self._build_generation_prompt(
            subject_name, topic_name, exam_code, is_gk or bool(search_context), concepts_list, search_context=search_context
        )

        search_tag = "Active" if search_context else "None"
        self.log_event(f"Requesting candidates for [{subject_name}] -> {topic_name} (Smart Web Search: {search_tag})...")

        # Execute LLM call in executor with multi-key pool fallback
        try:
            raw_response = await loop.run_in_executor(
                None, lambda: self.llm.generate_json(prompt, is_gk=is_gk or bool(search_context), temperature=0.3)
            )
        except Exception as e:
            self.log_event(f"All LLM key pools currently busy: {str(e)[:100]}. Backing off gracefully...", "warning")
            await asyncio.sleep(10)
            return

        if not raw_response or not isinstance(raw_response, list):
            self.log_event(f"No questions parsed for {subject_name}. Moving to next subject in cycle.", "warning")
            return

        # 4. Validate and Save
        approved_count = 0
        rejected_count = 0

        for item in raw_response:
            if not isinstance(item, dict):
                continue

            q_text = item.get("questionText") or item.get("question_text") or ""
            op_a = item.get("optionA") or item.get("option_a") or ""
            op_b = item.get("optionB") or item.get("option_b") or ""
            op_c = item.get("optionC") or item.get("option_c") or ""
            op_d = item.get("optionD") or item.get("option_d") or ""
            c_ans = item.get("correctAnswer") or item.get("correct_answer") or "A"
            explanation = item.get("explanation") or ""
            difficulty = item.get("difficulty") or "Medium"
            tags = item.get("tags") or f"{subject_name.lower()}, {topic_name.lower()}"

            # Validate basic schema
            if not (q_text and op_a and op_b and op_c and op_d and explanation):
                rejected_count += 1
                continue

            # Validate unique distractors
            options = [op_a.strip().lower(), op_b.strip().lower(), op_c.strip().lower(), op_d.strip().lower()]
            if len(set(options)) < 4:
                rejected_count += 1
                continue

            # Compute hash & check duplicates
            h = compute_normalized_hash(q_text)
            if self.storage.is_duplicate_hash(h):
                rejected_count += 1
                self.log_event(f"Duplicate rejected: '{q_text[:40]}...'", "warning")
                continue

            # Save approved question
            question_record = {
                "id": str(uuid.uuid4()),
                "subject_name": subject_name,
                "topic_name": topic_name,
                "exam_code": exam_code,
                "question_text": q_text,
                "option_a": op_a,
                "option_b": op_b,
                "option_c": op_c,
                "option_d": op_d,
                "correct_answer": str(c_ans).strip().upper()[:1],
                "explanation": explanation,
                "difficulty": difficulty,
                "tags": tags,
                "normalized_hash": h,
                "status": "READY_TO_DISPATCH",
            }

            saved = self.storage.save_question(question_record)
            if saved:
                approved_count += 1

        self.log_event(f"Saved {approved_count} new questions for {subject_name} ({rejected_count} rejected/dup).", "success")

    def _build_generation_prompt(
        self,
        subject_name: str,
        topic_name: str,
        exam_code: str,
        is_gk: bool,
        concepts: list,
        search_context: str = "",
    ) -> str:
        """Construct high-quality question generation prompt in English."""
        extra_ctx = ""
        if search_context:
            extra_ctx = (
                f"GROUNDED REAL-TIME WEB SEARCH CONTEXT (Verified):\n{search_context}\n\n"
                "CRITICAL: Formulate MCQs directly based on the verified facts above to ensure 100% factual accuracy on 2024-2026 developments."
            )
        elif is_gk:
            extra_ctx = (
                "IMPORTANT: Focus on real, verified events, appointments, sports, national schemes, "
                "or developments from 2024 to 2026. Ensure 100% factual accuracy."
            )
        elif concepts:
            concept_names = [c.get("name", "") for c in concepts[:3] if isinstance(c, dict)]
            if concept_names:
                extra_ctx = f"Sub-concepts to cover: {', '.join(concept_names)}."

        return f"""
Generate 6 high-quality, non-repetitive Multiple Choice Questions (MCQs) in ENGLISH for:
- Exam: {exam_code}
- Subject: {subject_name}
- Topic: {topic_name}
{extra_ctx}

Guidelines:
1. Standard 4 options (optionA, optionB, optionC, optionD). Exactly one unambiguous correct answer.
2. All distractors must be distinct and plausible. Do NOT use "All of the above" or "None of the above".
3. Provide a clear, educational explanation.
4. Set difficulty to "Easy", "Medium", or "Hard".
5. Output valid JSON array with this exact format:
[
  {{
    "questionText": "What is the capital of ...?",
    "optionA": "...",
    "optionB": "...",
    "optionC": "...",
    "optionD": "...",
    "correctAnswer": "A",
    "explanation": "...",
    "difficulty": "Medium",
    "tags": "{subject_name.lower()}, {topic_name.lower()}"
  }}
]
"""

    async def _check_and_dispatch(self, subject_name: str, exam_code: str):
        """Check if ready question count has hit threshold (default 100) and dispatch."""
        config = self.storage.get_config()
        batch_size = int(config.get("batch_size") or 100)
        auto_dispatch = bool(config.get("auto_dispatch", True))
        endpoint_url = config.get("examforge_url", "")
        api_key = config.get("examforge_api_key", "")

        ready_count = self.storage.get_subject_ready_count(subject_name)

        if ready_count >= batch_size:
            if not auto_dispatch:
                self.log_event(f"Batch threshold reached ({ready_count}/{batch_size}) for {subject_name}. Awaiting manual dispatch.", "warning")
                return

            self.log_event(f"Batch threshold reached ({ready_count} questions)! Auto-dispatching to ExamForge...", "success")

            questions_to_send = self.storage.get_ready_questions(subject_name=subject_name, limit=batch_size)
            if not questions_to_send:
                return

            # Execute dispatch in executor
            loop = asyncio.get_running_loop()
            batch_num = f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{subject_name[:3].upper()}"

            success, status, resp = await loop.run_in_executor(
                None,
                lambda: self.examforge.dispatch_batch(
                    questions=questions_to_send,
                    subject_name=subject_name,
                    topic_name=self.current_topic or "General",
                    exam_code=exam_code,
                    endpoint_url=endpoint_url,
                    api_key=api_key,
                )
            )

            # Record dispatch history
            q_ids = [q["id"] for q in questions_to_send]
            self.storage.record_dispatch(
                batch_number=batch_num,
                exam_code=exam_code,
                subject_name=subject_name,
                topic_name=self.current_topic or "General",
                question_count=len(questions_to_send),
                endpoint_url=endpoint_url,
                status_code=status,
                response_payload=resp,
                questions_payload=[self.examforge.format_question_for_ingest(q) for q in questions_to_send],
            )

            if success:
                self.storage.mark_questions_dispatched(q_ids, batch_num)
                self.log_event(f"SUCCESS: Batch {batch_num} ({len(questions_to_send)} questions) delivered to ExamForge (HTTP {status})!", "success")
            else:
                self.log_event(f"FAILED to deliver batch to ExamForge (HTTP {status}): {resp}", "error")

    def get_live_status(self) -> dict:
        """Return live metrics for the UI dashboard."""
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "current_subject": self.current_subject,
            "current_topic": self.current_topic,
            "last_action": self.last_action,
            "recent_logs": self.activity_logs[-25:],
            "search_status": self.search_manager.get_status(),
        }
