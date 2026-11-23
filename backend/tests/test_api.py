from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import quiz as quiz_api
from app.main import create_app

CONTENT = Path(__file__).resolve().parents[2] / "content"
SECTION1 = "0e9ec33c-58a4-5c37-8b1c-f74b08d26523"
SECTION1_KEYS = "B D A B C D D A C B".split()


@pytest.fixture
def client(tmp_path):
    app = create_app(content_dir=CONTENT, db_path=tmp_path / "t.db", static_dir=tmp_path / "none")
    with TestClient(app) as c:
        yield c


def _section1(client):
    return next(p for p in client.get("/api/packs").json() if p["id"] == SECTION1)


def test_packs_listed(client):
    packs = client.get("/api/packs").json()
    assert len(packs) == 9
    s1 = _section1(client)
    assert s1["itemCount"] == 10 and s1["quizzes"][0]["count"] == 10
    dva = [p for p in packs if p["exam"] == "aws-dva-c02"]
    assert sum(p["newCount"] for p in dva) == 106


def test_exam_mode_hides_answers_until_submit(client, monkeypatch):
    s1 = _section1(client)
    att = client.post("/api/attempts", json={"mode": "exam", "packId": SECTION1,
                                             "quizId": s1["quizzes"][0]["id"]}).json()
    assert att["deadlineAt"] and att["total"] == 10
    assert all("answer" not in e["item"] for e in att["items"])

    # answer all correctly except Q1; flag Q2
    for n, e in enumerate(att["items"]):
        choice = SECTION1_KEYS[n] if n else "A"
        r = client.put(f"/api/attempts/{att['id']}/responses/{e['item']['id']}",
                       json={"choiceIds": [choice], "flagged": n == 1, "timeMs": 1000}).json()
        assert r["response"]["correct"] is None and "answer" not in r["item"]  # no leak in exam mode
    # exam answers can be changed before submit
    first = att["items"][0]["item"]["id"]
    client.put(f"/api/attempts/{att['id']}/responses/{first}", json={"choiceIds": ["C"]})

    done = client.post(f"/api/attempts/{att['id']}/submit").json()
    assert done["score"] == 9 and done["submittedAt"]
    assert done["items"][0]["response"]["correct"] is False
    assert done["items"][0]["item"]["answer"]["choiceIds"] == ["B"]
    assert done["items"][1]["response"]["flagged"] is True
    assert client.put(f"/api/attempts/{att['id']}/responses/{first}", json={"choiceIds": ["B"]}).status_code == 409

    # FSRS puts an "Again" into a 1-minute relearning step, so the miss is due a few minutes
    # later, while the 9 correct answers are scheduled days out.
    from app.api import study as study_api
    monkeypatch.setattr(study_api, "now_utc", lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    due = client.get("/api/study/due-questions", params={"packId": SECTION1}).json()
    assert due["itemIds"] == [first]


def test_practice_mode_reveals_and_locks(client):
    att = client.post("/api/attempts", json={"mode": "practice", "packId": SECTION1}).json()
    assert att["deadlineAt"] is None
    iid = att["items"][0]["item"]["id"]
    r = client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["A"]}).json()
    assert r["revealed"] and r["response"]["correct"] is False and r["item"]["answer"]["choiceIds"] == ["B"]
    assert client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["B"]}).status_code == 409
    # flagging is still allowed after answering
    assert client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"flagged": True}).status_code == 200


def test_invalid_choice_rejected(client):
    att = client.post("/api/attempts", json={"packId": SECTION1}).json()
    iid = att["items"][0]["item"]["id"]
    assert client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["Z"]}).status_code == 422


def test_exam_auto_submits_after_deadline(client, monkeypatch):
    att = client.post("/api/attempts", json={"mode": "exam", "packId": SECTION1, "timeLimitSec": 60}).json()
    iid = att["items"][0]["item"]["id"]
    client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["B"]})
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    monkeypatch.setattr(quiz_api, "now_utc", lambda: later)
    assert client.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["A"]}).status_code == 409
    got = client.get(f"/api/attempts/{att['id']}").json()
    assert got["submittedAt"] and got["score"] == 1


def test_weighted_mock_exam_follows_topic_weights(client):
    att = client.post("/api/attempts", json={"mode": "exam", "exam": "databricks-ml-associate",
                                             "count": 20, "seed": 7}).json()
    assert att["total"] == 20 and len({e["item"]["id"] for e in att["items"]}) == 20
    from collections import Counter
    topics = Counter((e["item"]["topics"] or ["none"])[0] for e in att["items"])
    # weights .38/.19/.31/.12 of 20 -> 8/4/6/2 (largest remainder), each section has 10 items
    assert topics == {"databricks-ml": 8, "data-processing": 4, "model-development": 6, "model-deployment": 2}


def test_retake_by_item_ids(client):
    pack = client.get(f"/api/packs/{SECTION1}").json()
    ids = [it["id"] for it in pack["items"][:3]]
    att = client.post("/api/attempts", json={"itemIds": ids[::-1]}).json()
    assert [e["item"]["id"] for e in att["items"]] == ids[::-1]


def test_flashcard_queue_and_review(client):
    q = client.get("/api/study/queue", params={"exam": "aws-dva-c02", "newLimit": 5}).json()
    assert q["newCount"] == 5 and q["dueCount"] == 0
    card = q["cards"][0]
    r = client.post("/api/study/review", json={"itemId": card["id"], "rating": 1}).json()
    # "Again" on a new card schedules a short relearning step (minutes), not days
    due = datetime.fromisoformat(r["due"])
    assert due - datetime.now(timezone.utc) < timedelta(hours=1)
    q2 = client.get("/api/study/queue", params={"exam": "aws-dva-c02", "newLimit": 5}).json()
    assert card["id"] not in [c["id"] for c in q2["cards"]]  # not due yet, no longer new
    assert client.post("/api/study/review", json={"itemId": "nope", "rating": 3}).status_code == 404


def test_attempt_history(client):
    a = client.post("/api/attempts", json={"packId": SECTION1}).json()
    client.post(f"/api/attempts/{a['id']}/submit")
    hist = client.get("/api/attempts").json()
    assert hist[0]["id"] == a["id"] and hist[0]["score"] == 0
    assert _section1(client)["lastAttempt"]["id"] == a["id"]


def test_concurrent_answer_and_flag_both_persist(client):
    """Regression: picking an answer and flagging at once used to lose one of the two writes."""
    from concurrent.futures import ThreadPoolExecutor

    att = client.post("/api/attempts", json={"mode": "exam", "packId": SECTION1}).json()
    ids = [e["item"]["id"] for e in att["items"]]
    url = f"/api/attempts/{att['id']}/responses/"
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(client.put, url + i, json={"choiceIds": ["A"]}) for i in ids]
        futures += [pool.submit(client.put, url + i, json={"flagged": True}) for i in ids]
        assert all(f.result().status_code == 200 for f in futures)
    got = client.get(f"/api/attempts/{att['id']}").json()
    assert all(e["response"]["choiceIds"] == ["A"] and e["response"]["flagged"] for e in got["items"])
