"""Quiz attempts: practice (instant feedback) and exam (timed, feedback after submit)."""

from __future__ import annotations

import json
import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_conn, load_items, topic_names
from app.core.db import dumps
from app.core.grading import grade, is_gradable
from app.core.scheduler import now_utc, record_review

router = APIRouter(prefix="/api/attempts", tags=["quiz"])

SECONDS_PER_QUESTION = 120  # Databricks/AWS associate exams run ~2 min per question
HIDDEN_FIELDS = ("answer", "explanation", "choiceRationales")


class AttemptCreate(BaseModel):
    mode: Literal["practice", "exam"] = "practice"
    packId: str | None = None
    quizId: str | None = None
    exam: str | None = None
    itemIds: list[str] | None = None
    topics: list[str] | None = None
    count: int | None = Field(default=None, ge=1, le=500)
    timeLimitSec: int | None = Field(default=None, ge=30)
    shuffle: bool | None = None
    name: str | None = None
    seed: int | None = None  # deterministic draws for tests


class ResponseIn(BaseModel):
    choiceIds: list[str] | None = None
    text: str | None = None
    flagged: bool | None = None
    confidence: int | None = Field(default=None, ge=1, le=3)
    timeMs: int | None = Field(default=None, ge=0)


# --- selection -----------------------------------------------------------------------------

def _gradable_rows(conn, where: str, args: tuple) -> list[dict]:
    rows = conn.execute(f"SELECT body FROM items WHERE status != 'draft' AND {where} ORDER BY pack_id, position", args)
    return [b for b in (json.loads(r["body"]) for r in rows) if is_gradable(b)]


def weighted_draw(items: list[dict], topics: list[dict], count: int, rng: random.Random) -> list[dict]:
    """Draw `count` items so topic shares follow taxonomy weights (largest remainder).
    Shortfalls in a topic are filled from the remaining pool."""
    count = min(count, len(items))
    by_topic: dict[str, list[dict]] = {t["id"]: [] for t in topics}
    for it in items:
        for t in it.get("topics", []):
            if t in by_topic:
                by_topic[t].append(it)
                break
    weights = {t["id"]: t.get("weight") or 0 for t in topics}
    total_w = sum(weights.values()) or 1
    raw = {t: count * w / total_w for t, w in weights.items()}
    quota = {t: math.floor(v) for t, v in raw.items()}
    for t in sorted(raw, key=lambda t: raw[t] - quota[t], reverse=True)[: count - sum(quota.values())]:
        quota[t] += 1
    picked: list[dict] = []
    taken: set[str] = set()
    for t, pool in by_topic.items():
        for it in rng.sample(pool, min(quota[t], len(pool))):
            picked.append(it)
            taken.add(it["id"])
    rest = [it for it in items if it["id"] not in taken]
    picked += rng.sample(rest, count - len(picked))
    rng.shuffle(picked)
    return picked


def select_items(conn, req: AttemptCreate) -> tuple[list[str], str, int | None, bool]:
    """Returns (item ids, attempt name, quiz time limit, shuffle default)."""
    rng = random.Random(req.seed)
    if req.itemIds:
        items = _gradable_rows(conn, f"id IN ({','.join('?' * len(req.itemIds))})", tuple(req.itemIds))
        order = {i: n for n, i in enumerate(req.itemIds)}
        items.sort(key=lambda it: order[it["id"]])
        name, limit, shuffle = "Custom review", None, False
    elif req.quizId:
        if not req.packId:
            raise HTTPException(422, "quizId requires packId")
        row = conn.execute("SELECT body FROM packs WHERE id = ?", (req.packId,)).fetchone()
        if not row:
            raise HTTPException(404, "pack not found")
        quiz = next((q for q in json.loads(row["body"]).get("quizzes", []) if q["id"] == req.quizId), None)
        if not quiz:
            raise HTTPException(404, "quiz not found")
        found = {it["id"]: it for it in _gradable_rows(conn, "pack_id = ?", (req.packId,))}
        items = [found[i] for i in quiz["itemIds"] if i in found]
        name, limit, shuffle = quiz["name"], quiz.get("timeLimitSec"), quiz.get("shuffle", False)
    elif req.packId:
        items = _gradable_rows(conn, "pack_id = ?", (req.packId,))
        row = conn.execute("SELECT name FROM packs WHERE id = ?", (req.packId,)).fetchone()
        if not row:
            raise HTTPException(404, "pack not found")
        name, limit, shuffle = row["name"], None, False
    elif req.exam:
        items = _gradable_rows(conn, "pack_id IN (SELECT id FROM packs WHERE exam = ?)", (req.exam,))
        if req.topics:
            items = [it for it in items if set(it.get("topics", [])) & set(req.topics)]
        names = topic_names(conn, {r["id"] for r in conn.execute("SELECT id FROM packs WHERE exam = ?", (req.exam,))})
        topics = [{"id": t, "name": n} for t, n in names.items()]
        weights = {}
        for r in conn.execute("SELECT body FROM packs WHERE exam = ?", (req.exam,)):
            for t in json.loads(r["body"]).get("taxonomy", {}).get("topics", []):
                weights.setdefault(t["id"], t.get("weight"))
        for t in topics:
            t["weight"] = weights.get(t["id"])
        if req.topics:
            topics = [t for t in topics if t["id"] in req.topics]
        items = weighted_draw(items, topics, req.count or len(items), rng)
        name, limit, shuffle = f"{req.exam} mock exam", None, False
    else:
        raise HTTPException(422, "give one of itemIds, quizId, packId or exam")

    if req.topics and not req.exam:
        items = [it for it in items if set(it.get("topics", [])) & set(req.topics)]
    if req.shuffle if req.shuffle is not None else shuffle:
        rng.shuffle(items)
    if req.count and len(items) > req.count:
        items = items[: req.count]
    if not items:
        raise HTTPException(422, "no gradable questions match")
    return [it["id"] for it in items], req.name or name, limit, shuffle


