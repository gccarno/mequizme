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

from app.api import packs, quiz, stats, study
from app.core.db import Database
from app.core.ingest import ingest_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("mequizme")


def create_app(content_dir: Path | None = None, db_path: Path | str | None = None,
               static_dir: Path | None = None) -> FastAPI:
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
        yield

    app = FastAPI(title="mequizme", lifespan=lifespan)
    app.state.db = Database(db_path)
    app.state.content_dir = content_dir
    for r in (packs.router, quiz.router, stats.router, study.router):
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
