"""Two-way sync between the local SQLite DB and users/{uid}/ in Firestore.

Data model and merge rules: docs/sync.md. In short:
  packs, items   web -> cloud, skipped when the content hash is unchanged
  reviews        append-only union keyed by uuid
  srs            per item, the schedule with the later lastReviewedAt wins
  attempts       submitted attempts, create-only
Pulls are incremental on `syncedAt`, a server timestamp every writer sets.

Network calls happen outside DB transactions so the app stays responsive during a sync.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from app.cloud.firestore import ALREADY_EXISTS, FAILED_PRECONDITION, OK, Firestore, decode_fields, parse_ts
from app.core.db import Database
from app.core.scheduler import apply_remote_srs, now_utc

DEVICE = "web"
_DONE_CREATE = {OK, ALREADY_EXISTS, FAILED_PRECONDITION}  # create-only write landed, now or earlier


@dataclass
class SyncReport:
    pushed: dict = field(default_factory=dict)
    pulled: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _hash(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def _get_meta(db: Database, key: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(db: Database, key: str, value: str | None) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO sync_meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _created(fs: Firestore, names: list[str], codes: list[int]) -> list[bool]:
    """Which create-only writes are in the cloud. A permission error can mean the doc already
    exists (the rules forbid updating it), so check those directly instead of retrying forever."""
    done = [c in _DONE_CREATE for c in codes]
    unsure = [n for n, d in zip(names, done) if not d]
    if unsure:
        found = fs.batch_get(unsure)
        done = [d or found.get(n) is not None for n, d in zip(names, done)]
    return done


# --- push ----------------------------------------------------------------------------------

def push_content(db: Database, fs: Firestore, uid: str) -> int:
    docs: dict[str, dict] = {}
    with db.connect() as conn:
        for p in conn.execute("SELECT id, name, exam, body FROM packs"):
            docs[f"users/{uid}/packs/{p['id']}"] = {"id": p["id"], "name": p["name"], "exam": p["exam"],
                                                    "body": p["body"]}
        for i in conn.execute("SELECT id, pack_id, position, type, topics, body FROM items WHERE status != 'draft'"):
            docs[f"users/{uid}/packs/{i['pack_id']}/items/{i['id']}"] = {
                "id": i["id"], "packId": i["pack_id"], "position": i["position"], "type": i["type"],
                "topics": json.loads(i["topics"]), "body": i["body"]}
        known = {r["path"]: r["hash"] for r in conn.execute("SELECT path, hash FROM cloud_content")}

    hashes = {path: _hash(f) for path, f in docs.items()}
    changed = [p for p in docs if known.get(p) != hashes[p]]
    gone = [p for p in known if p.startswith(f"users/{uid}/") and p not in docs]
    writes = [Firestore.set(fs.name(p), {**docs[p], "contentHash": hashes[p]}) for p in changed]
    writes += [Firestore.delete(fs.name(p)) for p in gone]
    if not writes:
        return 0
    codes = fs.batch_write(writes)
    with db.connect() as conn:
        for p, code in zip(changed + gone, codes):
            if code != OK:
                continue
            if p in docs:
                conn.execute("INSERT INTO cloud_content (path, hash) VALUES (?, ?) "
                             "ON CONFLICT(path) DO UPDATE SET hash = excluded.hash", (p, hashes[p]))
            else:
                conn.execute("DELETE FROM cloud_content WHERE path = ?", (p,))
    return sum(c == OK for c in codes)


def push_reviews(db: Database, fs: Firestore, uid: str) -> int:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM reviews WHERE synced = 0 ORDER BY id").fetchall()
    if not rows:
        return 0
    names = [fs.name(f"users/{uid}/reviews/{r['uuid']}") for r in rows]
    writes = [Firestore.set(n, {
        "id": r["uuid"], "itemId": r["item_id"], "rating": r["rating"], "source": r["source"],
        "reviewedAt": parse_ts(r["reviewed_at"]), "durationMs": r["duration_ms"], "device": r["device"] or DEVICE,
    }, server_time="syncedAt", exists=False) for n, r in zip(names, rows)]
    done = _created(fs, names, fs.batch_write(writes))
    with db.connect() as conn:
        conn.executemany("UPDATE reviews SET synced = 1 WHERE id = ?",
                         [(r["id"],) for r, d in zip(rows, done) if d])
    return sum(done)


def _srs_fields(row) -> dict:
    return {"itemId": row["item_id"], "scheduler": row["scheduler"], "state": row["state"],
            "due": parse_ts(row["due"]), "lastReviewedAt": parse_ts(row["last_reviewed_at"]), "device": DEVICE}


def _apply_srs_doc(conn, fields: dict) -> bool:
    return apply_remote_srs(conn, fields["itemId"], fields["scheduler"], json.loads(fields["state"]),
                            fields["due"], fields["lastReviewedAt"])


def push_srs(db: Database, fs: Firestore, uid: str) -> int:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM srs_state WHERE dirty = 1").fetchall()
    if not rows:
        return 0
    names = [fs.name(f"users/{uid}/srs/{r['item_id']}") for r in rows]
    remote = fs.batch_get(names)
    writes, pending = [], []
    with db.connect() as conn:
        for name, row in zip(names, rows):
            doc = remote.get(name)
            if doc is None:
                writes.append(Firestore.set(name, _srs_fields(row), server_time="syncedAt", exists=False))
                pending.append(row)
                continue
            theirs = decode_fields(doc["fields"])
            if theirs["lastReviewedAt"] >= parse_ts(row["last_reviewed_at"]):
                _apply_srs_doc(conn, theirs)  # theirs is newer, or the same review: take it, stop pushing
                conn.execute("UPDATE srs_state SET dirty = 0 WHERE item_id = ? AND last_reviewed_at = ?",
                             (row["item_id"], row["last_reviewed_at"]))
            else:
                # Only overwrite the version we just compared against; if the phone wrote in
                # between, the precondition fails and the next sync re-decides.
                writes.append(Firestore.set(name, _srs_fields(row), server_time="syncedAt",
                                            update_time=doc["updateTime"]))
                pending.append(row)
    if not writes:
        return 0
    codes = fs.batch_write(writes)
    with db.connect() as conn:
        for row, code in zip(pending, codes):
            if code == OK:  # a review since we read the row keeps it dirty
                conn.execute("UPDATE srs_state SET dirty = 0 WHERE item_id = ? AND last_reviewed_at = ?",
                             (row["item_id"], row["last_reviewed_at"]))
    return sum(c == OK for c in codes)


def attempt_body(conn, att) -> dict:
    responses = conn.execute("SELECT * FROM responses WHERE attempt_id = ?", (att["id"],)).fetchall()
    return {
        "attempt": {"id": att["id"], "name": att["name"], "mode": att["mode"], "packId": att["pack_id"],
                    "quizId": att["quiz_id"], "exam": att["exam"], "itemIds": json.loads(att["item_ids"]),
                    "startedAt": att["started_at"], "deadlineAt": att["deadline_at"],
                    "submittedAt": att["submitted_at"], "score": att["score"], "total": att["total"]},
        "responses": [{"itemId": r["item_id"], "choiceIds": json.loads(r["choice_ids"]) if r["choice_ids"] else None,
                       "text": r["text"], "correct": None if r["correct"] is None else bool(r["correct"]),
                       "flagged": bool(r["flagged"]), "confidence": r["confidence"], "timeMs": r["time_ms"],
                       "answeredAt": r["answered_at"]} for r in responses],
    }


def push_attempts(db: Database, fs: Firestore, uid: str) -> int:
    with db.connect() as conn:
        atts = conn.execute(
            """SELECT * FROM attempts WHERE submitted_at IS NOT NULL
               AND id NOT IN (SELECT id FROM cloud_attempts)""").fetchall()
        bodies = [attempt_body(conn, a) for a in atts]
    if not atts:
        return 0
    names = [fs.name(f"users/{uid}/attempts/{a['id']}") for a in atts]
    writes = [Firestore.set(n, {
        "id": a["id"], "exam": a["exam"], "packId": a["pack_id"], "mode": a["mode"],
        "submittedAt": parse_ts(a["submitted_at"]), "score": a["score"], "total": a["total"],
        "device": DEVICE, "body": json.dumps(b, ensure_ascii=False),
    }, server_time="syncedAt", exists=False) for n, a, b in zip(names, atts, bodies)]
    done = _created(fs, names, fs.batch_write(writes))
    with db.connect() as conn:
        conn.executemany("INSERT OR IGNORE INTO cloud_attempts (id) VALUES (?)",
                         [(a["id"],) for a, d in zip(atts, done) if d])
    return sum(done)


# --- pull ----------------------------------------------------------------------------------

def _pull(db: Database, fs: Firestore, uid: str, collection: str) -> list[dict]:
    """Raw docs written since this collection's cursor; call _advance once they're stored."""
    return fs.query_since(f"users/{uid}", collection, "syncedAt", _get_meta(db, f"cursor.{collection}"))


def _advance(db: Database, collection: str, docs: list[dict]) -> None:
    if docs:  # raw string keeps Firestore's full nanosecond precision
        set_meta(db, f"cursor.{collection}", docs[-1]["fields"]["syncedAt"]["timestampValue"])


def pull_reviews(db: Database, fs: Firestore, uid: str) -> int:
    docs = _pull(db, fs, uid, "reviews")
    added = 0
    with db.connect() as conn:
        for d in docs:
            f = decode_fields(d["fields"])
            cur = conn.execute(
                """INSERT OR IGNORE INTO reviews (uuid, item_id, rating, source, reviewed_at, duration_ms, device, synced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (f["id"], f["itemId"], f["rating"], f["source"], f["reviewedAt"].isoformat(),
                 f.get("durationMs"), f.get("device")))
            added += cur.rowcount
    _advance(db, "reviews", docs)
    return added


