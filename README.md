# mequizme

A local study tutor for certifications: flashcards, quizzes, timed exams, answer review,
topic analytics, and (optionally) LLM-generated explanations and new questions.

Status: **Phase 1 – content format + importers.** See the full plan in `docs/plan.md`.

## Study Pack format (v2)

All content lives as JSON files in `content/`, one file per pack (a deck or a quiz bank).
Flashcards and quiz questions are both *items*, so one format serves this app and the
StudyDeck Android app (whose deck JSON is v1).

- Models (source of truth): `backend/app/core/schema.py`
- Generated JSON Schema: `schema/studypack.v2.schema.json`
- Item types: `flashcard`, `cloze`, `mcq_single`, `mcq_multi`, `true_false`, `short_answer`
- Each item can carry `explanation`, per-choice `choiceRationales`, `topics` (ids from the
  pack's `taxonomy`, with exam weights), `tags`, `difficulty`, `resources` (links), `media`,
  and `status` (`draft` for unreviewed/LLM-generated content).
- Ids are stable UUIDs, so items keep their identity across edits and re-imports.
- Unknown fields are preserved on round-trip, so the format can evolve additively.
- Personal progress (SRS state, review history) is never stored in a pack.

## Commands

```sh
cd backend
uv sync
uv run pytest                                   # tests
uv run studypack validate ../content            # validate packs
uv run studypack schema                         # regenerate schema after model changes
uv run studypack convert-md quiz.md --out ../content/x/quiz.json
uv run studypack convert-studydeck deck.json --out ../content/x/deck.json

# re-import the original quizzes and StudyDeck decks (from the repo root)
uv run --project backend python scripts/import_existing.py \
  --quizzes ../ml_associate_exam --decks ../../note_card_app/note_card_app/flashcards
```

## Interop

| Source | Import | Export |
|---|---|---|
| Markdown quizzes (Aiken-like) | ✅ | planned |
| StudyDeck v1 JSON | ✅ (SM-2 state split out as progress) | ✅ |
| Anki `.apkg`, CSV/TSV, Aiken, GIFT | planned (Phase 5) | planned |
| QTI | — | later |
