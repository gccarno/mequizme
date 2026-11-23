# mequizme: Study Tutor Web App Plan

## Context
You want a local web app that works as a full study tutor for certifications: flashcards, quizzes, timed exams, reviewing answers, per-topic weakness analysis, resource links when you get something wrong, and LLM help as an optional extra. The starting content is:
- `../ml_associate_exam/*.md`: 5 Databricks ML Associate quiz files. They are markdown with numbered questions and options A–D. Answer keys come in two styles: `## Answer Key` + `1. B`, and `# Answers` + `1B, 2C, …`. None of them have explanations, topics or resources.
- `C:\Users\gccar\Documents\note_card_app\note_card_app`: StudyDeck, an Android app (Kotlin, Room/SQLite, Firestore sync, SM-2). Its JSON format v1 is `{formatVersion, name, description, cards:[{question, answer, createdAt, sm2EasinessFactor, sm2Repetitions, sm2IntervalDays, topic}]}` (`app/src/main/kotlin/com/studydeck/app/data/util/JsonExporter.kt`). It has 4 AWS DVA-C02 decks in `flashcards/`.

Decisions so far: Python (FastAPI) + React/TS. The LLM is an optional feature (Claude API). StudyDeck migration is designed now and built later.

## Public format landscape → decision
- **Flashcards:** there is no open standard. The de facto sharing format is **Anki `.apkg`**: a zip holding a SQLite db and media, with a huge shared library on AnkiWeb. The common lowest denominators are CSV/TSV (Quizlet, Anki text export) and CrowdAnki JSON.
- **Quizzes:** **QTI 2.x/3.0** (1EdTech) is the formal standard. It's heavy XML used by Canvas, Moodle and Blackboard. **GIFT** (Moodle) and **Aiken** are simple text formats, and your markdown is almost Aiken already.
- **Decision:** we define one canonical, versioned JSON format, the **Study Pack format**, with a JSON Schema. Flashcards and quiz questions are both *items*, so a single format covers both apps. Interop comes through adapters: import Anki `.apkg`, CSV/TSV, Aiken, GIFT, StudyDeck v1 and the existing markdown; export CSV, Aiken/GIFT and (later) QTI and `.apkg`. We don't adopt Anki's internal schema as the canonical format because it's note-type/template based, awkward for MCQ and exam metadata, and tied to Anki's own scheduling.

## Study Pack format (v2, continuing StudyDeck's v1 numbering)
One JSON file per pack (deck or quiz bank). Every object has a stable `id` (ULID/UUID) so the apps can sync and merge. Unknown fields must be preserved, not just ignored, so the format can evolve.
```json
{
  "format": "studypack", "formatVersion": 2,
  "id": "01J…", "name": "Databricks ML Associate – Section 1", "description": "…",
  "source": {"kind": "authored|llm|import", "ref": "section1_quiz1.md"},
  "taxonomy": {"exam": "databricks-ml-associate",
               "topics": [{"id": "db-ml", "name": "Databricks ML", "weight": 0.38}]},
  "items": [{
    "id": "01J…", "type": "mcq_single",          // flashcard | cloze | mcq_single | mcq_multi | true_false | short_answer
    "prompt": "markdown…", "media": [],
    "choices": [{"id": "A", "text": "…"}],        // mcq only
    "answer": {"choiceIds": ["B"]},               // flashcard: {"text": "markdown"}
    "explanation": "markdown – why B is right",
    "choiceRationales": {"A": "why A is wrong"},
    "topics": ["db-ml"], "tags": ["mlflow"], "difficulty": 2,
    "resources": [{"title": "MLflow docs", "url": "…"}],
    "status": "reviewed|draft", "createdAt": "ISO-8601", "updatedAt": "…"
  }],
  "quizzes": [{"id": "…", "name": "Mixed practice exam", "itemIds": ["…"], "timeLimitSec": 2400, "shuffle": true}]
}
```
- The schema lives at `schema/studypack.v2.schema.json`. Validation runs on import and in tests.
- The StudyDeck v1 → v2 mapping is lossless: `question→prompt`, `answer→answer.text`, `type: flashcard`, `topic→topics[]`. SM-2 fields move into **progress**, not content (see below).
- **Progress is separate from content.** Scheduling state and the review log go in a separate `progress` export, so shared packs carry no personal data.

## Storage
**Hybrid: JSON files as the content source of truth, SQLite for runtime and progress.**
- Pack files live in `content/` (git-friendly, LLM-generatable, shareable). The server ingests them into SQLite and upserts by `id`.
- In SQLite, `packs` and `items` tables keep queryable columns (id, pack_id, type, topics) plus a `body JSON` column holding the full document. That gives NoSQL-style flexibility through SQLite's JSON1 functions, and relational queries for analytics.
- Progress tables: `attempts` (quiz session), `responses` (item, choice, correct, time_ms, confidence), `reviews` (append-only flashcard review log), `srs_state` (per item).
- Why not a pure NoSQL store: per-topic accuracy, trend and weak-area queries are relational by nature, and SQLite needs no setup. The document shape still maps 1:1 onto Firestore, which StudyDeck already uses, for future sync.

