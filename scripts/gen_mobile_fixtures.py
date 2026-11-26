"""Golden test vectors so StudyDeck's Kotlin ports provably match the web app.

Run from the repo root (re-run after upgrading `fsrs` or changing grading):
    uv run --project backend python scripts/gen_mobile_fixtures.py

Writes fixtures/fsrs_golden.json and fixtures/grading_cases.json. Copy both into StudyDeck's
app/src/test/resources/ (its tests read them from there).
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fsrs

from app.core.grading import grade

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures"
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

# (rating, seconds after the previous review). Hand-picked paths through every state transition,
# then random ones. Gaps mix "same session" (< 1 day: short-term stability) and late reviews.
HAND = [
    [(3, 0), (3, 60), (3, 600), (3, 86400 * 3), (3, 86400 * 9)],          # learn -> review, steady
    [(4, 0), (4, 86400 * 8), (4, 86400 * 40)],                             # easy all the way
    [(1, 0), (1, 60), (2, 60), (3, 360), (3, 600), (1, 86400 * 2)],        # struggle, lapse
    [(3, 0), (3, 600), (3, 86400 * 2), (1, 86400 * 5), (3, 600), (2, 86400)],  # relearning path
    [(2, 0), (2, 400), (2, 600), (2, 86400 * 4)],                          # hard on step 0 / later steps
    [(3, 0), (3, 600), (3, 86400 * 400), (3, 86400 * 4000)],               # very late, interval cap
    [(3, 0), (3, 600), (3, 3600 * 23 + 3599)],                             # just under a day
]


def sequences() -> list[list[tuple[int, int]]]:
    rng = random.Random(20261126)
    gaps = [0, 30, 60, 600, 3600, 86400 - 1, 86400, 86400 * 3, 86400 * 12, 86400 * 45]
    out = list(HAND)
    for _ in range(40):
        out.append([(rng.randint(1, 4), 0 if i == 0 else rng.choice(gaps)) for i in range(rng.randint(2, 12))])
    return out


def fsrs_golden() -> dict:
    sched = fsrs.Scheduler(enable_fuzzing=False)
    cases = []
    for seq in sequences():
        card = fsrs.Card(card_id=1, due=T0)
        now = T0
        steps = []
        for rating, gap in seq:
            now += timedelta(seconds=gap)
            card, _ = sched.review_card(card, fsrs.Rating(rating), review_datetime=now)
            steps.append({"rating": rating, "reviewedAt": now.isoformat(), "card": card.to_dict()})
        cases.append({"start": fsrs.Card(card_id=1, due=T0).to_dict(), "steps": steps})
    return {
        "fsrsVersion": fsrs.__version__ if hasattr(fsrs, "__version__") else "6.x",
        "scheduler": sched.to_dict(),
        "cases": cases,
    }


def item(kind: str, answer: dict) -> dict:
    return {"id": "x", "type": kind, "prompt": "?", "answer": answer}


def grading_cases() -> list[dict]:
    single = item("mcq_single", {"choiceIds": ["B"]})
    multi = item("mcq_multi", {"choiceIds": ["A", "C"]})
    tf = item("true_false", {"choiceIds": ["true"]})
    short = item("short_answer", {"text": "Delta Lake", "accepted": ["delta", "Delta tables."]})
    card = item("flashcard", {"text": "anything"})
    raw = [
        (single, ["B"], None), (single, ["A"], None), (single, [], None), (single, None, None),
        (single, ["B", "A"], None),
        (multi, ["A", "C"], None), (multi, ["C", "A"], None), (multi, ["A"], None), (multi, ["A", "B", "C"], None),
        (multi, ["A", "A", "C"], None),
        (tf, ["true"], None), (tf, ["false"], None),
        (short, None, "delta lake"), (short, None, "  Delta   Lake. "), (short, None, "DELTA"),
        (short, None, "delta tables"), (short, None, "lakehouse"), (short, None, ""), (short, None, None),
        (card, None, None), (card, None, "anything"),
    ]
    return [{"item": i, "choiceIds": c, "text": t, "expected": grade(i, c, t)} for i, c, t in raw]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "fsrs_golden.json").write_text(json.dumps(fsrs_golden(), indent=1) + "\n", encoding="utf-8")
    (OUT / "grading_cases.json").write_text(json.dumps(grading_cases(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'fsrs_golden.json'} and {OUT / 'grading_cases.json'}")


if __name__ == "__main__":
    main()
