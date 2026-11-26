"""In-memory stand-in for Firebase Auth + Firestore REST, plugged into httpx via MockTransport.

Implements just what app/cloud uses, plus the parts of infra/firestore.rules that matter:
owner-only access and append-only reviews/attempts. Tokens are fake: Google sign-in yields
id token "good-<uid>", refresh token "rt-<uid>" trades for access token "id-<uid>"."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.cloud.firestore import decode_fields, encode_fields

PROJECT = "test-project"
ROOT = f"projects/{PROJECT}/databases/(default)/documents"
APPEND_ONLY = re.compile(rf"^{re.escape(ROOT)}/users/[^/]+/(reviews|attempts)/[^/]+$")


class FakeFirestore:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self._clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.writes = 0

    # --- helpers for tests --------------------------------------------------------------

    def now(self) -> str:
        self._clock += timedelta(milliseconds=1)
        return self._clock.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def path(self, p: str) -> str:
        return f"{ROOT}/{p}"

    def get(self, p: str) -> dict | None:
        d = self.docs.get(self.path(p))
        return decode_fields(d["fields"]) if d else None

    def collection(self, uid: str, coll: str) -> dict[str, dict]:
        prefix = self.path(f"users/{uid}/{coll}/")
        return {n[len(prefix):]: decode_fields(d["fields"]) for n, d in self.docs.items()
                if n.startswith(prefix) and "/" not in n[len(prefix):]}

    def phone_write(self, p: str, fields: dict) -> None:
        """Write the way StudyDeck does: plain fields plus a server-time syncedAt."""
        t = self.now()
        enc = encode_fields(fields)
        enc["syncedAt"] = {"timestampValue": t}
        old = self.docs.get(self.path(p))
        self.docs[self.path(p)] = {"name": self.path(p), "fields": enc, "updateTime": t,
                                   "createTime": old["createTime"] if old else t}

    # --- transport ----------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        body = json.loads(req.content or b"{}") if req.headers.get("content-type", "").startswith("application/json") else {}
        if "accounts:lookup" in url:
            tok = body.get("idToken", "")
            if not tok.startswith("good-"):
                return httpx.Response(400, json={"error": {"message": "INVALID_ID_TOKEN"}})
            uid = tok[5:]
            return httpx.Response(200, json={"users": [{"localId": uid, "email": f"{uid}@example.com"}]})
        if "securetoken" in url:
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            rt = form.get("refresh_token", "")
            if not rt.startswith("rt-"):
                return httpx.Response(400, json={"error": {"message": "INVALID_REFRESH_TOKEN"}})
            return httpx.Response(200, json={"id_token": f"id-{rt[3:]}", "expires_in": "3600", "refresh_token": rt})

        auth = req.headers.get("authorization", "")
        if not auth.startswith("Bearer id-"):
            return httpx.Response(401, json={"error": "unauthenticated"})
        uid = auth[len("Bearer id-"):]
        owned = f"{ROOT}/users/{uid}/"
        if url.endswith(":batchWrite"):
            return httpx.Response(200, json={"status": [self._write(w, owned) for w in body["writes"]]})
        if url.endswith(":batchGet"):
            out = []
            for n in body["documents"]:
                if not n.startswith(owned):
                    return httpx.Response(403, json={"error": "denied"})
                out.append({"found": self.docs[n]} if n in self.docs else {"missing": n})
            return httpx.Response(200, json=out)
        if url.endswith(":runQuery"):
            parent = url.split("/v1/", 1)[1].rsplit(":", 1)[0]
            if not (parent + "/").startswith(owned):
                return httpx.Response(403, json={"error": "denied"})
            return httpx.Response(200, json=self._query(parent, body["structuredQuery"]))
        return httpx.Response(404, json={"error": f"fake doesn't handle {url}"})

    def _write(self, w: dict, owned: str) -> dict:
        name = w["update"]["name"] if "update" in w else w["delete"]
        if not name.startswith(owned):
            return {"code": 7}
        cur = self.docs.get(name)
        pre = w.get("currentDocument", {})
        if pre.get("exists") is False and cur:
            return {"code": 6}
        if "updateTime" in pre and (not cur or cur["updateTime"] != pre["updateTime"]):
            return {"code": 9}
        if cur and APPEND_ONLY.match(name):
            return {"code": 7}  # rules: create only
        self.writes += 1
        if "delete" in w:
            self.docs.pop(name, None)
            return {"code": 0}
        t = self.now()
        fields = dict(w["update"]["fields"])
        for tr in w.get("updateTransforms", []):
            fields[tr["fieldPath"]] = {"timestampValue": t}
        self.docs[name] = {"name": name, "fields": fields, "updateTime": t,
                           "createTime": cur["createTime"] if cur else t}
        return {"code": 0}

    def _query(self, parent: str, q: dict) -> list[dict]:
        coll = q["from"][0]["collectionId"]
        prefix = f"{parent}/{coll}/"
        docs = [d for n, d in self.docs.items() if n.startswith(prefix) and "/" not in n[len(prefix):]]
        field = q["orderBy"][0]["field"]["fieldPath"]
        key = lambda d: d["fields"][field]["timestampValue"]  # noqa: E731 (fixed-width UTC strings sort)
        if "where" in q:
            after = q["where"]["fieldFilter"]["value"]["timestampValue"]
            docs = [d for d in docs if key(d) > after]
        docs.sort(key=key)
        return [{"document": d, "readTime": self.now()} for d in docs] or [{"readTime": self.now()}]
