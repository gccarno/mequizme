"""SQLite storage. Content is ingested from pack files (body JSON = full document);
progress (attempts, responses, reviews, SRS state) only lives here."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exam TEXT,
    path TEXT NOT NULL,
    body TEXT NOT NULL,             -- full pack JSON minus items
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    topics TEXT NOT NULL,           -- JSON array of topic ids
    body TEXT NOT NULL              -- full item JSON
);
CREATE INDEX IF NOT EXISTS items_pack ON items(pack_id, position);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('practice', 'exam')),
    pack_id TEXT,
    quiz_id TEXT,
    exam TEXT,
    item_ids TEXT NOT NULL,         -- JSON array, presentation order
    started_at TEXT NOT NULL,
    deadline_at TEXT,
    submitted_at TEXT,
    score INTEGER,
    total INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS responses (
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    choice_ids TEXT,                -- JSON array
    text TEXT,
    correct INTEGER,
    flagged INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER,             -- 1 guess .. 3 sure
    time_ms INTEGER,
    answered_at TEXT,
    PRIMARY KEY (attempt_id, item_id)
);
CREATE TABLE IF NOT EXISTS reviews (            -- append-only log, lets us re-fit/swap schedulers
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    rating INTEGER NOT NULL,        -- 1 Again, 2 Hard, 3 Good, 4 Easy
    source TEXT NOT NULL,           -- flashcard | quiz
    reviewed_at TEXT NOT NULL,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS reviews_item ON reviews(item_id, reviewed_at);
CREATE TABLE IF NOT EXISTS srs_state (
    item_id TEXT PRIMARY KEY,
    scheduler TEXT NOT NULL,        -- fsrs | sm2
    state TEXT NOT NULL,            -- scheduler-specific JSON
    due TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS srs_due ON srs_state(due);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # One connection per request. FastAPI may open it (dependency) and use it (endpoint) on
        # different threadpool threads, but never concurrently, so the thread check is safe to drop.
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