## Spaced repetition
Use **FSRS** (the `fsrs` Python package; Anki's default since 23.10) behind a `Scheduler` interface, with SM-2 as a fallback so imported StudyDeck state keeps working. Because the review log is append-only, the scheduler can be swapped or re-fit later. Quiz misses also feed SRS, so wrong MCQs come back for review.

## Architecture
```
mequizme/
  backend/  (FastAPI, uv, SQLModel/SQLAlchemy, pydantic models generated from/validated against schema)
    app/main.py, api/{packs,items,study,quiz,stats,import_export,tutor}.py
    app/core/{schema.py, scheduler.py (fsrs+sm2), grading.py, ingest.py}
    app/adapters/{markdown_quiz.py, studydeck_v1.py, anki_apkg.py, csv_tsv.py, aiken.py, gift.py, qti.py}
    app/llm/{client.py, prompts.py}   # optional; enabled when ANTHROPIC_API_KEY set
    tests/
  frontend/ (Vite + React + TS, TanStack Query, Tailwind; types generated from JSON Schema)
    pages: Library, PackDetail, Flashcards, QuizRunner (practice/timed exam), AttemptReview, Topics/Dashboard, Editor
  content/  (study pack JSON files)
  schema/studypack.v2.schema.json
  scripts/  (CLI: import/convert/validate packs)
```
Run locally with `uv run fastapi dev` + `npm run dev`, or a single `make dev`. In production mode FastAPI serves the built frontend, so it runs as one process.

## Features by phase
**Phase 1: Format + import (foundation)**
- JSON Schema, pydantic models, `ingest.py` and a validation CLI.
- Adapters: the existing markdown quizzes (handles both answer-key styles and question-count/key mismatch warnings) and StudyDeck v1 JSON.
- Convert the 5 ml_associate quizzes and 4 DVA-C02 decks into `content/` and check them in.

**Phase 2: Core study loop**
- Library → pick a pack, topics or tags.
- **Flashcards:** flip, rate Again/Hard/Good/Easy, FSRS due queue, keyboard shortcuts.
- **Quiz, practice mode:** feedback after each question, with explanation, choice rationales and resources shown on a miss.
- **Quiz, exam mode:** timed with a countdown and auto-submit, flag-for-review, a navigator grid, no feedback until the end, and a section-weighted random draw from the taxonomy.
- **Attempt review:** every question shows your answer, the correct one, the explanation and resources, plus filters for wrong only and flagged. There's a retake-wrong-answers option.

**Phase 3: Tutor analytics**
- Per-topic accuracy, trend over attempts, and weighted exam-readiness score.
- Weak-topic drill: auto-build a quiz from the lowest-mastery topics and SRS-due misses.
- Confidence rating per answer, used to catch "lucky guesses" and "confidently wrong" answers.
- A "Resources to review" list compiled from your misses.

**Phase 4: Optional LLM features (Claude API; default `claude-sonnet-5-5`, configurable)**
- Enrich: generate explanations, per-choice rationales, topic tags and official-doc links for items that lack them. This is the main fill-in for the current quizzes. Results are saved as `status: draft` with a review/accept UI.
- Explain my mistake: a contextual "why was my answer wrong" on any missed item.
- Generate: create new items or quizzes for a topic and exam blueprint, as drafts. There's dedupe against existing items.
- Tutor chat scoped to an item or topic.

**Phase 5: Interop + authoring**
- Item editor in the UI.
- Import Anki `.apkg` (read the SQLite inside the zip: notes and fields, Basic and Cloze, media), plus CSV/TSV, Aiken and GIFT.
- Export to CSV/Aiken/GIFT and `.apkg` (via `genanki`); QTI later if needed.

**Phase 6 (later): StudyDeck migration**
- Update `JsonImporter.kt`/`JsonExporter.kt` to read v1 and v2 and write v2 (cards as `flashcard` items; ignore other item types or show them as cards).
- Optional progress sync via the shared `progress` export or Firestore.

## Verification
- `pytest`: schema validation of every file in `content/`; adapter round-trips (markdown → pack → same answers; StudyDeck v1 → v2 → v1 lossless); FSRS/SM-2 scheduler tests (port the cases from `Sm2AlgorithmTest.kt`); grading for single and multi choice; exam timer auto-submit on the server side.
- Golden checks: section1 has 10 items with keys B, D, A, B, C, D, D, A, C, B, and more_quizes has 20 items with keys 1B…20B.
- Vitest for frontend components, plus a Playwright smoke test: import pack → run timed quiz → submit → review screen shows the explanation for a wrong answer → dashboard topic accuracy updates.
- Manual: `make dev`, then take a real timed Section 1 exam in the browser.
