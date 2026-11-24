"""Write changes back to pack files, then re-ingest them.

Pack files stay the source of truth for content: accepting an AI draft or saving generated
questions edits the JSON in `content/`, so it shows up in git like any other edit.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.ingest import ingest_pack
from app.core.schema import Source, StudyPack, Taxonomy, stable_id, utcnow

# One writer at a time: jobs run on worker threads and requests on the threadpool.
_lock = threading.RLock()


def _pack_path(content_dir: Path, rel: str) -> Path:
    path = (content_dir / rel).resolve()
    if content_dir.resolve() not in path.parents:
        raise HTTPException(400, "pack path escapes the content folder")
    return path


def _write(path: Path, pack: StudyPack) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(pack.to_json())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _save(conn: sqlite3.Connection, content_dir: Path, rel: str, doc: dict) -> StudyPack:
    doc["updatedAt"] = utcnow().isoformat()
    try:
        pack = StudyPack.model_validate(doc)  # never write a file the app can't load back
    except ValidationError as e:
        raise HTTPException(422, f"that change would make the pack invalid: {e.errors()[0]['msg']}") from e
    _write(_pack_path(content_dir, rel), pack)
    ingest_pack(conn, pack, rel)
    return pack


def update_item(conn: sqlite3.Connection, content_dir: Path, item_id: str,
                change: Callable[[dict], dict | None]) -> dict | None:
    """Apply `change` to the item's JSON in its pack file. Return None from `change` to delete it.
    Returns the saved item (None if deleted)."""
    with _lock:
        row = conn.execute(
            "SELECT p.path FROM items i JOIN packs p ON p.id = i.pack_id WHERE i.id = ?", (item_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"item {item_id} not found")
        rel = row["path"]
        doc = json.loads(_pack_path(content_dir, rel).read_text(encoding="utf-8"))
        idx = next((n for n, it in enumerate(doc["items"]) if it["id"] == item_id), None)
        if idx is None:
            raise HTTPException(409, "the pack file changed on disk; reload content and try again")
        new = change(json.loads(json.dumps(doc["items"][idx])))
        if new is None:
            del doc["items"][idx]
            for q in doc.get("quizzes", []):
                q["itemIds"] = [i for i in q["itemIds"] if i != item_id]
            if not doc["items"]:
                raise HTTPException(409, "can't remove the last item in a pack")
        else:
            new["updatedAt"] = utcnow().isoformat()
            doc["items"][idx] = new
        _save(conn, content_dir, rel, doc)
        return new


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "exam"


def append_generated(conn: sqlite3.Connection, content_dir: Path, exam: str, taxonomy: dict,
                     items: list[dict]) -> str:
    """Add generated items to the exam's `generated.json` pack (created on first use).
    Returns the pack id."""
    rel = f"{_slug(exam)}/generated.json"
    with _lock:
        path = _pack_path(content_dir, rel)
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
        else:
            name = taxonomy.get("name") or exam
            doc = json.loads(StudyPack(
                id=stable_id("generated", exam),
                name=f"New questions: {name}",
                description="Questions written by the AI tutor. Review them before they appear in quizzes.",
                source=Source(kind="llm"),
                taxonomy=Taxonomy.model_validate(taxonomy),
                items=[],
                createdAt=utcnow(),
            ).model_dump_json(exclude_none=True))
        doc["items"].extend(items)
        pack = _save(conn, content_dir, rel, doc)
        return pack.id
