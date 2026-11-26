"""FastAPI app. Dev: `uv run fastapi dev app/main.py`; the Vite dev server proxies /api.
When frontend/dist exists it is served at / so the whole app runs as one process."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import sentry_sdk
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import ai, cloud, drafts, packs, quiz, stats, study
from app.cloud.service import CloudService
from app.core.db import Database
from app.core.ingest import ingest_dir
from app.core.localguard import LocalOnly
from app.llm import provider
from app.llm.jobs import JobRunner, mark_interrupted

REPO_ROOT = Path(__file__).resolve().parents[2]
_FROM_ENV = object()
log = logging.getLogger("mequizme")


def _init_sentry() -> None:
    """Error reporting, only when SENTRY_DSN is set (scripts/render_env.py writes it to backend/.env)."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn or sentry_sdk.get_client().is_active():
        return
    sentry_sdk.init(
        dsn=dsn,
        # Answers and Firebase tokens stay local: no user/IP info, no HTTP bodies (POST
        # /api/cloud/session carries tokens), no stack-frame variables (sync holds a refresh
        # token). Headers and query params keep sentry-sdk's built-in token/auth/key scrubbing.
        data_collection={"user_info": False, "http_bodies": [], "stack_frame_variables": False},
        environment=os.environ.get("SENTRY_ENVIRONMENT", "local"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
    )


def create_app(content_dir: Path | None = None, db_path: Path | str | None = None,
               static_dir: Path | None = None, llm=_FROM_ENV, cloud_http: httpx.Client | None = None) -> FastAPI:
    """`llm`: a provider, None to turn AI off, or omitted to pick one from the environment.
    `cloud_http`: the HTTP client cloud sync uses (tests pass one with a fake Firestore)."""
    _init_sentry()
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
        app.state.cloud.start()
        yield
        app.state.cloud.stop()
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
    app.state.cloud = CloudService.from_env(app.state.db, cloud_http)
    for r in (packs.router, quiz.router, stats.router, study.router, ai.router, drafts.router, cloud.router):
        app.include_router(r)

    if os.environ.get("MEQUIZME_DEBUG"):
        @app.get("/api/_debug/sentry", include_in_schema=False)
        def debug_sentry() -> None:
            raise RuntimeError("mequizme backend Sentry test error")

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
