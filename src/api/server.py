"""
FastAPI Production Server for ExamForge AI Question Platform.
Serves REST API, Background Generation Worker, and Admin UI.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Any
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import PROJECT_ROOT, ADMIN_EMAIL, ADMIN_PASSWORD
from src.database.supabase_client import StorageManager
from src.generator.llm_manager import MultiProviderLLM
from src.export.examforge_client import ExamForgeClient
from src.generator.generation_worker import GenerationWorker
from src.api.auth import verify_password, create_access_token, get_current_admin, SEEDED_PASSWORD_HASH

logger = logging.getLogger(__name__)

# Initialize Singletons
storage = StorageManager()
initial_cfg = storage.get_config()
llm = MultiProviderLLM(
    gemini_keys=initial_cfg.get("gemini_keys"),
    openrouter_keys=initial_cfg.get("openrouter_keys"),
    groq_keys=initial_cfg.get("groq_keys"),
    gemini_models=initial_cfg.get("gemini_models"),
    gemini_key=initial_cfg.get("gemini_api_key", ""),
    openrouter_key=initial_cfg.get("openrouter_api_key", ""),
    groq_key=initial_cfg.get("groq_api_key", ""),
)
examforge = ExamForgeClient(
    endpoint_url=initial_cfg.get("examforge_url"),
    api_key=initial_cfg.get("examforge_api_key"),
)
worker = GenerationWorker(storage=storage, llm=llm, examforge=examforge)

app = FastAPI(title="ExamForge AI Question Platform", version="2.0.0")

# Mount CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and template paths
UI_DIR = PROJECT_ROOT / "src" / "ui"
STATIC_DIR = UI_DIR / "static"
TEMPLATES_DIR = UI_DIR / "templates"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Request / Response Models ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class ToggleSubjectRequest(BaseModel):
    is_active: bool


class SpeedSubjectRequest(BaseModel):
    speed_seconds: int


class ConfigUpdateRequest(BaseModel):
    examforge_url: Optional[str] = None
    examforge_api_key: Optional[str] = None
    batch_size: Optional[int] = None
    auto_dispatch: Optional[bool] = None
    active_provider: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    gemini_keys: Optional[list[str]] = None
    openrouter_keys: Optional[list[str]] = None
    groq_keys: Optional[list[str]] = None
    gemini_models: Optional[list[str]] = None
    tavily_api_key: Optional[str] = None
    brave_api_key: Optional[str] = None
    exa_api_key: Optional[str] = None
    web_search_enabled: Optional[bool] = None
    smart_search_enabled: Optional[bool] = None


class ParseSyllabusRequest(BaseModel):
    subject_name: Optional[str] = None
    new_subject_name: Optional[str] = None
    exam_code: str = "RRB"
    raw_text: str
    mode: str = "replace"  # "replace" or "update"


class UpdateTreeRequest(BaseModel):
    subject_name: str
    exam_code: str = "RRB"
    parsed_hierarchy: list[dict]


# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def login(data: LoginRequest, response: Response):
    """Authenticate admin user and return JWT."""
    if data.email.strip().lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

    if not verify_password(data.password, SEEDED_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

    token = create_access_token({"sub": ADMIN_EMAIL, "role": "admin"})

    # Set HTTP-only secure cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )

    return {"access_token": token, "token_type": "bearer", "email": ADMIN_EMAIL}


@app.post("/api/auth/logout")
def logout(response: Response):
    """Log out admin and clear session cookie."""
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully."}


@app.get("/api/auth/me")
def get_me(admin: dict = Depends(get_current_admin)):
    return admin


# ── Subjects & Toggles ────────────────────────────────────────────────────────

@app.get("/api/subjects")
def list_subjects(admin: dict = Depends(get_current_admin)):
    """List all subjects with active toggle status and question counts."""
    return storage.get_subjects()


@app.post("/api/subjects/{name}/toggle")
def toggle_subject(name: str, data: ToggleSubjectRequest, admin: dict = Depends(get_current_admin)):
    """Toggle a subject ON or OFF."""
    storage.toggle_subject(name, data.is_active)
    worker.log_event(f"Subject '{name}' set to {'Active' if data.is_active else 'Paused'}.")
    return {"name": name, "is_active": data.is_active}


@app.post("/api/subjects/{name}/speed")
def set_subject_speed(name: str, data: SpeedSubjectRequest, admin: dict = Depends(get_current_admin)):
    """Set API delay speed for a subject."""
    storage.update_subject_speed(name, data.speed_seconds)
    return {"name": name, "speed_delay_seconds": data.speed_seconds}


# ── Worker Controls & Status ──────────────────────────────────────────────────

@app.get("/api/worker/status")
def get_worker_status(admin: dict = Depends(get_current_admin)):
    """Get live generation metrics and activity stream."""
    status_data = worker.get_live_status()
    status_data["provider_status"] = llm.get_status()
    return status_data


@app.post("/api/worker/start")
async def start_worker(admin: dict = Depends(get_current_admin)):
    import asyncio
    worker.start(loop=asyncio.get_running_loop())
    return {"status": "started"}


@app.post("/api/worker/pause")
async def pause_worker(admin: dict = Depends(get_current_admin)):
    worker.pause()
    return {"status": "paused"}


@app.post("/api/worker/resume")
async def resume_worker(admin: dict = Depends(get_current_admin)):
    import asyncio
    worker.resume(loop=asyncio.get_running_loop())
    return {"status": "resumed"}


@app.post("/api/worker/stop")
async def stop_worker(admin: dict = Depends(get_current_admin)):
    worker.stop()
    return {"status": "stopped"}



# ── Configuration & Webhook Settings ──────────────────────────────────────────

@app.get("/api/config")
def get_config(admin: dict = Depends(get_current_admin)):
    return storage.get_config()


@app.post("/api/config")
def update_config(data: ConfigUpdateRequest, admin: dict = Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    storage.update_config(updates)

    # Sync dynamically with in-memory clients (zero restart required!)
    cfg = storage.get_config()
    examforge.endpoint_url = cfg.get("examforge_url", "")
    examforge.api_key = cfg.get("examforge_api_key", "")
    llm.update_pools(
        gemini_keys=cfg.get("gemini_keys"),
        openrouter_keys=cfg.get("openrouter_keys"),
        groq_keys=cfg.get("groq_keys"),
        gemini_models=cfg.get("gemini_models"),
    )
    worker.search_manager.reload_config(cfg)

    worker.log_event("Global configuration and LLM multi-key pools updated successfully.", "success")
    return {"message": "Config updated.", "config": storage.get_config()}


@app.post("/api/config/test-webhook")
def test_webhook(admin: dict = Depends(get_current_admin)):
    """Test connection to the configured ExamForge endpoint."""
    cfg = storage.get_config()
    url = cfg.get("examforge_url", "")
    key = cfg.get("examforge_api_key", "")
    success, message = examforge.test_connection(endpoint_url=url, api_key=key)
    return {"success": success, "message": message, "target_url": url}


# ── Dispatches & Ingestion Audit ──────────────────────────────────────────────

@app.get("/api/dispatches")
def get_dispatches(limit: int = 50, admin: dict = Depends(get_current_admin)):
    return storage.get_dispatches(limit=limit)


@app.post("/api/dispatches/manual")
def manual_dispatch(subject_name: str, count: int = 100, admin: dict = Depends(get_current_admin)):
    """Force dispatch pending questions right now."""
    questions = storage.get_ready_questions(subject_name=subject_name, limit=count)
    if not questions:
        raise HTTPException(status_code=400, detail=f"No questions ready for subject '{subject_name}'.")

    import uuid
    from datetime import datetime, timezone
    batch_num = f"MANUAL-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{subject_name[:3].upper()}"
    cfg = storage.get_config()

    success, status_code, resp = examforge.dispatch_batch(
        questions=questions,
        subject_name=subject_name,
        topic_name="Manual Batch",
        exam_code="RRB",
        endpoint_url=cfg.get("examforge_url"),
        api_key=cfg.get("examforge_api_key"),
    )

    q_ids = [q["id"] for q in questions]
    storage.record_dispatch(
        batch_number=batch_num,
        exam_code="RRB",
        subject_name=subject_name,
        topic_name="Manual Batch",
        question_count=len(questions),
        endpoint_url=cfg.get("examforge_url"),
        status_code=status_code,
        response_payload=resp,
        questions_payload=[examforge.format_question_for_ingest(q) for q in questions],
    )

    if success:
        storage.mark_questions_dispatched(q_ids, batch_num)
        return {"success": True, "batch_number": batch_num, "dispatched_count": len(questions)}
    else:
        raise HTTPException(status_code=502, detail=f"ExamForge dispatch failed ({status_code}): {resp}")


# ── Syllabus Hub & Auto-Parser (Challenge 1) ──────────────────────────────────

@app.get("/api/syllabi")
def list_syllabi(admin: dict = Depends(get_current_admin)):
    return storage.get_all_syllabi()


@app.post("/api/syllabi/parse")
def auto_parse_syllabus(data: ParseSyllabusRequest, admin: dict = Depends(get_current_admin)):
    """Auto-parse raw syllabus text into topics, concepts, and weightages using LLM."""
    target_subject = (data.new_subject_name or data.subject_name or "").strip()
    if not target_subject:
        raise HTTPException(
            status_code=400,
            detail="Please select an existing subject or enter a new subject name."
        )

    # Ensure subject exists in subjects table so it appears in matrix and dropdowns
    storage.create_or_get_subject(target_subject, exam_code=data.exam_code)

    worker.log_event(f"AI Auto-parsing syllabus for '{target_subject}' (Mode: {data.mode.capitalize()})...")

    prompt = f"""
