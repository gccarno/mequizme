"""Cloud sync with the StudyDeck companion app (via Firestore)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.cloud.auth import AuthError
from app.cloud.firestore import FirestoreError
from app.cloud.service import CloudService, NotConnected

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


class SessionIn(BaseModel):
    idToken: str
    refreshToken: str


def _svc(request: Request) -> CloudService:
    return request.app.state.cloud


@router.get("/status")
def status(request: Request) -> dict:
    return _svc(request).status()


@router.post("/session")
def connect(body: SessionIn, request: Request) -> dict:
    svc = _svc(request)
    if not svc.configured:
        raise HTTPException(409, "cloud sync isn't configured (see infra/README.md)")
    try:
        return svc.connect(body.idToken, body.refreshToken)
    except AuthError as e:
        raise HTTPException(401, str(e)) from e


@router.delete("/session", status_code=204)
def disconnect(request: Request) -> None:
    _svc(request).disconnect()


@router.post("/sync")
def sync(request: Request) -> dict:
    svc = _svc(request)
    try:
        report = svc.sync_now()
    except NotConnected as e:
        raise HTTPException(409, str(e)) from e
    except AuthError as e:
        raise HTTPException(401, str(e)) from e
    except FirestoreError as e:
        raise HTTPException(502, str(e)) from e
    return {**report.as_dict(), "status": svc.status()}
