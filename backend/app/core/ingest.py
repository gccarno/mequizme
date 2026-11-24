"""Load pack files from the content directory into SQLite (upsert by id)."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.core.db import dumps
from app.core.schema import StudyPack, utcnow

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    packs: int = 0
    items: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def ingest_pack(conn: sqlite3.Connection, pack: StudyPack, path: str) -> int:
    doc = json.loads(pack.model_dump_json(exclude_none=True))
    items = doc.pop("items")
    conn.execute(
        """INSERT INTO packs (id, name, exam, path, body, ingested_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, exam=excluded.exam, path=excluded.path,
             body=excluded.body, ingested_at=excluded.ingested_at""",
        (pack.id, pack.name, pack.taxonomy.exam, path, dumps(doc), utcnow().isoformat()),
    )
    ids = [it["id"] for it in items]
    conn.execute(
        f"DELETE FROM items WHERE pack_id = ? AND id NOT IN ({','.join('?' * len(ids))})",
        (pack.id, *ids),
    )
    conn.executemany(
        """INSERT INTO items (id, pack_id, position, type, status, topics, body) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET pack_id=excluded.pack_id, position=excluded.position,
             type=excluded.type, status=excluded.status, topics=excluded.topics, body=excluded.body""",
        [
            (it["id"], pack.id, pos, it["type"], it.get("status", "reviewed"), dumps(it.get("topics", [])), dumps(it))
            for pos, it in enumerate(items)
        ],
    )
    return len(items)


def ingest_dir(conn: sqlite3.Connection, content_dir: Path) -> IngestReport:
    report = IngestReport()
    seen: list[str] = []
    for f in sorted(content_dir.rglob("*.json")):
        rel = f.relative_to(content_dir).as_posix()
        try:
            pack = StudyPack.from_json(f.read_text(encoding="utf-8"))
        except (ValidationError, ValueError) as e:
            report.errors[rel] = str(e)
            log.warning("skipping %s: %s", rel, e)
            continue
        report.items += ingest_pack(conn, pack, rel)
        report.packs += 1
        seen.append(pack.id)
    # Packs whose files were removed disappear; progress rows stay (keyed by item id).
    if seen:
        conn.execute(f"DELETE FROM packs WHERE id NOT IN ({','.join('?' * len(seen))})", seen)
    else:
        conn.execute("DELETE FROM packs")
    return report
