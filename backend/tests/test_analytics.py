from datetime import datetime, timedelta, timezone

import pytest

from app.core import analytics as an
from app.core.analytics import GUESS, SURE, UNSURE, Obs

NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
DML = "databricks-ml-associate"


def obs(item, correct, days_ago=0, conf=None, attempt="a"):
    return Obs(item, attempt, NOW - timedelta(days=days_ago), correct, conf)


# --- pure scoring --------------------------------------------------------------------------------

def test_mastery_prior_and_evidence():
    assert an.mastery(["q"], {}, NOW) == 0.5  # nothing known
    h = an.by_item([obs("q1", True), obs("q2", True), obs("q3", True)])
    assert an.mastery(["q1", "q2", "q3"], h, NOW) == pytest.approx(4 / 5)
    h = an.by_item([obs("q1", False), obs("q2", False)])
    assert an.mastery(["q1", "q2"], h, NOW) == pytest.approx(1 / 4)


def test_guess_earns_half_credit():
    h = an.by_item([obs("q", True, conf=GUESS)])
    assert an.mastery(["q"], h, NOW) == pytest.approx(1.5 / 3)
    h = an.by_item([obs("q", True, conf=SURE)])
    assert an.mastery(["q"], h, NOW) == pytest.approx(2 / 3)


def test_old_answers_fade_and_only_recent_ones_per_question_count():
    # wrong three weeks ago (weight .5), right today (weight 1)
    h = an.by_item([obs("q", False, days_ago=an.HALF_LIFE_DAYS), obs("q", True)])
    assert an.mastery(["q"], h, NOW) == pytest.approx((1 + 1) / (1.5 + 2))
    # ten old wrongs then three rights: only the latest three count
    h = an.by_item([obs("q", False, days_ago=1) for _ in range(10)] + [obs("q", True) for _ in range(3)])
    assert an.mastery(["q"], h, NOW) == pytest.approx(4 / 5)


def test_readiness_weights_and_status():
    topics = [{"weight": 0.75, "mastery": 0.8, "seen": 5}, {"weight": 0.25, "mastery": 0.4, "seen": 5}]
    r = an.readiness(topics, answered=40, passing=0.7)
    assert r["score"] == pytest.approx(0.7) and r["coverage"] == 1 and r["status"] == "borderline"
    assert an.readiness(topics, answered=5, passing=0.7)["status"] == "early"
    topics[1]["seen"] = 0  # 25% of the exam untested -> coverage .75 still enough
    assert an.readiness(topics, answered=40, passing=0.6)["status"] == "on_track"
    topics[0]["seen"] = 1
    assert an.readiness(topics, answered=40, passing=0.6)["status"] == "early"
    # unweighted topics count equally
    flat = [{"weight": None, "mastery": 0.2, "seen": 9}, {"weight": None, "mastery": 0.4, "seen": 9}]
    r = an.readiness(flat, answered=40, passing=None)
    assert r["score"] == pytest.approx(0.3) and r["status"] == "below" and r["passingScore"] == an.DEFAULT_PASSING


def test_calibration_uses_latest_answer_for_lists():
    o = [obs("a", False, 1, SURE), obs("a", True, 0, SURE),  # fixed since
         obs("b", False, 0, SURE),                            # confidently wrong
         obs("c", True, 0, GUESS),                            # lucky guess
         obs("d", True, 0, UNSURE), obs("e", True, 0)]
    c = an.calibration(o, an.by_item(o))
    assert c["confidentlyWrong"] == ["b"] and c["luckyGuesses"] == ["c"] and c["unrated"] == 1
    sure = next(lv for lv in c["levels"] if lv["confidence"] == SURE)
    assert (sure["correct"], sure["total"]) == (1, 3)


def test_drill_priority_order():
    h = an.by_item([obs("wrong", False), obs("guess", True, conf=GUESS),
                    obs("old", True, days_ago=9), obs("recent", True, days_ago=1)])
    ids = ["recent", "old", "guess", "unseen", "wrong", "due"]
    ordered = sorted(ids, key=lambda i: an.drill_priority(i, h, {"due"}))
    assert ordered == ["due", "wrong", "unseen", "guess", "old", "recent"]


def test_weak_topics():
    rows = [{"id": "a", "mastery": 0.9}, {"id": "b", "mastery": 0.3}, {"id": "c", "mastery": 0.6},
            {"id": "d", "mastery": 0.65}]
    assert an.weak_topics(rows, passing=0.7) == ["b", "c"]
    assert an.weak_topics([{"id": "a", "mastery": 0.9}, {"id": "b", "mastery": 0.8}], passing=0.7) == ["b"]


