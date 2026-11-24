"""FastAPI app. Dev: `uv run fastapi dev app/main.py`; the Vite dev server proxies /api.
When frontend/dist exists it is served at / so the whole app runs as one process."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import ai, drafts, packs, quiz, stats, study
from app.core.db import Database
from app.core.ingest import ingest_dir
from app.core.localguard import LocalOnly
from app.llm import provider
from app.llm.jobs import JobRunner, mark_interrupted

REPO_ROOT = Path(__file__).resolve().parents[2]
_FROM_ENV = object()
log = logging.getLogger("mequizme")


def create_app(content_dir: Path | None = None, db_path: Path | str | None = None,
               static_dir: Path | None = None, llm=_FROM_ENV) -> FastAPI:
    """`llm`: a provider, None to turn AI off, or omitted to pick one from the environment."""
    content_dir = Path(content_dir or os.environ.get("MEQUIZME_CONTENT", REPO_ROOT / "content"))
    db_path = db_path or os.environ.get("MEQUIZME_DB", REPO_ROOT / "data" / "mequizme.db")
    static_dir = Path(static_dir or REPO_ROOT / "frontend" / "dist")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with app.state.db.connect() as conn:
            report = ingest_dir(conn, content_dir)
        log.info("ingested %d packs / %d items from %s", report.packs, report.items, content_dir)
        for path, err in report.errors.items():
            log.warning("invalid pack %s: %s", path, err)
        mark_interrupted(app.state.db)
        if app.state.llm:
            log.info("AI tutor: %s", provider.author(app.state.llm))
        else:
            log.info("AI tutor off: %s", app.state.llm_reason)
        yield
        if app.state.jobs:
            app.state.jobs.shutdown()

    app = FastAPI(title="mequizme", lifespan=lifespan)
    extra = {h.strip().lower() for h in os.environ.get("MEQUIZME_ALLOWED_HOSTS", "").split(",") if h.strip()}
    app.add_middleware(LocalOnly, extra_hosts=extra)
    app.state.db = Database(db_path)
    app.state.content_dir = content_dir
    if llm is _FROM_ENV:
        llm, reason = provider.from_env()
    else:
        reason = "AI features are off."
    app.state.llm, app.state.llm_reason = llm, (None if llm else reason)
    app.state.jobs = JobRunner(app.state.db, content_dir, llm) if llm else None
    for r in (packs.router, quiz.router, stats.router, study.router, ai.router, drafts.router):
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    if (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = static_dir / path
            if path and f.is_file() and static_dir in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
