"""Background AI jobs. Each model call takes seconds, so bulk work runs on worker threads and
reports progress through the ai_jobs table, which the UI polls."""

from __future__ import annotations

import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.db import Database, dumps
from app.core.packfile import append_generated, update_item
from app.core.schema import utcnow
from app.llm import tutor
from app.llm.provider import LLM, author

log = logging.getLogger(__name__)


def _concurrency() -> int:
    try:
        return max(1, min(8, int(os.environ.get("MEQUIZME_LLM_CONCURRENCY", "3"))))
    except ValueError:
        return 3


class JobRunner:
    def __init__(self, db: Database, content_dir: Path, llm: LLM):
        self.db, self.content_dir, self.llm = db, content_dir, llm
        self.jobs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-job")
        self.calls = ThreadPoolExecutor(max_workers=_concurrency(), thread_name_prefix="ai-call")

    def shutdown(self) -> None:
        self.jobs.shutdown(wait=False, cancel_futures=True)
        self.calls.shutdown(wait=False, cancel_futures=True)

    # --- bookkeeping ---------------------------------------------------------------------

    def _create(self, kind: str, params: dict, total: int) -> str:
        job_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO ai_jobs (id, kind, params, status, total, created_at) VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, kind, dumps(params), total, utcnow().isoformat()),
            )
        return job_id

    def _status(self, job_id: str) -> str:
        with self.db.connect() as conn:
            return conn.execute("SELECT status FROM ai_jobs WHERE id = ?", (job_id,)).fetchone()["status"]

    def _set(self, job_id: str, **cols) -> None:
        with self.db.connect() as conn:
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(f"UPDATE ai_jobs SET {sets} WHERE id = ?", (*cols.values(), job_id))

    def _progress(self, job_id: str, changed: int, error: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT errors FROM ai_jobs WHERE id = ?", (job_id,)).fetchone()
            errors = json.loads(row["errors"])
            if error:
                errors.append(error)
            conn.execute("UPDATE ai_jobs SET done = done + 1, changed = changed + ?, errors = ? WHERE id = ?",
                         (changed, dumps(errors[-50:]), job_id))

    def _finish(self, job_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE ai_jobs SET status = CASE WHEN status = 'cancelled' THEN 'cancelled' "
                "WHEN changed = 0 AND errors != '[]' THEN 'failed' ELSE 'done' END, finished_at = ? WHERE id = ?",
                (utcnow().isoformat(), job_id),
            )

    # --- fill in missing fields ----------------------------------------------------------

    def start_enrich(self, targets: list[tuple[dict, dict]], params: dict) -> str:
        """targets: (item, taxonomy) pairs."""
        job_id = self._create("enrich", params, len(targets))
        self.jobs.submit(self._run_enrich, job_id, targets)
        return job_id

    def _run_enrich(self, job_id: str, targets: list[tuple[dict, dict]]) -> None:
        self._set(job_id, status="running")
        by = author(self.llm)

        def one(item: dict, taxonomy: dict) -> None:
            if self._status(job_id) == "cancelled":
                return
            changed, error = 0, None
            try:
                fields = tutor.missing_fields(item)
                values, note = tutor.enrich(self.llm, item, taxonomy, fields)

                def change(current: dict) -> dict:
                    # Only fill what is still empty: a person may have edited it meanwhile.
                    still = set(tutor.missing_fields(current))
                    return tutor.apply_draft(current, {k: v for k, v in values.items() if k in still}, note, by)

                if values or note:
                    with self.db.connect() as conn:
                        update_item(conn, self.content_dir, item["id"], change)
                    changed = 1
            except Exception as e:  # one bad answer shouldn't stop the batch
                log.warning("enrich %s failed: %s", item["id"], e)
                error = f"{item['prompt'][:60]}…: {e}"
            self._progress(job_id, changed, error)

        try:
            for f in [self.calls.submit(one, it, tax) for it, tax in targets]:
                f.result()
        finally:
            self._finish(job_id)

    # --- write new questions -------------------------------------------------------------

    def start_generate(self, exam: str, taxonomy: dict, topic: dict, count: int, existing: list[str],
                       focus: str | None) -> str:
        params = {"exam": exam, "topic": topic["id"], "count": count, "focus": focus}
        job_id = self._create("generate", params, count)
        self.jobs.submit(self._run_generate, job_id, exam, taxonomy, topic, count, existing, focus)
        return job_id

    def _run_generate(self, job_id, exam, taxonomy, topic, count, existing, focus) -> None:
        self._set(job_id, status="running")
        try:
            items = tutor.generate(self.llm, taxonomy, topic, count, existing, focus)
            if items:
                with self.db.connect() as conn:
                    known = {r["id"] for r in conn.execute(
                        f"SELECT id FROM items WHERE id IN ({','.join('?' * len(items))})", [i["id"] for i in items])}
                    items = [i for i in items if i["id"] not in known]
                    if items:
                        append_generated(conn, self.content_dir, exam, taxonomy, items)
            self._set(job_id, done=count, changed=len(items),
                      errors=dumps([] if items else ["The AI's questions were all too close to existing ones."]))
        except Exception as e:
            log.warning("generate failed: %s", e)
            self._set(job_id, done=count, errors=dumps([str(e)]))
        finally:
            self._finish(job_id)


def mark_interrupted(db: Database) -> None:
    """Jobs don't survive a restart; say so instead of showing them as running forever."""
    with db.connect() as conn:
        conn.execute("UPDATE ai_jobs SET status = 'interrupted', finished_at = ? WHERE status IN ('queued', 'running')",
                     (utcnow().isoformat(),))


def job_view(row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "params": json.loads(row["params"]),
        "status": row["status"],
        "total": row["total"],
        "done": row["done"],
        "changed": row["changed"],
        "errors": json.loads(row["errors"]),
        "createdAt": row["created_at"],
        "finishedAt": row["finished_at"],
    }
