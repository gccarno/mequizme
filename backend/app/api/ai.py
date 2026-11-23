"""Optional AI tutor: fill in missing explanations, explain a mistake, write new questions, chat."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_conn, load_items
from app.core.schema import utcnow
from app.llm import tutor
from app.llm.jobs import JobRunner, job_view
from app.llm.provider import LLM, LLMError, author

router = APIRouter(prefix="/api/ai", tags=["ai"])


def get_llm(request: Request) -> LLM:
    llm = request.app.state.llm
    if llm is None:
        raise HTTPException(503, request.app.state.llm_reason or "AI features are off")
    return llm


def get_runner(request: Request) -> JobRunner:
    get_llm(request)
    return request.app.state.jobs


def pack_taxonomy(conn: sqlite3.Connection, pack_id: str) -> dict:
    row = conn.execute("SELECT body FROM packs WHERE id = ?", (pack_id,)).fetchone()
    return json.loads(row["body"]).get("taxonomy", {}) if row else {}


def exam_taxonomy(conn: sqlite3.Connection, exam: str) -> dict:
    """The exam's taxonomy, merged across its packs (first definition of each topic wins)."""
    merged: dict = {}
    topics: dict[str, dict] = {}
    for r in conn.execute("SELECT body FROM packs WHERE exam = ? ORDER BY path", (exam,)):
        tax = json.loads(r["body"]).get("taxonomy", {})
        for k, v in tax.items():
            if k != "topics":
                merged.setdefault(k, v)
        for t in tax.get("topics", []):
            topics.setdefault(t["id"], t)
    if not merged:
        raise HTTPException(404, f"unknown exam {exam}")
    merged["topics"] = list(topics.values())
    return merged


@router.get("/status")
def status(request: Request) -> dict:
    llm = request.app.state.llm
    if llm is None:
        return {"available": False, "reason": request.app.state.llm_reason}
    return {"available": True, "provider": llm.name, "model": llm.model, "label": author(llm)}


# --- fill in missing fields ----------------------------------------------------------------

class EnrichRequest(BaseModel):
    exam: str | None = None
    packId: str | None = None
    itemIds: list[str] | None = Field(default=None, max_length=500)


def enrich_targets(conn: sqlite3.Connection, req: EnrichRequest) -> list[tuple[dict, dict]]:
    if req.itemIds:
        where, args = f"i.id IN ({','.join('?' * len(req.itemIds))})", tuple(req.itemIds)
    elif req.packId:
        where, args = "i.pack_id = ?", (req.packId,)
    elif req.exam:
        where, args = "p.exam = ?", (req.exam,)
    else:
        raise HTTPException(422, "give one of exam, packId or itemIds")
    rows = conn.execute(
        f"SELECT i.body, i.pack_id FROM items i JOIN packs p ON p.id = i.pack_id "
        f"WHERE i.status != 'draft' AND {where} ORDER BY p.path, i.position", args,
    ).fetchall()
    taxonomies: dict[str, dict] = {}
    out = []
    for r in rows:
        item = json.loads(r["body"])
        # Skip questions already waiting for review: asking again would redo the same gaps
        # (e.g. no doc link the tutor was sure of).
        if item.get("draft") or not tutor.missing_fields(item):
            continue
        if r["pack_id"] not in taxonomies:
            taxonomies[r["pack_id"]] = pack_taxonomy(conn, r["pack_id"])
        out.append((item, taxonomies[r["pack_id"]]))
    return out


