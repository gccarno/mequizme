"""Flashcard study: SRS due queue and ratings."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_conn, load_item, topic_names
from app.core.grading import is_gradable
from app.core.scheduler import now_utc, record_review

router = APIRouter(prefix="/api/study", tags=["study"])

CARD_TYPES = ("flashcard", "cloze")


class ReviewIn(BaseModel):
    itemId: str
    rating: int = Field(ge=1, le=4)
    durationMs: int | None = Field(default=None, ge=0)


def _scope(pack_id: str | None, exam: str | None) -> tuple[str, tuple]:
    if pack_id:
        return "i.pack_id = ?", (pack_id,)
    if exam:
        return "i.pack_id IN (SELECT id FROM packs WHERE exam = ?)", (exam,)
    return "1 = 1", ()


@router.get("/queue")
def queue(packId: str | None = None, exam: str | None = None, limit: int = 50, newLimit: int = 20,
          conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """Due cards first (oldest due first), then unseen cards in pack order."""
    where, args = _scope(packId, exam)
    types = f"i.type IN ({','.join('?' * len(CARD_TYPES))})"
    now = now_utc().isoformat()
    due = conn.execute(
        f"""SELECT i.body FROM items i JOIN srs_state s ON s.item_id = i.id
            WHERE {where} AND {types} AND i.status != 'draft' AND s.due <= ? ORDER BY s.due LIMIT ?""",
        (*args, *CARD_TYPES, now, limit),
    ).fetchall()
    new = conn.execute(
        f"""SELECT i.body FROM items i LEFT JOIN srs_state s ON s.item_id = i.id
            WHERE {where} AND {types} AND i.status != 'draft' AND s.item_id IS NULL
            ORDER BY i.pack_id, i.position LIMIT ?""",
        (*args, *CARD_TYPES, max(0, min(newLimit, limit - len(due)))),
    ).fetchall()
    cards = [json.loads(r["body"]) for r in [*due, *new]]
    return {
        "dueCount": len(due),
        "newCount": len(new),
        "topicNames": topic_names(conn),
        "cards": cards,
    }


@router.post("/review")
def review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    load_item(conn, body.itemId)  # 404 if unknown
    result = record_review(conn, body.itemId, body.rating, "flashcard", duration_ms=body.durationMs)
    return {"itemId": body.itemId, "due": result.due.isoformat()}


@router.get("/due-questions")
def due_questions(packId: str | None = None, exam: str | None = None,
                  conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """Quiz questions whose SRS review is due (mostly earlier misses)."""
    where, args = _scope(packId, exam)
    rows = conn.execute(
        f"""SELECT i.body FROM items i JOIN srs_state s ON s.item_id = i.id
            WHERE {where} AND i.status != 'draft' AND s.due <= ? ORDER BY s.due""",
        (*args, now_utc().isoformat()),
    )
    ids = [b["id"] for b in (json.loads(r["body"]) for r in rows) if is_gradable(b)]
    return {"count": len(ids), "itemIds": ids}


@router.get("/items/{item_id}")
def get_item(item_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    item = load_item(conn, item_id)
    if not item:
        raise HTTPException(404)
    return item
