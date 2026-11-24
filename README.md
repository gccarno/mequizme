# mequizme

A local study tutor for certifications: flashcards, quizzes, timed exams, answer review,
topic analytics, and (optionally) LLM-generated explanations and new questions.

Status: **Phase 4 – AI tutor.** See the full plan in `docs/plan.md`.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node 20+.

```sh
cd frontend && npm install && npm run build      # once, and after frontend changes
cd ../backend && uv run mequizme                  # http://127.0.0.1:8000
```

For development, run the API with reload and the Vite dev server (it proxies `/api`):

```sh
cd backend && uv run mequizme --reload           # terminal 1
cd frontend && npm run dev                       # terminal 2, http://localhost:5173
```

Content is read from `content/` at startup (`MEQUIZME_CONTENT` to override). Your progress lives in
`data/mequizme.db` (`MEQUIZME_DB` to override); it's git-ignored and never written into packs.

## What it does

- **Library**: packs grouped by exam. Start a practice quiz, a timed quiz, flashcards, or a
  **mock exam** that draws questions across packs in proportion to the exam's topic weights.
- **Practice mode**: each answer is checked right away, with the explanation, why each wrong
  choice is wrong, and reading links. Answers lock once checked.
- **Timed mode**: countdown (2 min/question by default), answer sheet navigator, flag for review,
  change answers until you submit. The server enforces the deadline and submits for you at 0:00.
- **Review**: score, time, per-topic breakdown, missed/flagged filters, your answer against the
  correct one, explanations and links, and one-click retake of the missed questions.
- **Spaced repetition**: flashcards use FSRS (Again/Hard/Good/Easy). Quiz answers feed the same
  scheduler, so missed questions come back under "Review missed questions".
- **Confidence**: mark each answer Guessing, Unsure or Sure. Correct guesses earn half credit and
  are scheduled sooner; review filters show "sure but wrong" and "lucky guesses".
- **Progress** (per exam): an estimated exam score weighted by the exam blueprint, against the
  passing line; mastery per topic (recent answers weigh most, only the latest three per question
  count, unknown topics start at 50%); score per quiz over time; how often you're right at each
  confidence level; and a reading list built from the links on questions you've missed.
- **Drills**: one click builds a practice set from your weakest topics (or one topic you pick),
  mixing in questions due for review and favouring ones you missed or haven't seen.
- **AI tutor** (optional, see below): fills in explanations, notes on each wrong choice, doc links
  and topics; checks answer keys; explains a specific mistake; chats about a question or topic; and
  writes new practice questions. Everything it writes is a draft you accept, edit or reject on the
  **AI tutor** page, and learners see which parts haven't been checked.
- Keyboard: A–H or 1–9 to choose, G/U/S for confidence, Enter to check/continue, F to flag,
  arrows to move; Space and 1–4 for flashcards.

## AI tutor

Off unless a model is available. By default the app uses, in order:

1. The Anthropic API, if `ANTHROPIC_API_KEY` is set (`uv sync --extra api`).
2. **Claude Code**, if `claude` is installed and signed in. No API key needed: the server runs
   `claude -p` headless with tools, settings, MCP servers and session history all off, from an
   empty folder, so the model only sees the question. Usage counts against your Claude plan.
   This is meant for you on your own machine; use an API key if other people will use the app.

Settings: `MEQUIZME_LLM` = `auto` | `claude-code` | `api` | `off` | `fake` (canned answers, used
by the e2e tests); `MEQUIZME_LLM_MODEL` (default `sonnet` for Claude Code, `claude-sonnet-5-5` for
the API); `MEQUIZME_LLM_CONCURRENCY` (parallel calls for bulk jobs, default 3);
`MEQUIZME_CHECK_LINKS=0` to skip checking that suggested links exist (the check only fetches
public https hosts, never addresses on your machine or network).

The API only answers requests addressed to this computer (`localhost`, `127.0.0.1`), and refuses
changes sent from other websites. To reach it under another host name, list it in
`MEQUIZME_ALLOWED_HOSTS` (comma-separated).

How drafts work: AI output is written into the pack files in `content/` with a `draft` marker
listing the fields it wrote, what they replaced, and any doubt about the answer key. Accepting
removes the marker; rejecting restores the old values. New questions go to
`content/<exam>/generated.json` with `status: draft` and stay out of quizzes until accepted. The
tutor never changes an answer key; it flags doubts for you. Links that return 404 are dropped.

## Tests

```sh
cd backend && uv run pytest                      # format, adapters, scheduler, grading, analytics, API
cd frontend && npm test                          # unit tests
cd frontend && npm run build && npm run e2e      # Playwright: exam, practice, flashcards, progress, tutor
```

## Study Pack format (v2)

All content lives as JSON files in `content/`, one file per pack (a deck or a quiz bank).
Flashcards and quiz questions are both *items*, so one format serves this app and the
StudyDeck Android app (whose deck JSON is v1).

- Models (source of truth): `backend/app/core/schema.py`
- Generated JSON Schema: `schema/studypack.v2.schema.json`
- Item types: `flashcard`, `cloze`, `mcq_single`, `mcq_multi`, `true_false`, `short_answer`
- Each item can carry `draft` (unreviewed AI-written fields, see above), `explanation`, per-choice `choiceRationales`, `topics` (ids from the
  pack's `taxonomy`, with exam weights), `tags`, `difficulty`, `resources` (links), `media`,
  and `status` (`draft` for unreviewed/LLM-generated content).
- Ids are stable UUIDs, so items keep their identity across edits and re-imports.
- Unknown fields are preserved on round-trip, so the format can evolve additively.
- Personal progress (SRS state, review history) is never stored in a pack.

## Commands

```sh
cd backend
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
