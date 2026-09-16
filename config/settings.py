"""
Global settings for the Question Generation Platform.
Loads configuration from .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths ────────────────────────────────────────────────────────────────
SYLLABUS_DIR = PROJECT_ROOT / "syllabus"
PARSED_SYLLABUS_DIR = PROJECT_ROOT / "config" / "parsed_syllabus"
BLUEPRINTS_DIR = PROJECT_ROOT / "config" / "blueprints"
TEMPLATES_DIR = PROJECT_ROOT / "config" / "templates"
QUESTION_BANK_DIR = PROJECT_ROOT / "question_bank"
OUTPUT_DIR = PROJECT_ROOT / "output"
TESTS_OUTPUT_DIR = OUTPUT_DIR / "tests"
DUMPS_OUTPUT_DIR = OUTPUT_DIR / "question_dumps"
LOGS_DIR = PROJECT_ROOT / "logs"

# Create directories
for d in [SYLLABUS_DIR, PARSED_SYLLABUS_DIR, BLUEPRINTS_DIR, TEMPLATES_DIR,
          QUESTION_BANK_DIR, OUTPUT_DIR, TESTS_OUTPUT_DIR, DUMPS_OUTPUT_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Gemini API ───────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── Generation Settings ─────────────────────────────────────────────────
GENERATION_BATCH_SIZE = int(os.getenv("GENERATION_BATCH_SIZE", "8"))
PAUSE_BETWEEN_BATCHES_SECONDS = int(os.getenv("PAUSE_BETWEEN_BATCHES_SECONDS", "30"))
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "15"))

# ── Quality Thresholds ──────────────────────────────────────────────────
QUALITY_APPROVE_THRESHOLD = int(os.getenv("QUALITY_APPROVE_THRESHOLD", "90"))
QUALITY_MONITOR_THRESHOLD = int(os.getenv("QUALITY_MONITOR_THRESHOLD", "80"))
QUALITY_REVISION_THRESHOLD = int(os.getenv("QUALITY_REVISION_THRESHOLD", "70"))

# ── Duplicate Detection ─────────────────────────────────────────────────
DUPLICATE_EXACT_REJECT = os.getenv("DUPLICATE_EXACT_REJECT", "true").lower() == "true"
DUPLICATE_SEMANTIC_THRESHOLD = float(os.getenv("DUPLICATE_SEMANTIC_THRESHOLD", "0.90"))
DUPLICATE_SEMANTIC_REVIEW_THRESHOLD = float(os.getenv("DUPLICATE_SEMANTIC_REVIEW_THRESHOLD", "0.85"))

# ── Test Assembly ────────────────────────────────────────────────────────
MAX_QUESTION_REUSE_DAYS = int(os.getenv("MAX_QUESTION_REUSE_DAYS", "60"))
MAX_SAME_CONCEPT_PER_TEST = int(os.getenv("MAX_SAME_CONCEPT_PER_TEST", "3"))
ANSWER_BALANCE_TOLERANCE = float(os.getenv("ANSWER_BALANCE_TOLERANCE", "0.05"))

# ── Difficulty Distribution Defaults ─────────────────────────────────────
DEFAULT_DIFFICULTY_DISTRIBUTION = {
    "easy": 0.20,
    "medium": 0.60,
    "hard": 0.20,
}

# ── Question Type Distribution Defaults ──────────────────────────────────
DEFAULT_QUESTION_TYPE_DISTRIBUTION = {
    "analytical": 0.30,
    "application": 0.30,
    "problem_solving": 0.20,
    "conceptual": 0.20,
}

# ── Multi-Provider LLM Settings (Inference Cascade: Gemini → OpenRouter → Groq)
# 1st Priority: Google Gemini
# 2nd Priority: OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

# 3rd Priority: Groq (Ultra-fast Llama 3.3 70B fallback)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Free Web Search Providers Cascade (Tavily → Brave → Exa) ─────────────
# 1. Tavily: 1,000 free credits/month
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
# 2. Brave: $5/month free tier (~1,000 basic searches)
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
# 3. Exa: $10/month free allowance (~1,428 basic searches)
EXA_API_KEY = os.getenv("EXA_API_KEY", "")
# Combined free web search capacity: ~3,428 searches/month
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"

# ── Supabase Cloud Storage ───────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── ExamForge Ingestion Webhook Settings ─────────────────────────────────
EXAMFORGE_API_URL = os.getenv(
    "EXAMFORGE_API_URL",
    "https://examforge-pink.vercel.app/api/questions/ai-ingest"
)
EXAMFORGE_LOCAL_URL = os.getenv(
    "EXAMFORGE_LOCAL_URL",
    "http://localhost:3000/api/questions/ai-ingest"
)
EXAMFORGE_API_KEY = os.getenv(
    "EXAMFORGE_API_KEY",
    "ef_ai_ingest_9a7d3f28e6c41b80d52a7e9140f"
)
EXAMFORGE_BATCH_SIZE = int(os.getenv("EXAMFORGE_BATCH_SIZE", "100"))

# ── Admin Authentication ────────────────────────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "examforge_jwt_super_secret_key_2026_x89a")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "maheshgodike17@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Maheshg17#")
