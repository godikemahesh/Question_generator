"""
Comprehensive Integration Tests for ExamForge AI Platform:
1. Admin Authentication & JWT Verification
2. Multi-Provider Cascade & Status
3. ExamForge Payload Formatting & Connection Test
4. Storage Manager (CRUD, Subject Toggles, Deduplication)
"""
import sys
from pathlib import Path

# Add project root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.api.auth import verify_password, create_access_token, SEEDED_PASSWORD_HASH, ADMIN_EMAIL
from src.database.supabase_client import StorageManager
from src.generator.llm_manager import MultiProviderLLM
from src.export.examforge_client import ExamForgeClient
from src.generator.generation_worker import compute_normalized_hash


def test_auth():
    print("Testing Admin Authentication...")
    assert verify_password("Maheshg17#", SEEDED_PASSWORD_HASH), "Password verification failed"
    assert not verify_password("WrongPassword123", SEEDED_PASSWORD_HASH), "Wrong password accepted"

    token = create_access_token({"sub": ADMIN_EMAIL, "role": "admin"})
    assert isinstance(token, str) and len(token) > 20, "Token creation failed"
    print("  [PASS] Admin Auth & Token issuance passed")


def test_storage_and_dedup():
    print("Testing Storage Manager & Deduplication...")
    storage = StorageManager()

    # Test Subjects
    subjects = storage.get_subjects()
    assert len(subjects) > 0, "No initial subjects loaded"
    subj_name = subjects[0]["name"]

    # Test Toggle
    storage.toggle_subject(subj_name, False)
    s_updated = next(s for s in storage.get_subjects() if s["name"] == subj_name)
    assert not s_updated["is_active"], "Toggle off failed"

    storage.toggle_subject(subj_name, True)
    s_updated2 = next(s for s in storage.get_subjects() if s["name"] == subj_name)
    assert s_updated2["is_active"], "Toggle on failed"

    # Test Deduplication
    q_text = "What is the speed of light in a vacuum?"
    h = compute_normalized_hash(q_text)

    q1 = {
        "subject_name": subj_name,
        "topic_name": "Physics",
        "exam_code": "RRB",
        "question_text": q_text,
        "option_a": "3 x 10^8 m/s",
        "option_b": "3 x 10^6 m/s",
        "option_c": "3 x 10^5 km/s",
        "option_d": "Both A and C",
        "correct_answer": "D",
        "explanation": "3 x 10^8 m/s is equivalent to 3 x 10^5 km/s.",
        "difficulty": "Medium",
        "tags": "physics",
        "normalized_hash": h,
    }

    # First insert should succeed or already exist
    storage.save_question(q1)

    # Second insert with identical hash must be rejected
    is_dup = storage.is_duplicate_hash(h)
    assert is_dup, "Duplicate detector failed to detect existing hash"

    saved_again = storage.save_question(q1)
    assert not saved_again, "Duplicate question was improperly saved!"

    print("  [PASS] Storage CRUD & Hash Deduplication passed")


def test_examforge_formatting():
    print("Testing ExamForge Payload Formatting...")
    client = ExamForgeClient()

    raw_q = {
        "question_text": "What is the capital of India?",
        "option_a": "Mumbai",
        "option_b": "New Delhi",
        "option_c": "Kolkata",
        "option_d": "Chennai",
        "correct_answer": "B",
        "explanation": "New Delhi is the official capital.",
        "difficulty": "easy",
        "tags": "geography",
        "subject_name": "General Knowledge",
        "topic_name": "Indian Polity",
    }

    formatted = client.format_question_for_ingest(raw_q)
    assert formatted["questionText"] == "What is the capital of India?"
    assert formatted["optionB"] == "New Delhi"
    assert formatted["correctAnswer"] == "B"
    assert formatted["difficulty"] == "Easy"
    assert formatted["tags"] == "geography"
    print("  [PASS] ExamForge Schema Formatting passed")


def test_llm_status():
    print("Testing Multi-Provider LLM Status...")
    llm = MultiProviderLLM()
    st = llm.get_status()
    assert "gemini" in st, "Gemini provider missing from status"
    assert "openrouter" in st, "OpenRouter provider missing from status"
    assert "groq" in st, "Groq provider missing from status"
    print(f"  [PASS] Multi-Provider status verified: 1st {st['gemini']['name']}, 2nd {st['openrouter']['name']}, 3rd {st['groq']['name']}")


if __name__ == "__main__":
    print("\n================ STARTING EXAMFORGE PLATFORM TESTS ================")
    test_auth()
    test_storage_and_dedup()
    test_examforge_formatting()
    test_llm_status()
    print("================ ALL INTEGRATION TESTS PASSED! ================\n")