# --- through the API ----------------------------------------------------------------------------

SECTION1 = "0e9ec33c-58a4-5c37-8b1c-f74b08d26523"
SECTION1_KEYS = "B D A B C D D A C B".split()


def _answer(client, att, n, choice, confidence=None):
    iid = att["items"][n]["item"]["id"]
    body = {"choiceIds": [choice]} | ({"confidence": confidence} if confidence else {})
    r = client.put(f"/api/attempts/{att['id']}/responses/{iid}", json=body)
    assert r.status_code == 200, r.text
    return iid


def _wrong(key):
    return "A" if key != "A" else "B"


def test_stats_from_practice_with_confidence(client):
    att = client.post("/api/attempts", json={"mode": "practice", "packId": SECTION1}).json()
    keys = {e["item"]["id"]: k for e, k in zip(att["items"], SECTION1_KEYS)}
    order = [keys[e["item"]["id"]] for e in att["items"]]
    lucky = _answer(client, att, 0, order[0], confidence=1)
    sure_wrong = _answer(client, att, 1, _wrong(order[1]), confidence=3)
    _answer(client, att, 2, order[2], confidence=3)
    # confidence locks with the answer in practice
    r = client.put(f"/api/attempts/{att['id']}/responses/{lucky}", json={"confidence": 3})
    assert r.status_code == 409
    client.post(f"/api/attempts/{att['id']}/submit")  # ended early: 7 unanswered

    s = client.get(f"/api/stats/exams/{DML}").json()
    assert s["readiness"]["answered"] == 3 and s["readiness"]["status"] == "early"
    assert s["readiness"]["passingScore"] == 0.7
    dml = next(t for t in s["topics"] if t["id"] == "databricks-ml")
    assert (dml["answered"], dml["correct"], dml["seen"], dml["itemCount"]) == (3, 2, 3, 10)
    assert dml["mastery"] == pytest.approx((0.5 + 0 + 1 + 1) / (3 + 2))
    assert dml["trend"] == [{**dml["trend"][0], "correct": 2, "total": 3}]
    assert s["calibration"]["luckyGuesses"] == [lucky]
    assert s["calibration"]["confidentlyWrong"] == [sure_wrong]
    assert s["missedCount"] == 1 and s["missedWithoutResources"] == 1 and s["resources"] == []
    assert len(s["weakTopics"]) == 2  # all four sit near the 0.5 prior, below the 0.7 pass line
    # questions skipped by ending practice early are not scheduled as misses
    assert s["dueCount"] == 0
    assert client.get("/api/stats/exams/nope").status_code == 404


def test_exam_in_progress_is_not_counted_and_blanks_count_after_submit(client):
    att = client.post("/api/attempts", json={"mode": "exam", "packId": SECTION1}).json()
    _answer(client, att, 0, "A")
    assert client.get(f"/api/stats/exams/{DML}").json()["readiness"]["answered"] == 0
    client.post(f"/api/attempts/{att['id']}/submit")
    s = client.get(f"/api/stats/exams/{DML}").json()
    assert s["readiness"]["answered"] == 10  # blanks in a submitted exam count as wrong
    assert s["trend"][-1]["total"] == 10


def test_drill_targets_weak_topic_and_due_misses(client, monkeypatch):
    # miss every Section 4 (model deployment) question in a timed exam
    s4 = "model-deployment"
    att = client.post("/api/attempts", json={"mode": "exam", "exam": DML, "topics": [s4], "count": 10}).json()
    for n in range(len(att["items"])):
        _answer(client, att, n, "A")  # A is right for 2 of the 10
    done = client.post(f"/api/attempts/{att['id']}/submit").json()
    missed = {e["item"]["id"] for e in done["items"] if not e["response"]["correct"]}
    assert missed

    from app.api import quiz as quiz_api
    monkeypatch.setattr(quiz_api, "now_utc", lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    drill = client.post("/api/attempts", json={"mode": "practice", "exam": DML, "drill": True,
                                               "count": 12, "seed": 3}).json()
    assert drill["name"].startswith("Drill: Model Deployment")
    ids = {e["item"]["id"] for e in drill["items"]}
    assert missed <= ids  # due misses always make the cut
    assert len(ids) == 12

    picked = client.post("/api/attempts", json={"exam": DML, "drill": True, "topics": ["data-processing"],
                                                "count": 4, "seed": 1}).json()
    assert picked["name"] == "Drill: Data Processing" and picked["total"] == 4
    assert all(e["item"]["topics"] == ["data-processing"] for e in picked["items"])
    assert client.post("/api/attempts", json={"drill": True}).status_code == 422
