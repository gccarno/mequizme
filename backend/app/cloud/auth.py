"""Firebase user session for the local backend.

The browser signs in with Google (Firebase JS SDK) and hands us its refresh token. We keep it in
the local DB and trade it for short-lived ID tokens.
REST reference: https://firebase.google.com/docs/reference/rest/auth"""

from __future__ import annotations

import sqlite3
import threading
import time

import httpx

from app.core.schema import utcnow

LOOKUP = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"
REFRESH = "https://securetoken.googleapis.com/v1/token"


class AuthError(RuntimeError):
    pass


def verify(http: httpx.Client, api_key: str, id_token: str) -> dict:
    """Ask Firebase who an ID token belongs to (rejects forged or expired tokens)."""
    r = http.post(LOOKUP, params={"key": api_key}, json={"idToken": id_token}, timeout=30)
    users = r.json().get("users") if r.status_code == 200 else None
    if not users:
        raise AuthError("Firebase rejected the sign-in token")
    return {"uid": users[0]["localId"], "email": users[0].get("email")}


def save_account(conn: sqlite3.Connection, uid: str, email: str | None, refresh_token: str) -> None:
    prev = conn.execute("SELECT uid FROM cloud_account").fetchone()
    if prev and prev["uid"] != uid:
        forget_sync_state(conn)
    conn.execute(
        """INSERT INTO cloud_account (id, uid, email, refresh_token, connected_at) VALUES (1, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET uid=excluded.uid, email=excluded.email,
               refresh_token=excluded.refresh_token, connected_at=excluded.connected_at""",
        (uid, email, refresh_token, utcnow().isoformat()),
    )


def forget_sync_state(conn: sqlite3.Connection) -> None:
    """Treat everything as never synced, e.g. before syncing with a different account."""
    for t in ("sync_meta", "cloud_content", "cloud_attempts"):
        conn.execute(f"DELETE FROM {t}")
    conn.execute("UPDATE reviews SET synced = 0")
    conn.execute("UPDATE srs_state SET dirty = 1")


def load_account(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT uid, email, refresh_token, connected_at FROM cloud_account").fetchone()


class TokenSource:
    """Hands out a valid ID token, refreshing a minute before it expires."""

    def __init__(self, http: httpx.Client, api_key: str, refresh_token: str):
        self.http, self.api_key, self.refresh_token = http, api_key, refresh_token
        self._token, self._expires = "", 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if time.time() > self._expires - 60:
                r = self.http.post(REFRESH, params={"key": self.api_key}, timeout=30,
                                   data={"grant_type": "refresh_token", "refresh_token": self.refresh_token})
                if r.status_code != 200:
                    raise AuthError("cloud session expired; sign in again")
                body = r.json()
                self._token = body["id_token"]
                self._expires = time.time() + int(body.get("expires_in", 3600))
                self.refresh_token = body.get("refresh_token", self.refresh_token)
            return self._token