You are an expert curriculum designer. Parse the following syllabus text for:
Subject: {target_subject}
Exam: {data.exam_code}

Raw Syllabus Text:
\"\"\"{data.raw_text[:4000]}\"\"\"

Extract a clean, structured topic hierarchy with target percentage weightages summing to 100%.
Return a JSON array of topics with this exact structure:
[
  {{
    "name": "Topic Name",
    "weightage": 25,
    "concepts": [
      {{
        "name": "Concept / Subtopic Name",
        "description": "Brief description"
      }}
    ]
  }}
]
"""

    parsed = llm.generate_json(prompt, temperature=0.2)
    if not parsed or not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="Failed to parse syllabus with AI. Please check raw text.")

    # Save to storage (supports replace or merge/update mode)
    final_topics = storage.save_syllabus(
        subject_name=target_subject,
        exam_code=data.exam_code,
        raw_text=data.raw_text,
        parsed_hierarchy=parsed,
        mode=data.mode,
    )

    action_text = "merged" if data.mode == "update" else "replaced"
    worker.log_event(f"Syllabus for '{target_subject}' {action_text} with {len(final_topics)} total topics.", "success")
    return {
        "subject_name": target_subject,
        "exam_code": data.exam_code,
        "topics": final_topics,
        "mode": data.mode,
        "is_new_subject": bool(data.new_subject_name and data.new_subject_name.strip()),
    }


@app.post("/api/syllabi/update-tree")
def update_syllabus_tree(data: UpdateTreeRequest, admin: dict = Depends(get_current_admin)):
    """Save user-adjusted topic weights and sub-concepts."""
    existing = storage.get_syllabus(data.subject_name) or {}
    storage.save_syllabus(
        subject_name=data.subject_name,
        exam_code=data.exam_code,
        raw_text=existing.get("raw_text", ""),
        parsed_hierarchy=data.parsed_hierarchy,
    )
    return {"message": "Syllabus topic tree updated successfully."}


# ── UI Root & Health Monitoring Routes (UptimeRobot / Render) ─────────────────

@app.head("/")
def head_index():
    """Handle HEAD requests from UptimeRobot / uptime checkers."""
    return Response(status_code=status.HTTP_200_OK)


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the single-page Admin Dashboard."""
    html_file = TEMPLATES_DIR / "dashboard.html"
    if html_file.exists():
        return FileResponse(str(html_file))
    return HTMLResponse("<h1>ExamForge AI Platform UI Loading...</h1>")


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    """Lightweight health check endpoint for monitoring services like UptimeRobot."""
    return JSONResponse(
        content={"status": "healthy", "service": "ExamForge AI Question Platform"},
        status_code=status.HTTP_200_OK,
    )


@app.api_route("/ping", methods=["GET", "HEAD"])
def ping():
    """Ultra-fast ping endpoint."""
    return Response(content="pong", status_code=status.HTTP_200_OK)


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=port, reload=False)

