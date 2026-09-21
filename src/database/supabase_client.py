"""
Database Storage Layer — Supabase Cloud with Automatic SQLite Fallback.
Provides unified persistence for Subjects, Questions, Dispatches, and Syllabi.
"""
from __future__ import annotations
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
import uuid

from config.settings import (
    SUPABASE_URL,
    SUPABASE_KEY,
    PROJECT_ROOT,
    EXAMFORGE_API_URL,
    EXAMFORGE_API_KEY,
    EXAMFORGE_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

SQLITE_PATH = PROJECT_ROOT / "config" / "storage.db"


class StorageManager:
    """
    Unified Storage Interface.
    Uses Supabase if credentials are provided; otherwise uses SQLite local DB.
    """

    def __init__(self, supabase_url: str = "", supabase_key: str = ""):
        self.supabase_url = supabase_url or SUPABASE_URL
        self.supabase_key = supabase_key or SUPABASE_KEY
        self.supabase_client = None
        self.use_supabase = False
        self.use_postgres = False
        self.pg_url = ""

        # 1. Direct Supabase PostgreSQL connection URI support (e.g. postgresql://postgres...)
        if self.supabase_url and (self.supabase_url.startswith("postgresql://") or self.supabase_url.startswith("postgres://")):
            try:
                import psycopg2
                test_conn = psycopg2.connect(self.supabase_url)
                test_conn.close()
                self.use_postgres = True
                self.pg_url = self.supabase_url
                logger.info("Supabase PostgreSQL direct pooler connected successfully.")
            except Exception as e:
                logger.warning(f"Failed to connect to Supabase PostgreSQL: {e}. Falling back to SQLite.")
        elif self.supabase_url and self.supabase_key:
            try:
                from supabase import create_client
                self.supabase_client = create_client(self.supabase_url, self.supabase_key)
                self.use_supabase = True
                logger.info("Supabase REST storage client initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to connect to Supabase: {e}. Falling back to SQLite.")

        # Always initialize SQLite tables to guarantee local fallback & offline readiness
        self._init_sqlite()

    def _execute_pg(self, query: str, params: tuple = (), fetch_all: bool = False, fetch_one: bool = False, commit: bool = True):
        import psycopg2
        from psycopg2.extras import RealDictCursor, Json
        pg_query = query.replace("?", "%s")
        adapted_params = []
        for p in params:
            if isinstance(p, (dict, list)):
                adapted_params.append(Json(p))
            else:
                adapted_params.append(p)
        with psycopg2.connect(self.pg_url) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(pg_query, tuple(adapted_params))
                if commit:
                    conn.commit()
                if fetch_all:
                    return [dict(r) for r in cur.fetchall()]
                if fetch_one:
                    row = cur.fetchone()
                    return dict(row) if row else None
                return None

    def _init_sqlite(self):
        """Initialize SQLite tables matching schema.sql."""
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SQLITE_PATH) as conn:
            c = conn.cursor()

            c.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                id TEXT PRIMARY KEY,
                examforge_url TEXT,
                examforge_api_key TEXT,
                batch_size INTEGER,
                auto_dispatch BOOLEAN,
                active_provider TEXT,
                gemini_api_key TEXT,
                openrouter_api_key TEXT,
                groq_api_key TEXT,
                gemini_keys TEXT DEFAULT '[]',
                openrouter_keys TEXT DEFAULT '[]',
                groq_keys TEXT DEFAULT '[]',
                gemini_models TEXT DEFAULT '["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-flash"]',
                tavily_api_key TEXT,
                brave_api_key TEXT,
                exa_api_key TEXT,
                web_search_enabled BOOLEAN DEFAULT 1,
                smart_search_enabled BOOLEAN DEFAULT 1,
                updated_at TEXT
            )
            """)

            # Ensure newly added columns exist in existing SQLite databases
            for col_name, col_type in [
                ("tavily_api_key", "TEXT"),
                ("brave_api_key", "TEXT"),
                ("exa_api_key", "TEXT"),
                ("web_search_enabled", "BOOLEAN DEFAULT 1"),
                ("gemini_keys", "TEXT DEFAULT '[]'"),
                ("openrouter_keys", "TEXT DEFAULT '[]'"),
                ("groq_keys", "TEXT DEFAULT '[]'"),
                ("gemini_models", "TEXT DEFAULT '[\"gemini-3.8-flash\", \"gemini-3.7-flash\", \"gemini-3.6-flash\", \"gemini-2.5-flash\"]'"),
                ("smart_search_enabled", "BOOLEAN DEFAULT 1"),
            ]:
                try:
                    c.execute(f"ALTER TABLE app_config ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

            c.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                exam_code TEXT,
                is_active BOOLEAN,
                speed_delay_seconds INTEGER,
                target_count INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS syllabi (
                id TEXT PRIMARY KEY,
                subject_name TEXT UNIQUE,
                exam_code TEXT,
                raw_text TEXT,
                parsed_hierarchy TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                subject_name TEXT,
                topic_name TEXT,
                exam_code TEXT,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_answer TEXT,
                explanation TEXT,
                difficulty TEXT,
                tags TEXT,
                normalized_hash TEXT UNIQUE,
                status TEXT,
                batch_id TEXT,
                dispatched_at TEXT,
                created_at TEXT
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS dispatch_batches (
                id TEXT PRIMARY KEY,
                batch_number TEXT UNIQUE,
                exam_code TEXT,
                subject_name TEXT,
                topic_name TEXT,
                question_count INTEGER,
                endpoint_url TEXT,
                status_code INTEGER,
                response_payload TEXT,
                questions_payload TEXT,
                created_at TEXT
            )
            """)

            # Seed default config if empty
            c.execute("SELECT id FROM app_config WHERE id = 'global'")
            if not c.fetchone():
                c.execute(
                    "INSERT INTO app_config (id, examforge_url, examforge_api_key, batch_size, auto_dispatch, active_provider, web_search_enabled, smart_search_enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ('global', EXAMFORGE_API_URL, EXAMFORGE_API_KEY, EXAMFORGE_BATCH_SIZE, 1, 'gemini', 1, 1)
                )

            # Seed initial default subjects if empty
            c.execute("SELECT COUNT(*) FROM subjects")
            count = c.fetchone()[0]
            if count == 0:
                defaults = [
                    (str(uuid.uuid4()), 'Science', 'RRB', 1, 15, 120),
                    (str(uuid.uuid4()), 'Mathematics', 'RRB', 1, 15, 120),
                    (str(uuid.uuid4()), 'General Knowledge', 'RRB', 1, 15, 120),
                    (str(uuid.uuid4()), 'Disability', 'DSC', 1, 15, 120),
                    (str(uuid.uuid4()), 'Perspectives Special Ed', 'DSC', 1, 15, 120),
                    (str(uuid.uuid4()), 'Psychology', 'DSC', 1, 15, 120),
                    (str(uuid.uuid4()), 'Sped Methodology', 'DSC', 1, 15, 120),
                ]
                now_str = datetime.now(timezone.utc).isoformat()
                c.executemany(
                    "INSERT INTO subjects (id, name, exam_code, is_active, speed_delay_seconds, target_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(d[0], d[1], d[2], d[3], d[4], d[5], now_str, now_str) for d in defaults]
                )
            conn.commit()

    # ── Config Methods ────────────────────────────────────────────────────────

    def _normalize_config(self, cfg: dict) -> dict:
        """Normalize configuration so multi-key lists and model lists are always valid lists."""
        if not cfg:
            cfg = {}
        for key in ["gemini_keys", "openrouter_keys", "groq_keys", "gemini_models"]:
            val = cfg.get(key)
            if isinstance(val, str):
                try:
                    cfg[key] = json.loads(val)
                except Exception:
                    cfg[key] = []
            elif not isinstance(val, list):
                cfg[key] = []

        # Fallback to single key if multi-key list is empty
        if not cfg.get("gemini_keys") and cfg.get("gemini_api_key"):
            cfg["gemini_keys"] = [cfg["gemini_api_key"]]
        if not cfg.get("openrouter_keys") and cfg.get("openrouter_api_key"):
            cfg["openrouter_keys"] = [cfg["openrouter_api_key"]]
        if not cfg.get("groq_keys") and cfg.get("groq_api_key"):
            cfg["groq_keys"] = [cfg["groq_api_key"]]

        # Default gemini models if empty
        if not cfg.get("gemini_models"):
            cfg["gemini_models"] = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]

        if "smart_search_enabled" not in cfg:
            cfg["smart_search_enabled"] = True
        if "web_search_enabled" not in cfg:
            cfg["web_search_enabled"] = True
        return cfg

    def get_config(self) -> dict:
        """Get global app configuration."""
        raw_cfg = None
        if self.use_postgres:
            try:
                row = self._execute_pg("SELECT * FROM app_config WHERE id = 'global'", fetch_one=True)
                if row:
                    raw_cfg = row
            except Exception as e:
                logger.warning(f"Supabase PG get_config error: {e}")

        if not raw_cfg and self.use_supabase:
            try:
                res = self.supabase_client.table("app_config").select("*").eq("id", "global").execute()
                if res.data:
                    raw_cfg = res.data[0]
            except Exception as e:
                logger.warning(f"Supabase get_config error: {e}")

        if not raw_cfg:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM app_config WHERE id = 'global'").fetchone()
                if row:
                    raw_cfg = dict(row)

        if not raw_cfg:
            raw_cfg = {
                "examforge_url": EXAMFORGE_API_URL,
                "examforge_api_key": EXAMFORGE_API_KEY,
                "batch_size": EXAMFORGE_BATCH_SIZE,
                "auto_dispatch": True,
                "active_provider": "gemini",
                "gemini_api_key": "",
                "openrouter_api_key": "",
                "groq_api_key": "",
                "gemini_keys": [],
                "openrouter_keys": [],
                "groq_keys": [],
                "gemini_models": ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
                "tavily_api_key": "",
                "brave_api_key": "",
                "exa_api_key": "",
                "web_search_enabled": True,
                "smart_search_enabled": True,
            }

        return self._normalize_config(raw_cfg)

    def update_config(self, updates: dict):
        """Update app configuration."""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self.use_postgres:
            try:
                set_clauses = [f"{k} = ?" for k in updates.keys()]
                values = list(updates.values())
                query = f"UPDATE app_config SET {', '.join(set_clauses)} WHERE id = 'global'"
                self._execute_pg(query, tuple(values))
            except Exception as e:
                logger.warning(f"Supabase PG update_config error: {e}")

        if self.use_supabase:
            try:
                self.supabase_client.table("app_config").upsert({"id": "global", **updates}).execute()
            except Exception as e:
                logger.warning(f"Supabase update_config error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            # For SQLite, serialize list/dict fields to JSON strings
            sqlite_updates = {}
            for k, v in updates.items():
                if isinstance(v, (list, dict)):
                    sqlite_updates[k] = json.dumps(v)
                else:
                    sqlite_updates[k] = v
            set_clauses = [f"{k} = ?" for k in sqlite_updates.keys()]
            values = list(sqlite_updates.values())
            query = f"UPDATE app_config SET {', '.join(set_clauses)} WHERE id = 'global'"
            conn.execute(query, values)
            conn.commit()
            conn.commit()

    # ── Subjects Methods ──────────────────────────────────────────────────────

    def get_subjects(self) -> list[dict]:
        """Get all subjects with pending and dispatched question counts."""
        subjects = []
        if self.use_postgres:
            try:
                subjects = self._execute_pg("SELECT * FROM subjects ORDER BY name", fetch_all=True) or []
            except Exception as e:
                logger.warning(f"Supabase PG get_subjects error: {e}")

        if not subjects and self.use_supabase:
            try:
                res = self.supabase_client.table("subjects").select("*").order("name").execute()
                subjects = res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_subjects error: {e}")

        if not subjects:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                subjects = [dict(r) for r in conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()]

        # Attach real-time counts to each subject
        for s in subjects:
            s["ready_count"] = self.get_subject_ready_count(s["name"])
            s["total_count"] = self.get_subject_total_count(s["name"])

        return subjects

    def toggle_subject(self, name: str, is_active: bool):
        """Toggle subject generation ON / OFF."""
        now_str = datetime.now(timezone.utc).isoformat()
        if self.use_postgres:
            try:
                self._execute_pg("UPDATE subjects SET is_active = ?, updated_at = ? WHERE name = ?", (is_active, now_str, name))
            except Exception as e:
                logger.warning(f"Supabase PG toggle_subject error: {e}")

        if self.use_supabase:
            try:
                self.supabase_client.table("subjects").update({
                    "is_active": is_active,
                    "updated_at": now_str
                }).eq("name", name).execute()
            except Exception as e:
                logger.warning(f"Supabase toggle_subject error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("UPDATE subjects SET is_active = ?, updated_at = ? WHERE name = ?", (is_active, now_str, name))
            conn.commit()

    def update_subject_speed(self, name: str, speed_seconds: int):
        """Update subject rate limit delay in seconds."""
        now_str = datetime.now(timezone.utc).isoformat()
        if self.use_postgres:
            try:
                self._execute_pg("UPDATE subjects SET speed_delay_seconds = ?, updated_at = ? WHERE name = ?", (speed_seconds, now_str, name))
            except Exception as e:
                logger.warning(f"Supabase PG update_subject_speed error: {e}")

        if self.use_supabase:
            try:
                self.supabase_client.table("subjects").update({
                    "speed_delay_seconds": speed_seconds,
                    "updated_at": now_str
                }).eq("name", name).execute()
            except Exception as e:
                logger.warning(f"Supabase update_subject_speed error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("UPDATE subjects SET speed_delay_seconds = ?, updated_at = ? WHERE name = ?", (speed_seconds, now_str, name))
            conn.commit()

    def create_or_get_subject(self, name: str, exam_code: str = "RRB") -> dict:
        """Ensure subject exists in subjects table, creating it if not."""
        clean_name = name.strip()
        now_str = datetime.now(timezone.utc).isoformat()
        s_id = str(uuid.uuid4())

        if self.use_postgres:
            try:
                row = self._execute_pg("SELECT * FROM subjects WHERE name = ?", (clean_name,), fetch_one=True)
                if row:
                    return row
                new_s = {
                    "id": s_id,
                    "name": clean_name,
                    "exam_code": exam_code,
                    "is_active": True,
                    "speed_delay_seconds": 15,
                    "target_count": 120,
                    "created_at": now_str,
                    "updated_at": now_str,
                }
                self._execute_pg(
                    "INSERT INTO subjects (id, name, exam_code, is_active, speed_delay_seconds, target_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (s_id, clean_name, exam_code, True, 15, 120, now_str, now_str)
                )
                return new_s
            except Exception as e:
                logger.warning(f"Supabase PG create_or_get_subject error: {e}")

        if self.use_supabase:
            try:
                res = self.supabase_client.table("subjects").select("*").eq("name", clean_name).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
                new_s = {
                    "id": s_id,
                    "name": clean_name,
                    "exam_code": exam_code,
                    "is_active": True,
                    "speed_delay_seconds": 15,
                    "target_count": 120,
                    "created_at": now_str,
                    "updated_at": now_str,
                }
                self.supabase_client.table("subjects").insert(new_s).execute()
                return new_s
            except Exception as e:
                logger.warning(f"Supabase create_or_get_subject error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM subjects WHERE name = ?", (clean_name,)).fetchone()
            if row:
                return dict(row)

            conn.execute(
                "INSERT INTO subjects (id, name, exam_code, is_active, speed_delay_seconds, target_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (s_id, clean_name, exam_code, 1, 15, 120, now_str, now_str)
            )
            conn.commit()
            return {
                "id": s_id,
                "name": clean_name,
                "exam_code": exam_code,
                "is_active": True,
                "speed_delay_seconds": 15,
                "target_count": 120,
            }

    # ── Questions Methods ─────────────────────────────────────────────────────

    def get_subject_ready_count(self, subject_name: str) -> int:
        """Count questions ready for dispatch for a subject."""
        if self.use_supabase:
            try:
                res = self.supabase_client.table("questions").select("id", count="exact").eq("subject_name", subject_name).eq("status", "READY_TO_DISPATCH").execute()
                if res.count is not None:
                    return res.count
            except Exception as e:
                logger.warning(f"Supabase count error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            res = conn.execute("SELECT COUNT(*) FROM questions WHERE subject_name = ? AND status = 'READY_TO_DISPATCH'", (subject_name,)).fetchone()
            return res[0] if res else 0

    def get_subject_total_count(self, subject_name: str) -> int:
        """Count total questions generated for a subject."""
        if self.use_supabase:
            try:
                res = self.supabase_client.table("questions").select("id", count="exact").eq("subject_name", subject_name).execute()
                if res.count is not None:
                    return res.count
            except Exception as e:
                pass

        with sqlite3.connect(SQLITE_PATH) as conn:
            res = conn.execute("SELECT COUNT(*) FROM questions WHERE subject_name = ?", (subject_name,)).fetchone()
            return res[0] if res else 0

    def save_question(self, q: dict) -> bool:
        """Save a newly approved question."""
        q_id = q.get("id") or str(uuid.uuid4())
        q["id"] = q_id
        q["created_at"] = q.get("created_at") or datetime.now(timezone.utc).isoformat()
        q["status"] = q.get("status") or "READY_TO_DISPATCH"

        # Check for duplicate hash
        h = q.get("normalized_hash", "")
        if self.is_duplicate_hash(h):
            return False

        if self.use_supabase:
            try:
                self.supabase_client.table("questions").insert(q).execute()
                # Also save to SQLite for local sync
            except Exception as e:
                logger.warning(f"Supabase save_question error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            try:
                conn.execute("""
                INSERT INTO questions (
                    id, subject_name, topic_name, exam_code, question_text,
                    option_a, option_b, option_c, option_d, correct_answer,
                    explanation, difficulty, tags, normalized_hash, status,
                    batch_id, dispatched_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    q["id"], q.get("subject_name", ""), q.get("topic_name", "General"),
                    q.get("exam_code", "RRB"), q.get("question_text", ""),
                    q.get("option_a", ""), q.get("option_b", ""), q.get("option_c", ""),
                    q.get("option_d", ""), q.get("correct_answer", ""),
                    q.get("explanation", ""), q.get("difficulty", "Medium"),
                    q.get("tags", ""), h, q["status"], q.get("batch_id"),
                    q.get("dispatched_at"), q["created_at"]
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def is_duplicate_hash(self, hash_str: str) -> bool:
        """Check if hash already exists in database."""
        if not hash_str:
            return False
        if self.use_supabase:
            try:
                res = self.supabase_client.table("questions").select("id").eq("normalized_hash", hash_str).execute()
                if res.data:
                    return True
            except Exception as e:
                pass

        with sqlite3.connect(SQLITE_PATH) as conn:
            res = conn.execute("SELECT id FROM questions WHERE normalized_hash = ?", (hash_str,)).fetchone()
            return bool(res)

    def get_all_hashes(self) -> set[str]:
        """Get all known hashes to initialize duplicate detector."""
        hashes = set()
        if self.use_supabase:
            try:
                res = self.supabase_client.table("questions").select("normalized_hash").execute()
                for r in res.data or []:
                    if r.get("normalized_hash"):
                        hashes.add(r["normalized_hash"])
            except Exception as e:
                pass

        with sqlite3.connect(SQLITE_PATH) as conn:
            for row in conn.execute("SELECT normalized_hash FROM questions WHERE normalized_hash IS NOT NULL").fetchall():
                hashes.add(row[0])
        return hashes

    def get_ready_questions(self, subject_name: Optional[str] = None, limit: int = 100) -> list[dict]:
        """Fetch questions ready for dispatch."""
        questions = []
        if self.use_supabase:
            try:
                query = self.supabase_client.table("questions").select("*").eq("status", "READY_TO_DISPATCH")
                if subject_name:
                    query = query.eq("subject_name", subject_name)
                res = query.order("created_at").limit(limit).execute()
                questions = res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_ready_questions error: {e}")

        if not questions:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                sql = "SELECT * FROM questions WHERE status = 'READY_TO_DISPATCH'"
                params = []
                if subject_name:
                    sql += " AND subject_name = ?"
                    params.append(subject_name)
                sql += " ORDER BY created_at LIMIT ?"
                params.append(limit)
                questions = [dict(r) for r in conn.execute(sql, params).fetchall()]

        return questions

    def mark_questions_dispatched(self, question_ids: list[str], batch_id: str):
        """Mark a batch of questions as DISPATCHED."""
        now_str = datetime.now(timezone.utc).isoformat()
        if self.use_supabase:
            try:
                self.supabase_client.table("questions").update({
                    "status": "DISPATCHED",
                    "batch_id": batch_id,
                    "dispatched_at": now_str
                }).in_("id", question_ids).execute()
            except Exception as e:
                logger.warning(f"Supabase mark_questions_dispatched error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            placeholders = ",".join(["?"] * len(question_ids))
            conn.execute(
                f"UPDATE questions SET status = 'DISPATCHED', batch_id = ?, dispatched_at = ? WHERE id IN ({placeholders})",
                [batch_id, now_str] + question_ids
            )
            conn.commit()

    # ── Dispatches Audit Log ──────────────────────────────────────────────────

    def record_dispatch(
        self,
        batch_number: str,
        exam_code: str,
        subject_name: str,
        topic_name: str,
        question_count: int,
        endpoint_url: str,
        status_code: int,
        response_payload: Any,
        questions_payload: list[dict],
    ) -> str:
        """Record batch delivery log for audit."""
        b_id = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        resp_json = response_payload if isinstance(response_payload, dict) else {"response": str(response_payload)}

        record = {
            "id": b_id,
            "batch_number": batch_number,
            "exam_code": exam_code,
            "subject_name": subject_name,
            "topic_name": topic_name,
            "question_count": question_count,
            "endpoint_url": endpoint_url,
            "status_code": status_code,
            "response_payload": resp_json,
            "questions_payload": questions_payload,
            "created_at": now_str,
        }

        if self.use_supabase:
            try:
                self.supabase_client.table("dispatch_batches").insert(record).execute()
            except Exception as e:
                logger.warning(f"Supabase record_dispatch error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("""
            INSERT INTO dispatch_batches (
                id, batch_number, exam_code, subject_name, topic_name,
                question_count, endpoint_url, status_code, response_payload,
                questions_payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                b_id, batch_number, exam_code, subject_name, topic_name,
                question_count, endpoint_url, status_code,
                json.dumps(resp_json), json.dumps(questions_payload), now_str
            ))
            conn.commit()

        return b_id

    def get_dispatches(self, limit: int = 50) -> list[dict]:
        """Fetch history of dispatched batches."""
        dispatches = []
        if self.use_supabase:
            try:
                res = self.supabase_client.table("dispatch_batches").select("*").order("created_at", desc=True).limit(limit).execute()
                dispatches = res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_dispatches error: {e}")

        if not dispatches:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                dispatches = [dict(r) for r in conn.execute("SELECT * FROM dispatch_batches ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
                for d in dispatches:
                    if isinstance(d.get("response_payload"), str):
                        try:
                            d["response_payload"] = json.loads(d["response_payload"])
                        except Exception:
                            pass

        return dispatches

    # ── Syllabus Methods ──────────────────────────────────────────────────────

    def save_syllabus(
        self,
        subject_name: str,
        exam_code: str,
        raw_text: str,
        parsed_hierarchy: list[dict],
        mode: str = "replace",
    ) -> list[dict]:
        """Save raw text and parsed topic tree. Supports replace or update (merge) mode."""
        s_id = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        hierarchy_json = parsed_hierarchy if isinstance(parsed_hierarchy, list) else []

        if mode == "update":
            existing = self.get_syllabus(subject_name)
            if existing:
                # Merge raw_text
                old_raw = existing.get("raw_text") or ""
                if old_raw and raw_text and raw_text not in old_raw:
                    raw_text = f"{old_raw}\n\n=== SYLLABUS UPDATE ===\n{raw_text}".strip()
                elif old_raw and not raw_text:
                    raw_text = old_raw

                # Merge parsed_hierarchy
                existing_topics = existing.get("parsed_hierarchy") or []
                topic_map = {t.get("name", "").strip().lower(): t for t in existing_topics if isinstance(t, dict)}

                for new_t in hierarchy_json:
                    if not isinstance(new_t, dict):
                        continue
                    key = new_t.get("name", "").strip().lower()
                    if key in topic_map:
                        ext_t = topic_map[key]
                        # Merge concepts
                        ext_concepts = ext_t.get("concepts") or []
                        ext_c_names = {
                            (c.get("name") if isinstance(c, dict) else str(c)).strip().lower()
                            for c in ext_concepts
                        }
                        for new_c in (new_t.get("concepts") or []):
                            c_name = (new_c.get("name") if isinstance(new_c, dict) else str(new_c)).strip().lower()
                            if c_name not in ext_c_names:
                                ext_concepts.append(new_c)
                        ext_t["concepts"] = ext_concepts
                    else:
                        existing_topics.append(new_t)

                hierarchy_json = existing_topics

        if self.use_postgres:
            try:
                import json
                self._execute_pg("""
                    INSERT INTO syllabi (id, subject_name, exam_code, raw_text, parsed_hierarchy, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?::jsonb, ?, ?)
                    ON CONFLICT(subject_name) DO UPDATE SET
                        exam_code = EXCLUDED.exam_code,
                        raw_text = EXCLUDED.raw_text,
                        parsed_hierarchy = EXCLUDED.parsed_hierarchy,
                        updated_at = EXCLUDED.updated_at
                """, (s_id, subject_name, exam_code, raw_text, json.dumps(hierarchy_json), now_str, now_str))
            except Exception as e:
                logger.warning(f"Supabase PG save_syllabus error: {e}")

        if self.use_supabase:
            try:
                self.supabase_client.table("syllabi").upsert({
                    "subject_name": subject_name,
                    "exam_code": exam_code,
                    "raw_text": raw_text,
                    "parsed_hierarchy": hierarchy_json,
                    "updated_at": now_str,
                }, on_conflict="subject_name").execute()
            except Exception as e:
                logger.warning(f"Supabase save_syllabus error: {e}")

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("""
            INSERT INTO syllabi (id, subject_name, exam_code, raw_text, parsed_hierarchy, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject_name) DO UPDATE SET
                exam_code = excluded.exam_code,
                raw_text = excluded.raw_text,
                parsed_hierarchy = excluded.parsed_hierarchy,
                updated_at = excluded.updated_at
            """, (s_id, subject_name, exam_code, raw_text, json.dumps(hierarchy_json), now_str, now_str))
            conn.commit()

        return hierarchy_json

    def get_syllabus(self, subject_name: str) -> Optional[dict]:
        """Get syllabus tree for a subject."""
        if self.use_postgres:
            try:
                import json
                row = self._execute_pg("SELECT * FROM syllabi WHERE subject_name = ?", (subject_name,), fetch_one=True)
                if row:
                    if isinstance(row.get("parsed_hierarchy"), str):
                        row["parsed_hierarchy"] = json.loads(row["parsed_hierarchy"])
                    return row
            except Exception as e:
                logger.warning(f"Supabase PG get_syllabus error: {e}")

        if self.use_supabase:
            try:
                res = self.supabase_client.table("syllabi").select("*").eq("subject_name", subject_name).execute()
                if res.data:
                    return res.data[0]
            except Exception as e:
                pass

        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM syllabi WHERE subject_name = ?", (subject_name,)).fetchone()
            if row:
                d = dict(row)
                if isinstance(d.get("parsed_hierarchy"), str):
                    try:
                        d["parsed_hierarchy"] = json.loads(d["parsed_hierarchy"])
                    except Exception:
                        pass
                return d
        return None

    def get_all_syllabi(self) -> list[dict]:
        """Fetch all syllabi."""
        syllabi = []
        if self.use_supabase:
            try:
                res = self.supabase_client.table("syllabi").select("*").execute()
                syllabi = res.data or []
            except Exception as e:
                pass

        if not syllabi:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                syllabi = [dict(r) for r in conn.execute("SELECT * FROM syllabi").fetchall()]
                for s in syllabi:
                    if isinstance(s.get("parsed_hierarchy"), str):
                        try:
                            s["parsed_hierarchy"] = json.loads(s["parsed_hierarchy"])
                        except Exception:
                            pass
        return syllabi
