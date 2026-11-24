from __future__ import annotations

import json
import sqlite3
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_conn
from app.core.grading import is_gradable
from app.core.ingest import ingest_dir
from app.core.scheduler import now_utc

router = APIRouter(prefix="/api", tags=["packs"])

SRS_TYPES = ("flashcard", "cloze")


@router.get("/packs")
def list_packs(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    now = now_utc().isoformat()
    srs = {
        r["pack_id"]: (r["due"], r["new"])
        for r in conn.execute(
            f"""SELECT i.pack_id,
                   SUM(CASE WHEN s.due IS NOT NULL AND s.due <= ? THEN 1 ELSE 0 END) AS due,
                   SUM(CASE WHEN s.item_id IS NULL AND i.type IN ({','.join('?' * len(SRS_TYPES))})
                       THEN 1 ELSE 0 END) AS new
                FROM items i LEFT JOIN srs_state s ON s.item_id = i.id
                WHERE i.status != 'draft' GROUP BY i.pack_id""",
            (now, *SRS_TYPES),
        )
    }
    last = {
        r["pack_id"]: dict(r)
        for r in conn.execute(
            """SELECT pack_id, id, score, total, submitted_at, mode FROM attempts a
               WHERE submitted_at IS NOT NULL AND pack_id IS NOT NULL AND submitted_at =
                 (SELECT MAX(submitted_at) FROM attempts b WHERE b.pack_id = a.pack_id)"""
        )
    }
    out = []
    for p in conn.execute("SELECT id, name, exam, path, body FROM packs ORDER BY exam, path"):
        body = json.loads(p["body"])
        types = Counter(r["type"] for r in conn.execute("SELECT type FROM items WHERE pack_id = ?", (p["id"],)))
        due, new = srs.get(p["id"], (0, 0))
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "description": body.get("description", ""),
                "exam": p["exam"],
                "path": p["path"],
                "itemCount": sum(types.values()),
                "types": dict(types),
                "quizzes": [
                    {"id": q["id"], "name": q["name"], "count": len(q["itemIds"]),
                     "timeLimitSec": q.get("timeLimitSec")}
                    for q in body.get("quizzes", [])
                ],
                "dueCount": due or 0,
                "newCount": new or 0,
                "lastAttempt": last.get(p["id"]),
            }
        )
    return out


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute("SELECT body FROM packs WHERE id = ?", (pack_id,)).fetchone()
    if not row:
        raise HTTPException(404, "pack not found")
    pack = json.loads(row["body"])
    pack["items"] = [
        json.loads(r["body"])
        for r in conn.execute("SELECT body FROM items WHERE pack_id = ? ORDER BY position", (pack_id,))
    ]
    return pack


@router.get("/exams")
def list_exams(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    exams: dict[str, dict] = {}
    for p in conn.execute("SELECT id, exam, body FROM packs WHERE exam IS NOT NULL"):
        e = exams.setdefault(p["exam"], {"exam": p["exam"], "name": None, "topics": {}, "packIds": [],
                                         "questionCount": 0, "cardCount": 0})
        e["packIds"].append(p["id"])
        taxonomy = json.loads(p["body"]).get("taxonomy", {})
        e["name"] = e["name"] or taxonomy.get("name")
        for t in taxonomy.get("topics", []):
            e["topics"].setdefault(t["id"], t)
    for e in exams.values():
        rows = conn.execute(
            f"SELECT body FROM items WHERE status != 'draft' AND pack_id IN ({','.join('?' * len(e['packIds']))})",
            e["packIds"],
        )
        bodies = [json.loads(r["body"]) for r in rows]
        e["questionCount"] = sum(1 for b in bodies if is_gradable(b))
        e["cardCount"] = sum(1 for b in bodies if b["type"] in SRS_TYPES)
        e["topics"] = list(e["topics"].values())
        e["name"] = e["name"] or e["exam"]
    return list(exams.values())


@router.post("/admin/reload")
def reload_content(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    report = ingest_dir(conn, request.app.state.content_dir)
    return {"packs": report.packs, "items": report.items, "errors": report.errors}
