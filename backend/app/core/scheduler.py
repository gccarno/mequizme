"""Spaced-repetition schedulers behind one interface.

FSRS (the `fsrs` package, Anki's default) is used for new cards. SM-2 is kept so state
imported from StudyDeck keeps working; such cards stay on SM-2 unless reset.
Ratings use the FSRS scale: 1 Again, 2 Hard, 3 Good, 4 Easy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import fsrs


@dataclass
class Scheduled:
    state: dict
    due: datetime


class Scheduler(Protocol):
    name: str

    def new(self, now: datetime) -> Scheduled: ...
    def review(self, state: dict, rating: int, now: datetime) -> Scheduled: ...


class FsrsScheduler:
    name = "fsrs"

    def __init__(self, desired_retention: float = 0.9, fuzz: bool = True):
        self._s = fsrs.Scheduler(desired_retention=desired_retention, enable_fuzzing=fuzz)

    def new(self, now: datetime) -> Scheduled:
        card = fsrs.Card(due=now)
        return Scheduled(card.to_dict(), now)

    def review(self, state: dict, rating: int, now: datetime) -> Scheduled:
        card = fsrs.Card.from_dict(state)
        card, _ = self._s.review_card(card, fsrs.Rating(rating), review_datetime=now)
        return Scheduled(card.to_dict(), card.due)


class Sm2Scheduler:
    """Port of StudyDeck's Sm2Algorithm.kt. Maps FSRS ratings onto SM-2 scores 1-5."""

    name = "sm2"
    RATING_TO_SCORE = {1: 1, 2: 3, 3: 4, 4: 5}

    def new(self, now: datetime) -> Scheduled:
        return Scheduled({"ef": 2.5, "reps": 0, "interval": 1}, now)

    @staticmethod
    def step(score: int, ef: float, reps: int, interval: int) -> tuple[float, int, int]:
        if not 1 <= score <= 5:
            raise ValueError("score must be 1..5")
        if score < 3:
            reps, interval = 0, 1
        else:
            interval = 1 if reps == 0 else 6 if reps == 1 else round(interval * ef)
            reps += 1
        ef = max(1.3, ef + 0.1 - (5 - score) * (0.08 + (5 - score) * 0.02))
        return ef, reps, interval

    def review(self, state: dict, rating: int, now: datetime) -> Scheduled:
        ef, reps, interval = self.step(self.RATING_TO_SCORE[rating], state["ef"], state["reps"], state["interval"])
        return Scheduled({"ef": ef, "reps": reps, "interval": interval}, now + timedelta(days=interval))


SCHEDULERS: dict[str, Scheduler] = {"fsrs": FsrsScheduler(), "sm2": Sm2Scheduler()}
DEFAULT = "fsrs"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def record_review(conn, item_id: str, rating: int, source: str, now: datetime | None = None,
                  duration_ms: int | None = None) -> Scheduled:
    """Append to the review log and advance the item's SRS state."""
    now = now or now_utc()
    row = conn.execute("SELECT scheduler, state FROM srs_state WHERE item_id = ?", (item_id,)).fetchone()
    if row:
        sched = SCHEDULERS[row["scheduler"]]
        state = json.loads(row["state"])
    else:
        sched = SCHEDULERS[DEFAULT]
        state = sched.new(now).state
    result = sched.review(state, rating, now)
    conn.execute(
        "INSERT INTO reviews (item_id, rating, source, reviewed_at, duration_ms) VALUES (?, ?, ?, ?, ?)",
        (item_id, rating, source, now.isoformat(), duration_ms),
    )
    conn.execute(
        """INSERT INTO srs_state (item_id, scheduler, state, due) VALUES (?, ?, ?, ?)
           ON CONFLICT(item_id) DO UPDATE SET scheduler=excluded.scheduler, state=excluded.state, due=excluded.due""",
        (item_id, sched.name, json.dumps(result.state), result.due.isoformat()),
    )
    return result
