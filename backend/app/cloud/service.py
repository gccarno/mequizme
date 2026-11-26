"""The app's handle on cloud sync: sign-in state, sync on demand, and a background loop."""

from __future__ import annotations

import logging
import os
import threading

import httpx

from app.cloud import auth
from app.cloud.firestore import Firestore
from app.cloud.sync import SyncReport, set_meta, sync_once
from app.core.db import Database

log = logging.getLogger(__name__)


class NotConnected(RuntimeError):
    pass


class CloudService:
    def __init__(self, db: Database, api_key: str | None, project: str | None,
                 http: httpx.Client | None = None, interval: float = 300):
        self.db, self.api_key, self.project, self.interval = db, api_key, project, interval
        self.http = http or httpx.Client()
        self._sync_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tokens: auth.TokenSource | None = None

    @classmethod
    def from_env(cls, db: Database, http: httpx.Client | None = None) -> CloudService:
        try:
            interval = float(os.environ.get("MEQUIZME_SYNC_INTERVAL", "300"))
        except ValueError:
            interval = 300
        return cls(db, os.environ.get("MEQUIZME_FIREBASE_API_KEY"), os.environ.get("MEQUIZME_FIREBASE_PROJECT"),
                   http, interval)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.project)

    # --- session -------------------------------------------------------------------------

    def connect(self, id_token: str, refresh_token: str) -> dict:
        who = auth.verify(self.http, self.api_key, id_token)
        with self.db.connect() as conn:
            auth.save_account(conn, who["uid"], who["email"], refresh_token)
        self._tokens = None
        return self.status()

    def disconnect(self) -> None:
        with self._sync_lock, self.db.connect() as conn:
            conn.execute("DELETE FROM cloud_account")
        self._tokens = None

    def _account(self):
        with self.db.connect() as conn:
            return auth.load_account(conn)

    def status(self) -> dict:
        acct = self._account()
        with self.db.connect() as conn:
            meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM sync_meta")}
            pending = conn.execute("SELECT (SELECT COUNT(*) FROM reviews WHERE synced = 0) + "
                                   "(SELECT COUNT(*) FROM srs_state WHERE dirty = 1)").fetchone()[0]
        return {
            "configured": self.configured,
            "connected": acct is not None,
            "email": acct["email"] if acct else None,
            "lastSync": meta.get("last_sync"),
            "lastError": meta.get("last_error"),
            "pending": pending,
            "syncing": self._sync_lock.locked(),
        }

    # --- sync ----------------------------------------------------------------------------

    def sync_now(self) -> SyncReport:
        if not self.configured:
            raise NotConnected("cloud sync isn't configured (see infra/README.md)")
        with self._sync_lock:
            acct = self._account()
            if not acct:
                raise NotConnected("not signed in")
            if self._tokens is None or self._tokens.refresh_token != acct["refresh_token"]:
                self._tokens = auth.TokenSource(self.http, self.api_key, acct["refresh_token"])
            fs = Firestore(self.http, self.project, self._tokens)
            try:
                report = sync_once(self.db, fs, acct["uid"])
            except Exception as e:
                set_meta(self.db, "last_error", str(e)[:500])
                raise
            set_meta(self.db, "last_error", None)
            return report

    def start(self) -> None:
        if self.interval <= 0 or not self.configured or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="cloud-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            if self._account() is None:
                continue
            try:
                self.sync_now()
            except Exception:
                log.exception("background sync failed")