@router.get("/enrich/preview")
def enrich_preview(exam: str | None = None, packId: str | None = None,
                   conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """How many questions are missing something, before starting a job."""
    targets = enrich_targets(conn, EnrichRequest(exam=exam, packId=packId))
    return {"count": len(targets)}


@router.post("/enrich", status_code=202)
def start_enrich(req: EnrichRequest, conn: sqlite3.Connection = Depends(get_conn),
                 runner: JobRunner = Depends(get_runner)) -> dict:
    targets = enrich_targets(conn, req)
    if not targets:
        raise HTTPException(422, "every matching question already has an explanation, links and topics")
    job_id = runner.start_enrich(targets, req.model_dump(exclude_none=True))
    return _job(conn, job_id)


# --- write new questions -------------------------------------------------------------------

class GenerateRequest(BaseModel):
    exam: str
    topic: str
    count: int = Field(default=5, ge=1, le=10)
    focus: str | None = Field(default=None, max_length=300)


@router.post("/generate", status_code=202)
def start_generate(req: GenerateRequest, conn: sqlite3.Connection = Depends(get_conn),
                   runner: JobRunner = Depends(get_runner)) -> dict:
    taxonomy = exam_taxonomy(conn, req.exam)
    topic = next((t for t in taxonomy["topics"] if t["id"] == req.topic), None)
    if topic is None:
        raise HTTPException(422, f"unknown topic {req.topic}")
    existing = [
        json.loads(r["body"])["prompt"]
        for r in conn.execute(
            "SELECT i.body FROM items i JOIN packs p ON p.id = i.pack_id WHERE p.exam = ? AND i.topics LIKE ?",
            (req.exam, f'%"{req.topic}"%'),
        )
    ]
    job_id = runner.start_generate(req.exam, taxonomy, topic, req.count, existing, req.focus)
    return _job(conn, job_id)


# --- jobs ----------------------------------------------------------------------------------

def _job(conn: sqlite3.Connection, job_id: str) -> dict:
    row = conn.execute("SELECT * FROM ai_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "job not found")
    return job_view(row)


@router.get("/jobs")
def list_jobs(limit: int = 10, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return [job_view(r) for r in conn.execute("SELECT * FROM ai_jobs ORDER BY created_at DESC LIMIT ?", (limit,))]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return _job(conn, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    _job(conn, job_id)
    conn.execute("UPDATE ai_jobs SET status = 'cancelled' WHERE id = ? AND status IN ('queued', 'running')", (job_id,))
    return _job(conn, job_id)


# --- explain my mistake / chat -------------------------------------------------------------

def _revealed_entry(conn: sqlite3.Connection, attempt_id: str, item_id: str) -> tuple[dict, sqlite3.Row | None]:
    """The item and the learner's response, only once the answer is visible to them."""
    att = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not att:
        raise HTTPException(404, "attempt not found")
    if item_id not in json.loads(att["item_ids"]):
        raise HTTPException(404, "item not in this attempt")
    r = conn.execute("SELECT * FROM responses WHERE attempt_id = ? AND item_id = ?", (attempt_id, item_id)).fetchone()
    revealed = att["submitted_at"] is not None or (att["mode"] == "practice" and r is not None and r["answered_at"])
    if not revealed:
        raise HTTPException(409, "answer this question first")
    item = load_items(conn, [item_id]).get(item_id)
    if item is None:
        raise HTTPException(404, "item no longer exists")
    return item, r


class ExplainRequest(BaseModel):
    attemptId: str
    itemId: str
    refresh: bool = False


@router.post("/explain")
def explain(req: ExplainRequest, conn: sqlite3.Connection = Depends(get_conn), llm: LLM = Depends(get_llm)) -> dict:
    item, r = _revealed_entry(conn, req.attemptId, req.itemId)
    chosen = sorted(json.loads(r["choice_ids"])) if r and r["choice_ids"] else []
    if r is not None and r["correct"]:
        raise HTTPException(422, "this answer was right")
    key = ",".join(chosen) or "-"
    if not req.refresh:
        hit = conn.execute("SELECT text, model FROM ai_explanations WHERE item_id = ? AND choice_key = ?",
                           (item["id"], key)).fetchone()
        if hit:
            return {"text": hit["text"], "by": hit["model"], "cached": True}
    conn.commit()  # don't hold a transaction open during a slow model call
    try:
        text = tutor.explain_mistake(llm, item, chosen, r["confidence"] if r else None,
                                     pack_taxonomy(conn, item["packId"]))
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    if not text:
        raise HTTPException(502, "the AI returned an empty answer")
    conn.execute(
        """INSERT INTO ai_explanations (item_id, choice_key, text, model, created_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(item_id, choice_key) DO UPDATE SET text=excluded.text, model=excluded.model,
             created_at=excluded.created_at""",
        (item["id"], key, text, author(llm), utcnow().isoformat()),
    )
    return {"text": text, "by": author(llm), "cached": False}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    attemptId: str | None = None
    itemId: str | None = None
    exam: str | None = None
    topic: str | None = None


@router.post("/chat")
def chat(req: ChatRequest, conn: sqlite3.Connection = Depends(get_conn), llm: LLM = Depends(get_llm)) -> dict:
    if req.messages[-1].role != "user":
        raise HTTPException(422, "the last message must be the learner's")
    item = topic = None
    if req.itemId:
        if req.attemptId:
            item, _ = _revealed_entry(conn, req.attemptId, req.itemId)
        else:
            item = load_items(conn, [req.itemId]).get(req.itemId)
            if item is None:
                raise HTTPException(404, "item not found")
        taxonomy = pack_taxonomy(conn, item["packId"])
    elif req.exam:
        taxonomy = exam_taxonomy(conn, req.exam)
        if req.topic:
            topic = next((t for t in taxonomy["topics"] if t["id"] == req.topic), None)
    else:
        raise HTTPException(422, "give itemId or exam")
    conn.commit()
    try:
        reply = tutor.chat(llm, [m.model_dump() for m in req.messages], taxonomy, item=item, topic=topic)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    if not reply:
        raise HTTPException(502, "the AI returned an empty answer")
    return {"reply": reply}
