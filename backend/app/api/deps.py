from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

from fastapi import HTTPException, Request


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    with request.app.state.db.connect() as conn:
        yield conn


def load_item(conn: sqlite3.Connection, item_id: str) -> dict:
    row = conn.execute("SELECT body FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"item {item_id} not found")
    return json.loads(row["body"])


def load_items(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT i.body, i.pack_id, p.name AS pack_name FROM items i JOIN packs p ON p.id = i.pack_id "
        f"WHERE i.id IN ({','.join('?' * len(ids))})",
        ids,
    ).fetchall()
    out = {}
    for r in rows:
        body = json.loads(r["body"])
        body["packId"], body["packName"] = r["pack_id"], r["pack_name"]
        out[body["id"]] = body
    return out


def topic_names(conn: sqlite3.Connection, pack_ids: set[str] | None = None) -> dict[str, str]:
    """topic id -> name, merged across pack taxonomies."""
    q, args = "SELECT body FROM packs", ()
    if pack_ids:
        q += f" WHERE id IN ({','.join('?' * len(pack_ids))})"
        args = tuple(pack_ids)
    names: dict[str, str] = {}
    for r in conn.execute(q, args):
        for t in json.loads(r["body"]).get("taxonomy", {}).get("topics", []):
            names.setdefault(t["id"], t["name"])
    return names
