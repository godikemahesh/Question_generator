"""
Structured prompts for Gemini API.
All prompts enforce strict JSON output for reliable parsing.
"""

QUESTION_GENERATION_PROMPT = """You are a master question paper setter for the DSC (District Selection Committee) competitive exam in India.

Generate exactly {num_questions} high-caliber multiple-choice questions (MCQs) designed for serious DSC aspirants.

Subject: {subject}
Topic: {topic}
Subtopic: {subtopic}
Difficulty: {difficulty}
Question Type: {question_type}

{template_instruction}

Reference syllabus context:
---
{reference_context}
---

CRITICAL DSC EXAM QUALITY STANDARDS (TARGET: 9.5+/10 RATING):

1. QUESTION ARCHETYPES & COGNITIVE DEPTH:
   - For 'analytical' questions: Favor Assertion-Reason (A & R), Statement I & Statement II evaluation, or Multi-statement selection ("Which of the statements given above are correct? 1 and 2 only, etc.").
   - For 'application' / 'analytical' questions: Systematically link two related principles or processes (multi-concept synthesis) rather than isolated one-line textbook recall.
   - For 'problem_solving' questions: Require genuine multi-step conceptual calculation or quantitative relationship analysis.

2. STRICT DISTRACTOR PARALLELISM & NO WORDING GIVEAWAYS:
   - ALL 4 OPTIONS (A, B, C, D) MUST BE OF COMPARABLE LENGTH AND TECHNICAL DETAIL (within ±20% word length).
   - The correct option MUST NOT stand out by being significantly longer, more carefully qualified, or syntactically distinct.
   - Distractors must be smart, highly plausible cognitive traps based on real candidate misconceptions, common calculation slips, or related terms.
   - Do NOT use "All of the above" or "None of the above".

3. EXPLANATION (CONCISE & SINGLE LINE):
   - Provide a concise, single-line explanation (1-2 sentences maximum) explaining strictly why the correct answer is correct.
   - Keep it on a single line — do NOT include line breaks, bullet points, or explanations of why other options are wrong.

4. RIGOR & ACCURACY:
   - Exactly ONE option must be indisputably correct.
   - Vary the correct answer position across A, B, C, and D evenly.

Return a JSON array with this EXACT structure:
[
  {{
    "question_text": "The complete question text (including Statements or Assertion/Reason if applicable)",
    "option_a": "Option A text",
    "option_b": "Option B text",
    "option_c": "Option C text",
    "option_d": "Option D text",
    "correct_option": "A",
    "explanation": "Concise single-line explanation of why the correct answer is right.",
    "difficulty": "{difficulty}",
    "question_type": "{question_type}"
  }}
]

Generate exactly {num_questions} questions. Return ONLY valid JSON array.
"""


ANSWER_VERIFICATION_PROMPT = """You are a subject matter expert verifying MCQ answers.

Subject: {subject}
Topic: {topic}

Question: {question_text}

A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}

Stated correct answer: {correct_option}

Tasks:
1. Solve this question independently step by step
2. Determine the correct answer
3. Compare with the stated answer
4. Check if any other option could also be correct

Return JSON:
{{
  "your_answer": "A/B/C/D",
  "reasoning": "Step-by-step reasoning",
  "agrees_with_stated": true/false,
  "multiple_correct": false,
  "issues": []
}}

Return ONLY valid JSON.
"""


QUALITY_REVIEW_PROMPT = """You are a quality reviewer for DSC exam MCQs.

Subject: {subject}
Topic: {topic}

Question: {question_text}

A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}

Correct: {correct_option}
Explanation: {explanation}

Rate this question on each dimension (0-100):

1. correctness: Is the stated answer definitely correct?
2. clarity: Is the question clear and unambiguous?
3. syllabus_alignment: Is this appropriate for DSC exam level on this topic?
4. distractor_quality: Are the wrong options plausible and well-crafted?
5. difficulty_accuracy: Does the actual difficulty match "{difficulty}"?
6. originality: Is this question creative/unique (not a textbook copy)?

Return JSON:
{{
  "correctness": 0-100,
  "clarity": 0-100,
  "syllabus_alignment": 0-100,
  "distractor_quality": 0-100,
  "difficulty_accuracy": 0-100,
  "originality": 0-100,
  "issues": ["list of any issues found"],
  "suggestions": ["list of improvement suggestions"]
}}

Return ONLY valid JSON.
"""


DUPLICATE_CHECK_PROMPT = """You are checking if two MCQs are duplicates or test the same concept in the same way.

Question A:
{question_a}

Question B:
{question_b}

Return JSON:
{{
  "is_duplicate": true/false,
  "similarity_type": "exact/semantic/pattern/none",
  "reasoning": "Brief explanation"
}}

Return ONLY valid JSON.
"""
