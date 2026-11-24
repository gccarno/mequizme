"""Review AI drafts: list them, accept (optionally with edits), or reject."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_conn, topic_names
from app.core.packfile import update_item
from app.core.schema import Resource

router = APIRouter(prefix="/api", tags=["drafts"])


@router.get("/drafts")
def list_drafts(exam: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    q = ("SELECT i.body, i.pack_id, p.name AS pack_name, p.exam FROM items i JOIN packs p ON p.id = i.pack_id "
         "WHERE (i.status = 'draft' OR json_extract(i.body, '$.draft') IS NOT NULL)")
    args: tuple = ()
    if exam:
        q += " AND p.exam = ?"
        args = (exam,)
    items = []
    pack_ids = set()
    for r in conn.execute(q + " ORDER BY p.path, i.position", args):
        body = json.loads(r["body"])
        body.update(packId=r["pack_id"], packName=r["pack_name"], exam=r["exam"])
        pack_ids.add(r["pack_id"])
        items.append(body)
    return {"items": items, "topicNames": topic_names(conn, pack_ids) if pack_ids else {}}


@router.get("/drafts/count")
def count_drafts(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE status = 'draft' OR json_extract(body, '$.draft') IS NOT NULL"
    ).fetchone()
    return {"count": row["n"]}


class Edits(BaseModel):
    """Reviewer's changes, applied before accepting."""

    explanation: str | None = Field(default=None, max_length=10000)
    choiceRationales: dict[str, str] | None = None
    resources: list[Resource] | None = None
    topics: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)


@router.post("/items/{item_id}/accept")
def accept(item_id: str, request: Request, edits: Edits | None = None,
           conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    changes = edits.model_dump(exclude_unset=True, mode="json") if edits else {}

    def change(item: dict) -> dict:
        if not item.get("draft") and item.get("status") != "draft":
            raise HTTPException(409, "nothing to review on this item")
        for k, v in changes.items():
            if v in (None, "", [], {}):
                item.pop(k, None)
            else:
                item[k] = v
        item.pop("draft", None)
        item["status"] = "reviewed"
        return item

    return update_item(conn, request.app.state.content_dir, item_id, change)


@router.post("/items/{item_id}/reject")
def reject(item_id: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    def change(item: dict) -> dict | None:
        draft = item.get("draft")
        if item.get("status") == "draft":
            return None  # a generated question: rejecting deletes it
        if not draft:
            raise HTTPException(409, "nothing to review on this item")
        previous = draft.get("previous") or {}
        for f in draft.get("fields", []):
            if f in previous:
                item[f] = previous[f]
            else:
                item.pop(f, None)
        item.pop("draft", None)
        return item

    saved = update_item(conn, request.app.state.content_dir, item_id, change)
    return {"deleted": saved is None, "item": saved}
