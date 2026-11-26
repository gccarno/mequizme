"""Cloud sync against an in-memory Firestore: web <-> phone merge rules (docs/sync.md)."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.db import Database
from app.main import create_app
from fake_firestore import PROJECT, FakeFirestore

UID = "alice"
SECTION1 = "0e9ec33c-58a4-5c37-8b1c-f74b08d26523"


@pytest.fixture
def fake():
    return FakeFirestore()


@pytest.fixture
def make_client(tmp_path, content, fake, monkeypatch):
    monkeypatch.setenv("MEQUIZME_FIREBASE_API_KEY", "test-key")
    monkeypatch.setenv("MEQUIZME_FIREBASE_PROJECT", PROJECT)
    opened = []

    def make(name="t.db"):
        app = create_app(content_dir=content, db_path=tmp_path / name, static_dir=tmp_path / "none", llm=None,
                         cloud_http=httpx.Client(transport=fake.transport()))
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def web(make_client):
    c = make_client()
    r = c.post("/api/cloud/session", json={"idToken": f"good-{UID}", "refreshToken": f"rt-{UID}"})
    assert r.status_code == 200 and r.json()["connected"]
    return c


def _sync(c) -> dict:
    r = c.post("/api/cloud/sync")
    assert r.status_code == 200, r.text
    return r.json()


def _card(c) -> dict:
    return c.get("/api/study/queue", params={"exam": "aws-dva-c02", "newLimit": 1}).json()["cards"][0]


def _db(c) -> sqlite3.Connection:
    conn = sqlite3.connect(c.app.state.db.path)
    conn.row_factory = sqlite3.Row
    return conn


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# --- session --------------------------------------------------------------------------------

def test_not_configured(tmp_path, content, monkeypatch):
    monkeypatch.delenv("MEQUIZME_FIREBASE_API_KEY", raising=False)
    app = create_app(content_dir=content, db_path=tmp_path / "x.db", static_dir=tmp_path / "none", llm=None)
    with TestClient(app) as c:
        assert c.get("/api/cloud/status").json()["configured"] is False
        assert c.post("/api/cloud/sync").status_code == 409


def test_bad_token_rejected(make_client):
    c = make_client()
    assert c.post("/api/cloud/session", json={"idToken": "forged", "refreshToken": "rt-x"}).status_code == 401
    assert c.get("/api/cloud/status").json()["connected"] is False


def test_sync_requires_sign_in(make_client):
    assert make_client().post("/api/cloud/sync").status_code == 409


def test_disconnect(web):
    assert web.delete("/api/cloud/session").status_code == 204
    assert web.get("/api/cloud/status").json()["connected"] is False


# --- push -----------------------------------------------------------------------------------

def test_push_content_reviews_and_schedule(web, fake):
    card = _card(web)
    web.post("/api/study/review", json={"itemId": card["id"], "rating": 3})
    rep = _sync(web)
    assert rep["pushed"]["reviews"] == 1 and rep["pushed"]["srs"] == 1
    assert rep["pushed"]["content"] > 100
    assert rep["status"]["pending"] == 0 and rep["status"]["lastError"] is None

    reviews = fake.collection(UID, "reviews")
    (rev,) = reviews.values()
    assert rev["itemId"] == card["id"] and rev["rating"] == 3 and rev["device"] == "web"
    srs = fake.get(f"users/{UID}/srs/{card['id']}")
    assert srs["scheduler"] == "fsrs" and json.loads(srs["state"])["stability"] > 0

    packs = fake.collection(UID, "packs")
    assert SECTION1 in packs and json.loads(packs[SECTION1]["body"])["name"]
    items = fake.collection(UID, f"packs/{_pack_of(web, card['id'])}/items")
    assert card["id"] in items and json.loads(items[card["id"]]["body"])["id"] == card["id"]


def _pack_of(c, item_id):
    with _db(c) as conn:
        return conn.execute("SELECT pack_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def test_second_sync_is_a_no_op(web, fake):
    _sync(web)
    writes = fake.writes
    rep = _sync(web)
    assert rep["pushed"] == {"content": 0, "reviews": 0, "srs": 0, "attempts": 0}
    assert rep["pulled"] == {"reviews": 0, "srs": 0, "attempts": 0}
    assert fake.writes == writes


def test_changed_item_bumps_its_pack(web, fake):
    _sync(web)
    card = _card(web)
    pack = _pack_of(web, card["id"])
    before = fake.get(f"users/{UID}/packs/{pack}")["itemsHash"]
    others = {p: d["itemsHash"] for p, d in fake.collection(UID, "packs").items() if p != pack}
    with _db(web) as conn:
        body = json.loads(conn.execute("SELECT body FROM items WHERE id = ?", (card["id"],)).fetchone()[0])
        body["prompt"] += " (edited)"
        conn.execute("UPDATE items SET body = ? WHERE id = ?", (json.dumps(body), card["id"]))
    assert _sync(web)["pushed"]["content"] == 2  # the item, then its pack
    assert fake.get(f"users/{UID}/packs/{pack}")["itemsHash"] != before
    assert {p: d["itemsHash"] for p, d in fake.collection(UID, "packs").items() if p != pack} == others


def test_pack_not_advertised_until_its_items_land(web, fake, monkeypatch):
    real = fake._write
    monkeypatch.setattr(fake, "_write", lambda w, owned: {"code": 14} if "/items/" in w.get("update", {}).get("name", "") else real(w, owned))
    _sync(web)
    assert fake.collection(UID, "packs") == {}
    monkeypatch.setattr(fake, "_write", real)
    _sync(web)
    assert len(fake.collection(UID, "packs")) == 9


def test_drafts_are_not_published(web, fake):
    _sync(web)
    with _db(web) as conn:
        drafts = {r[0] for r in conn.execute("SELECT id FROM items WHERE status = 'draft'")}
    pushed = {n.rsplit("/", 1)[1] for n in fake.docs if "/items/" in n}
    assert pushed and not (drafts & pushed)


# --- pull from the phone --------------------------------------------------------------------

def _phone_review(fake, item_id, rating, when, state=None, due=None):
    rid = str(uuid.uuid4())
    fake.phone_write(f"users/{UID}/reviews/{rid}", {
        "id": rid, "itemId": item_id, "rating": rating, "source": "flashcard",
        "reviewedAt": when, "durationMs": 1200, "device": "android"})
    fake.phone_write(f"users/{UID}/srs/{item_id}", {
        "itemId": item_id, "scheduler": "fsrs",
        "state": json.dumps(state or {"card_id": 1, "state": 2, "step": None, "stability": 9.5,
                                      "difficulty": 4.0, "due": _iso(due), "last_review": _iso(when)}),
        "due": due, "lastReviewedAt": when, "device": "android"})
    return rid


def test_pull_phone_review_and_schedule(web, fake):
    card = _card(web)
    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    due = when + timedelta(days=9)
    rid = _phone_review(fake, card["id"], 3, when, due=due)

    rep = _sync(web)
    assert rep["pulled"]["reviews"] == 1 and rep["pulled"]["srs"] == 1
    with _db(web) as conn:
        r = conn.execute("SELECT * FROM reviews WHERE uuid = ?", (rid,)).fetchone()
        assert r["device"] == "android" and r["synced"] == 1
        s = conn.execute("SELECT * FROM srs_state WHERE item_id = ?", (card["id"],)).fetchone()
        assert datetime.fromisoformat(s["due"]) == due and s["dirty"] == 0
    # the card is scheduled now, so it's no longer offered as new
    assert _card(web)["id"] != card["id"]
    # and nothing is echoed back up
    assert _sync(web)["pushed"]["reviews"] == 0


def test_newer_phone_review_wins_over_local(web, fake):
    card = _card(web)
    web.post("/api/study/review", json={"itemId": card["id"], "rating": 1})  # local, now
    later = datetime.now(timezone.utc) + timedelta(minutes=1)
    _phone_review(fake, card["id"], 4, later, due=later + timedelta(days=20))

    _sync(web)
    with _db(web) as conn:
        s = conn.execute("SELECT * FROM srs_state WHERE item_id = ?", (card["id"],)).fetchone()
        assert datetime.fromisoformat(s["last_reviewed_at"]) == later and s["dirty"] == 0
        assert conn.execute("SELECT COUNT(*) FROM reviews WHERE item_id = ?", (card["id"],)).fetchone()[0] == 2
    assert fake.get(f"users/{UID}/srs/{card['id']}")["device"] == "android"  # not overwritten
    assert len(fake.collection(UID, "reviews")) == 2  # both reviews kept in the log


def test_newer_local_review_wins_over_phone(web, fake):
    card = _card(web)
    earlier = datetime.now(timezone.utc) - timedelta(hours=1)
    _phone_review(fake, card["id"], 4, earlier, due=earlier + timedelta(days=20))
    web.post("/api/study/review", json={"itemId": card["id"], "rating": 1})

    _sync(web)
    srs = fake.get(f"users/{UID}/srs/{card['id']}")
    assert srs["device"] == "web" and srs["lastReviewedAt"] > earlier
    with _db(web) as conn:
        s = conn.execute("SELECT * FROM srs_state WHERE item_id = ?", (card["id"],)).fetchone()
        assert s["dirty"] == 0 and datetime.fromisoformat(s["last_reviewed_at"]) > earlier


def test_two_web_installs_converge(make_client, fake):
    a, b = make_client("a.db"), make_client("b.db")
    for c in (a, b):
        c.post("/api/cloud/session", json={"idToken": f"good-{UID}", "refreshToken": f"rt-{UID}"})
    card = _card(a)
    a.post("/api/study/review", json={"itemId": card["id"], "rating": 3})
    _sync(a)
    _sync(b)
    with _db(a) as ca, _db(b) as cb:
        q = "SELECT scheduler, state, due FROM srs_state WHERE item_id = ?"
        assert dict(ca.execute(q, (card["id"],)).fetchone()) == dict(cb.execute(q, (card["id"],)).fetchone())


# --- attempts -------------------------------------------------------------------------------

def test_attempts_push_and_local_delete_sticks(web, fake):
    att = web.post("/api/attempts", json={"packId": SECTION1}).json()
    iid = att["items"][0]["item"]["id"]
    web.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["B"], "confidence": 3})
    web.post(f"/api/attempts/{att['id']}/submit")
    assert _sync(web)["pushed"]["attempts"] == 1
    body = json.loads(fake.get(f"users/{UID}/attempts/{att['id']}")["body"])
    assert body["attempt"]["total"] == 10 and body["responses"][0]["choiceIds"] == ["B"]

    web.delete(f"/api/attempts/{att['id']}")
    _sync(web)
    assert all(h["id"] != att["id"] for h in web.get("/api/attempts").json())


def test_unsubmitted_attempts_stay_local(web, fake):
    web.post("/api/attempts", json={"packId": SECTION1})
    _sync(web)
    assert fake.collection(UID, "attempts") == {}


def test_pull_phone_attempt(web, fake):
    with _db(web) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM items WHERE pack_id = ? ORDER BY position", (SECTION1,))]
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake.phone_write(f"users/{UID}/attempts/{aid}", {
        "id": aid, "exam": "databricks-ml-associate", "packId": SECTION1, "mode": "practice",
        "submittedAt": now, "score": 1, "total": 2, "device": "android",
        "body": json.dumps({
            "attempt": {"id": aid, "name": "Phone practice", "mode": "practice", "packId": SECTION1,
                        "quizId": None, "exam": "databricks-ml-associate", "itemIds": ids[:2],
                        "startedAt": _iso(now - timedelta(minutes=3)), "deadlineAt": None,
                        "submittedAt": _iso(now), "score": 1, "total": 2},
            "responses": [{"itemId": ids[0], "choiceIds": ["B"], "text": None, "correct": True, "flagged": False,
                           "confidence": 3, "timeMs": 5000, "answeredAt": _iso(now)}]})})
    assert _sync(web)["pulled"]["attempts"] == 1
    got = web.get(f"/api/attempts/{aid}").json()
    assert got["name"] == "Phone practice" and got["score"] == 1
    assert _sync(web)["pushed"]["attempts"] == 0  # not echoed back


# --- security & accounts --------------------------------------------------------------------

def test_cannot_touch_another_users_data(web, fake):
    fake.phone_write("users/bob/reviews/x", {"id": "x", "itemId": "i", "rating": 3, "source": "flashcard",
                                              "reviewedAt": datetime.now(timezone.utc), "device": "android"})
    _sync(web)
    with _db(web) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews WHERE uuid = 'x'").fetchone()[0] == 0
    assert all(n.startswith(fake.path(f"users/{UID}/")) or "/users/bob/" in n for n in fake.docs)


def test_switching_accounts_pushes_everything_again(web, fake):
    card = _card(web)
    web.post("/api/study/review", json={"itemId": card["id"], "rating": 3})
    _sync(web)
    web.post("/api/cloud/session", json={"idToken": "good-bob", "refreshToken": "rt-bob"})
    rep = _sync(web)
    assert rep["pushed"]["reviews"] == 1 and rep["pushed"]["content"] > 100
    assert len(fake.collection("bob", "reviews")) == 1


# --- migration ------------------------------------------------------------------------------

def test_migrates_pre_sync_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, rating INTEGER NOT NULL,
                              source TEXT NOT NULL, reviewed_at TEXT NOT NULL, duration_ms INTEGER);
        CREATE TABLE srs_state (item_id TEXT PRIMARY KEY, scheduler TEXT NOT NULL, state TEXT NOT NULL, due TEXT NOT NULL);
        INSERT INTO reviews (item_id, rating, source, reviewed_at) VALUES
            ('i1', 3, 'flashcard', '2026-01-01T00:00:00+00:00'), ('i1', 4, 'flashcard', '2026-01-03T00:00:00+00:00');
        INSERT INTO srs_state VALUES ('i1', 'fsrs', '{}', '2026-02-01T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()

    Database(path)
    Database(path)  # idempotent
    with Database(path).connect() as conn:
        uuids = [r[0] for r in conn.execute("SELECT uuid FROM reviews")]
        assert len(set(uuids)) == 2 and all(uuids)
        s = conn.execute("SELECT last_reviewed_at, dirty FROM srs_state").fetchone()
        assert s["last_reviewed_at"] == "2026-01-03T00:00:00+00:00" and s["dirty"] == 1
