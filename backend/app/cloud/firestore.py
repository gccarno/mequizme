"""Minimal Firestore REST client. Requests carry the user's Firebase ID token, so the same
security rules apply as for the phone; no service account involved.

Only what sync needs: batchWrite (independent writes, each with its own precondition),
runQuery on one collection, and batchGet."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import httpx

API = "https://firestore.googleapis.com/v1"
BATCH = 500  # Firestore's per-request write limit
OK, ALREADY_EXISTS, FAILED_PRECONDITION = 0, 6, 9  # gRPC status codes in batchWrite results


class FirestoreError(RuntimeError):
    pass


# --- value codec ---------------------------------------------------------------------------

def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def encode(v: Any) -> dict:
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, datetime):
        return {"timestampValue": ts(v)}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [encode(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": encode_fields(v)}}
    raise TypeError(f"can't store {type(v).__name__} in Firestore")


def decode(v: dict) -> Any:
    ((kind, x),) = v.items()
    if kind == "integerValue":
        return int(x)
    if kind == "timestampValue":
        return parse_ts(x)
    if kind == "arrayValue":
        return [decode(i) for i in x.get("values", [])]
    if kind == "mapValue":
        return decode_fields(x.get("fields", {}))
    return x  # null, boolean, double, string


def encode_fields(d: dict) -> dict:
    return {k: encode(v) for k, v in d.items()}


def decode_fields(fields: dict) -> dict:
    return {k: decode(v) for k, v in fields.items()}


# --- client --------------------------------------------------------------------------------

class Firestore:
    def __init__(self, http: httpx.Client, project: str, token: Callable[[], str]):
        self.http, self.token = http, token
        self.root = f"projects/{project}/databases/(default)/documents"

    def name(self, path: str) -> str:
        return f"{self.root}/{path}"

    def _post(self, url: str, body: dict) -> Any:
        r = self.http.post(f"{API}/{url}", json=body, timeout=60,
                           headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code >= 400:
            raise FirestoreError(f"Firestore {r.status_code}: {r.text[:300]}")
        return r.json()

    @staticmethod
    def set(name: str, fields: dict, *, server_time: str | None = None, exists: bool | None = None,
            update_time: str | None = None) -> dict:
        """A full-document write. `server_time` names a field set to the commit time;
        `exists`/`update_time` make it conditional."""
        w: dict = {"update": {"name": name, "fields": encode_fields(fields)}}
        if server_time:
            w["updateTransforms"] = [{"fieldPath": server_time, "setToServerValue": "REQUEST_TIME"}]
        if exists is not None:
            w["currentDocument"] = {"exists": exists}
        elif update_time:
            w["currentDocument"] = {"updateTime": update_time}
        return w

    @staticmethod
    def delete(name: str) -> dict:
        return {"delete": name}

    def batch_write(self, writes: list[dict]) -> list[int]:
        """Apply writes independently: one failed precondition doesn't sink the others.
        Returns a gRPC status code per write (OK, or FAILED_PRECONDITION etc.)."""
        codes: list[int] = []
        for i in range(0, len(writes), BATCH):
            res = self._post(f"{self.root}:batchWrite", {"writes": writes[i:i + BATCH]})
            codes += [s.get("code", OK) for s in res.get("status", [])]
        return codes

    def query_since(self, parent: str, collection: str, field: str, after: str | None) -> list[dict]:
        """Docs in parent/collection whose `field` (a server timestamp) is > after, oldest first.
        All writes of one commit share a timestamp and become visible together, so `>` on the
        largest value seen never skips a document."""
        q: dict = {"from": [{"collectionId": collection}],
                   "orderBy": [{"field": {"fieldPath": field}, "direction": "ASCENDING"}]}
        if after:
            q["where"] = {"fieldFilter": {"field": {"fieldPath": field}, "op": "GREATER_THAN",
                                          "value": {"timestampValue": after}}}
        rows = self._post(f"{self.name(parent)}:runQuery", {"structuredQuery": q})
        return [r["document"] for r in rows if "document" in r]

    def batch_get(self, names: Iterable[str]) -> dict[str, dict | None]:
        names = list(names)
        out: dict[str, dict | None] = {}
        for i in range(0, len(names), 300):
            for r in self._post(f"{self.root}:batchGet", {"documents": names[i:i + 300]}):
                if "found" in r:
                    out[r["found"]["name"]] = r["found"]
                elif "missing" in r:
                    out[r["missing"]] = None
        return out