def pull_srs(db: Database, fs: Firestore, uid: str) -> int:
    docs = _pull(db, fs, uid, "srs")
    applied = 0
    with db.connect() as conn:
        for d in docs:
            applied += _apply_srs_doc(conn, decode_fields(d["fields"]))
    _advance(db, "srs", docs)
    return applied


def pull_attempts(db: Database, fs: Firestore, uid: str) -> int:
    docs = _pull(db, fs, uid, "attempts")
    added = 0
    with db.connect() as conn:
        for d in docs:
            body = json.loads(decode_fields(d["fields"])["body"])
            a = body["attempt"]
            seen = conn.execute("SELECT 1 FROM cloud_attempts WHERE id = ?", (a["id"],)).fetchone()
            conn.execute("INSERT OR IGNORE INTO cloud_attempts (id) VALUES (?)", (a["id"],))
            if seen or conn.execute("SELECT 1 FROM attempts WHERE id = ?", (a["id"],)).fetchone():
                continue  # ours, or deleted here after syncing
            conn.execute(
                """INSERT INTO attempts (id, name, mode, pack_id, quiz_id, exam, item_ids, started_at,
                                         deadline_at, submitted_at, score, total)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (a["id"], a["name"], a["mode"], a.get("packId"), a.get("quizId"), a.get("exam"),
                 json.dumps(a["itemIds"]), a["startedAt"], a.get("deadlineAt"), a["submittedAt"],
                 a.get("score"), a["total"]))
            for r in body.get("responses", []):
                conn.execute(
                    """INSERT INTO responses (attempt_id, item_id, choice_ids, text, correct, flagged,
                                              confidence, time_ms, answered_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (a["id"], r["itemId"], None if r.get("choiceIds") is None else json.dumps(r["choiceIds"]),
                     r.get("text"), None if r.get("correct") is None else int(r["correct"]),
                     int(bool(r.get("flagged"))), r.get("confidence"), r.get("timeMs"), r.get("answeredAt")))
            added += 1
    _advance(db, "attempts", docs)
    return added


def sync_once(db: Database, fs: Firestore, uid: str) -> SyncReport:
    rep = SyncReport()
    rep.pushed["content"] = push_content(db, fs, uid)
    rep.pushed["reviews"] = push_reviews(db, fs, uid)
    rep.pushed["srs"] = push_srs(db, fs, uid)
    rep.pushed["attempts"] = push_attempts(db, fs, uid)
    rep.pulled["reviews"] = pull_reviews(db, fs, uid)
    rep.pulled["srs"] = pull_srs(db, fs, uid)
    rep.pulled["attempts"] = pull_attempts(db, fs, uid)
    set_meta(db, "last_sync", now_utc().isoformat())
    return rep
