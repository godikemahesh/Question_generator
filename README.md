# AI DSC Question Generation & Mock Test Platform

Automated question content vendor platform for **DSC (District Selection Committee) Mock Tests**.

Produces large volumes of high-quality, balanced multiple-choice questions (MCQs) following an official syllabus and test blueprint, with multi-stage validation, duplicate detection, answer-position balancing, and CSV exports (separated per subject).

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API Key
Open `.env` and enter your Google Gemini API key:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

### 3. Add Syllabus Text Files
Extract text from your syllabus PDFs and save each subject as a `.txt` file inside the `syllabus/` folder:
```
syllabus/
├── Mathematics.txt
├── General_Science.txt
├── Social_Studies.txt
├── English_Language.txt
└── ...
```

---

## 🛠️ CLI Commands

### 1. Parse Syllabus Text Files
Extracts topics, subtopics, and individual concepts into a structured hierarchy:
```bash
python main.py parse-syllabus
```

### 2. Generate Questions
Generates candidate questions continuously with pauses to stay within API rate limits:
```bash
# Generate 120 questions for all subjects (with 30s pause between batches)
python main.py generate --count 120

# Generate for a specific subject
python main.py generate --subject Mathematics --count 120

# Custom pause between batches (e.g. 45 seconds)
python main.py generate --subject Mathematics --count 120 --pause 45
```

### 3. Check Question Bank Status
View live inventory of approved, used, rejected, and revision questions:
```bash
python main.py status
```

### 4. Assemble a Balanced Mock Test
Assembles an alternate-day mock test (default 120 questions) with balanced topic distribution, balanced difficulty, and balanced answer positions (A ≈ 25%, B ≈ 25%, C ≈ 25%, D ≈ 25%):
```bash
python main.py assemble-test --subject Mathematics --count 120
```

### 5. Export Question Bank to CSV
Exports approved questions to **separate CSV files per subject** in the format `question_text, correct_answer, explanation`:
```bash
# Export all subjects (each into its own CSV)
python main.py export

# Export a specific subject
python main.py export --subject Mathematics
```

### 6. Full End-to-End Run
Executes syllabus parsing, question generation, validation, test assembly, and CSV exports in a single command:
```bash
python main.py full-run --count 120
```

---

## 📁 Output CSV Format

The output CSV strictly follows your required format:
| question_text | correct_answer | explanation |
|---|---|---|
| If 3x + 5 = 20, what is the value of x? | 5 | Subtracting 5 from both sides gives 3x = 15, then dividing by 3 yields x = 5. |

---

## ⚙️ Architecture & Pipeline

```
Syllabus .txt File
      ↓
Syllabus Parser (Hierarchical JSON)
      ↓
Blueprint Engine (Quota Distribution)
      ↓
AI Generator (Gemini Flash + Continuous Pausing)
      ↓
Multi-Stage Validation Pipeline:
   ├─ 1. Schema Validator (Deterministic)
   ├─ 2. Syllabus Validator (Topic Alignment)
   ├─ 3. Answer Validator (SymPy Math Solver / LLM)
   ├─ 4. Distractor Validator (Plausibility / Quality)
   ├─ 5. Duplicate Detector (Level 1: Exact Hash, Level 2: TF-IDF, Level 3: Pattern)
   └─ 6. Quality Scorer (Weighted multi-dimension score)
      ↓
Question Bank (JSON Files organized by Subject & Status)
      ↓
Test Assembly Engine (Answer Position & Topic Balancing)
      ↓
Subject-wise CSV Files in output/
```
