"""Progress analytics per exam: readiness, topic mastery, trends, calibration, resources."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.core.analytics import exam_context, exam_stats
from app.core.scheduler import now_utc

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/exams/{exam}")
def get_exam_stats(exam: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    ctx = exam_context(conn, exam)
    if ctx is None:
        raise HTTPException(404, "exam not found")
    return exam_stats(conn, ctx, now_utc())
