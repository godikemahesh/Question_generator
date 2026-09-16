import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.generator.gemini_client import GeminiClient
from src.generator.generator import QuestionGenerator
from src.question_bank.models import GenerationJob
from src.validators.pipeline import ValidationPipeline

def test_generation():
    client = GeminiClient()
    generator = QuestionGenerator(client=client)
    pipeline = ValidationPipeline(client=client)

    # Test an analytical job (Assertion-Reason / Statement evaluation)
    job = GenerationJob(
        subject="Science",
        topic="Living World",
        subtopic="Plant Life and Photosynthesis",
        difficulty="medium",
        question_type="analytical",
        num_questions=2
    )

    print("Generating 2 analytical questions for Science...")
    questions = generator.generate_batch(job)
    print(f"Generated {len(questions)} questions.")

    for i, q in enumerate(questions, 1):
        print(f"\n--- Question {i} ---")
        print(f"Text:\n{q.question_text}")
        print(f"A: {q.option_a}")
        print(f"B: {q.option_b}")
        print(f"C: {q.option_c}")
        print(f"D: {q.option_d}")
        print(f"Correct: {q.correct_option}")
        print(f"Explanation:\n{q.explanation}")
        
        # Validate
        res = pipeline.validate_single(q)
        print(f"Validation Status: {q.status} (Quality Score: {q.quality_score})")
        for vr in q.validation_results:
            if vr.warnings:
                print(f"  [{vr.validator_name} warnings]: {vr.warnings}")
            if vr.errors:
                print(f"  [{vr.validator_name} errors]: {vr.errors}")

if __name__ == "__main__":
    test_generation()