# --- helpers -------------------------------------------------------------------------------

def _get_attempt(conn, attempt_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not row:
        raise HTTPException(404, "attempt not found")
    return row


def _expired(att: sqlite3.Row, now: datetime) -> bool:
    return bool(att["deadline_at"]) and att["submitted_at"] is None and now >= datetime.fromisoformat(att["deadline_at"])


def _submit(conn, att: sqlite3.Row, now: datetime) -> None:
    item_ids = json.loads(att["item_ids"])
    items = load_items(conn, item_ids)
    responses = {
        r["item_id"]: r for r in conn.execute("SELECT * FROM responses WHERE attempt_id = ?", (att["id"],))
    }
    score = 0
    for iid in item_ids:
        r = responses.get(iid)
        correct = bool(r and r["correct"])
        score += correct
        if iid in items:
            # Misses come back soon via SRS; low-confidence hits get a shorter interval.
            rating = 1 if not correct else 2 if (r and r["confidence"] == 1) else 3
            record_review(conn, iid, rating, "quiz", now)
    conn.execute(
        "UPDATE attempts SET submitted_at = ?, score = ? WHERE id = ?", (now.isoformat(), score, att["id"])
    )


def _summary(att: sqlite3.Row) -> dict:
    return {
        "id": att["id"],
        "name": att["name"],
        "mode": att["mode"],
        "packId": att["pack_id"],
        "quizId": att["quiz_id"],
        "exam": att["exam"],
        "startedAt": att["started_at"],
        "deadlineAt": att["deadline_at"],
        "submittedAt": att["submitted_at"],
        "score": att["score"],
        "total": att["total"],
    }


def _response_dict(r: sqlite3.Row | None, reveal: bool) -> dict | None:
    if r is None:
        return None
    return {
        "choiceIds": json.loads(r["choice_ids"]) if r["choice_ids"] else None,
        "text": r["text"],
        "correct": (bool(r["correct"]) if r["correct"] is not None else None) if reveal else None,
        "flagged": bool(r["flagged"]),
        "confidence": r["confidence"],
        "timeMs": r["time_ms"],
        "answered": r["answered_at"] is not None,
    }


def _view(conn, att: sqlite3.Row) -> dict:
    item_ids = json.loads(att["item_ids"])
    items = load_items(conn, item_ids)
    responses = {r["item_id"]: r for r in conn.execute("SELECT * FROM responses WHERE attempt_id = ?", (att["id"],))}
    submitted = att["submitted_at"] is not None
    out_items = []
    for iid in item_ids:
        item = items.get(iid)
        r = responses.get(iid)
        if item is None:  # removed from content since the attempt started
            out_items.append({"item": {"id": iid, "missing": True}, "response": _response_dict(r, submitted)})
            continue
        reveal = submitted or (att["mode"] == "practice" and r is not None and r["answered_at"] is not None)
        if not reveal:
            item = {k: v for k, v in item.items() if k not in HIDDEN_FIELDS}
        out_items.append({"item": item, "revealed": reveal, "response": _response_dict(r, reveal)})
    pack_ids = {it["packId"] for it in items.values()}
    return {
        **_summary(att),
        "serverTime": now_utc().isoformat(),
        "topicNames": topic_names(conn, pack_ids),
        "items": out_items,
    }


# --- routes --------------------------------------------------------------------------------

@router.post("", status_code=201)
def create_attempt(req: AttemptCreate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    ids, name, quiz_limit, _ = select_items(conn, req)
    now = now_utc()
    deadline = None
    if req.mode == "exam":
        limit = req.timeLimitSec or quiz_limit or SECONDS_PER_QUESTION * len(ids)
        deadline = (now + timedelta(seconds=limit)).isoformat()
    attempt_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO attempts (id, name, mode, pack_id, quiz_id, exam, item_ids, started_at, deadline_at, total)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (attempt_id, name, req.mode, req.packId, req.quizId, req.exam, dumps(ids), now.isoformat(), deadline, len(ids)),
    )
    return _view(conn, _get_attempt(conn, attempt_id))


@router.get("")
def list_attempts(limit: int = 50, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    rows = conn.execute("SELECT * FROM attempts ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    now = now_utc()
    out = []
    for att in rows:
        if _expired(att, now):
            _submit(conn, att, now)
            att = _get_attempt(conn, att["id"])
        out.append(_summary(att))
    return out


@router.get("/{attempt_id}")
def get_attempt(attempt_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    att = _get_attempt(conn, attempt_id)
    now = now_utc()
    if _expired(att, now):
        _submit(conn, att, now)
        att = _get_attempt(conn, attempt_id)
    return _view(conn, att)


@router.put("/{attempt_id}/responses/{item_id}")
def save_response(attempt_id: str, item_id: str, body: ResponseIn,
                  conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    # Read-modify-write of one response: take the write lock up front so concurrent saves
    # (e.g. pick an answer, then flag, in quick succession) can't overwrite each other.
    conn.execute("BEGIN IMMEDIATE")
    att = _get_attempt(conn, attempt_id)
    now = now_utc()
    if _expired(att, now):
        _submit(conn, att, now)
        raise HTTPException(409, "time is up; the attempt was submitted")
    if att["submitted_at"]:
        raise HTTPException(409, "attempt already submitted")
    if item_id not in json.loads(att["item_ids"]):
        raise HTTPException(404, "item not in this attempt")
    item = load_items(conn, [item_id]).get(item_id)
    if item is None:
        raise HTTPException(404, "item no longer exists")

    prev = conn.execute(
        "SELECT * FROM responses WHERE attempt_id = ? AND item_id = ?", (attempt_id, item_id)
    ).fetchone()
    answering = body.choiceIds is not None or body.text is not None
    if answering and att["mode"] == "practice" and prev and prev["answered_at"]:
        raise HTTPException(409, "already answered (practice answers lock after feedback)")
    if body.choiceIds is not None and item.get("choices"):
        valid = {c["id"] for c in item["choices"]}
        if not set(body.choiceIds) <= valid:
            raise HTTPException(422, "unknown choice id")

    choice_ids = body.choiceIds if body.choiceIds is not None else (json.loads(prev["choice_ids"]) if prev and prev["choice_ids"] else None)
    text = body.text if body.text is not None else (prev["text"] if prev else None)
    has_answer = bool(choice_ids) or bool(text)
    correct = grade(item, choice_ids, text) if has_answer else None
    flagged = body.flagged if body.flagged is not None else (bool(prev["flagged"]) if prev else False)
    confidence = body.confidence if body.confidence is not None else (prev["confidence"] if prev else None)
    time_ms = ((prev["time_ms"] or 0) if prev else 0) + (body.timeMs or 0)
    if answering:  # clearing every choice (exam mode) makes the question unanswered again
        answered_at = now.isoformat() if has_answer else None
    else:
        answered_at = prev["answered_at"] if prev else None
    conn.execute(
        """INSERT INTO responses (attempt_id, item_id, choice_ids, text, correct, flagged, confidence, time_ms, answered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(attempt_id, item_id) DO UPDATE SET choice_ids=excluded.choice_ids, text=excluded.text,
             correct=excluded.correct, flagged=excluded.flagged, confidence=excluded.confidence,
             time_ms=excluded.time_ms, answered_at=excluded.answered_at""",
        (attempt_id, item_id, dumps(choice_ids) if choice_ids else None, text,
         None if correct is None else int(correct), int(flagged), confidence, time_ms, answered_at),
    )
    view = _view(conn, att)
    return next(e for e in view["items"] if e["item"]["id"] == item_id)


@router.post("/{attempt_id}/submit")
def submit_attempt(attempt_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    conn.execute("BEGIN IMMEDIATE")  # a double-click must not grade (and log SRS reviews) twice
    att = _get_attempt(conn, attempt_id)
    if not att["submitted_at"]:
        _submit(conn, att, now_utc())
        att = _get_attempt(conn, attempt_id)
    return _view(conn, att)


@router.delete("/{attempt_id}", status_code=204)
def delete_attempt(attempt_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> None:
    _get_attempt(conn, attempt_id)
    conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
