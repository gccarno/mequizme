"""AI tutor features, with a fake model so tests are fast and offline."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import tutor
from app.llm.fake import FakeLLM
from app.main import create_app
from pristine import pristine_copy

EXAM = "databricks-ml-associate"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEQUIZME_CHECK_LINKS", "0")
    content = pristine_copy(tmp_path / "content")  # writes go to a copy, never the real content
    llm = FakeLLM()
    app = create_app(content_dir=content, db_path=tmp_path / "t.db", static_dir=tmp_path / "none", llm=llm)
    with TestClient(app) as c:
        yield c, llm, content


def wait(client, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/ai/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


def pack_for(client, name_part):
    return next(p for p in client.get("/api/packs").json() if name_part in p["name"])


def file_item(content, rel, item_id):
    doc = json.loads((content / rel).read_text(encoding="utf-8"))
    return next(i for i in doc["items"] if i["id"] == item_id)


def test_status(client, env):
    assert client.get("/api/ai/status").json()["available"] is False
    assert client.post("/api/ai/enrich", json={"exam": EXAM}).status_code == 503
    c, _, _ = env
    s = c.get("/api/ai/status").json()
    assert s["available"] and s["label"] == "fake-tutor via canned test answers"


def test_enrich_writes_drafts_to_the_pack_file_then_accept_and_reject(env):
    c, llm, content = env
    pack = pack_for(c, "Section 1")
    assert c.get("/api/ai/enrich/preview", params={"packId": pack["id"]}).json()["count"] == 10
    job = wait(c, c.post("/api/ai/enrich", json={"packId": pack["id"]}).json()["id"])
    assert job["status"] == "done" and job["changed"] == 10 and job["done"] == 10

    drafts = c.get("/api/drafts", params={"exam": EXAM}).json()["items"]
    assert len(drafts) == 10
    first = drafts[0]
    on_disk = file_item(content, pack["path"], first["id"])
    assert on_disk["explanation"] == "Because of the concept."
    assert set(on_disk["choiceRationales"]) == {c["id"] for c in on_disk["choices"]} - set(on_disk["answer"]["choiceIds"])
    # topics were already set by section, so the AI didn't touch them
    assert on_disk["topics"] == ["databricks-ml"] and "topics" not in on_disk["draft"]["fields"]
    assert on_disk["draft"]["by"] == "fake-tutor via canned test answers"

    # Accept with an edit: the edit lands in the file and the draft marker goes away.
    saved = c.post(f"/api/items/{first['id']}/accept", json={"explanation": "My own words."}).json()
    assert "draft" not in saved
    on_disk = file_item(content, pack["path"], first["id"])
    assert on_disk["explanation"] == "My own words." and "draft" not in on_disk
    assert c.post(f"/api/items/{first['id']}/accept").status_code == 409

    # Reject: generated fields are removed again.
    second = drafts[1]["id"]
    out = c.post(f"/api/items/{second}/reject").json()
    assert not out["deleted"] and "explanation" not in out["item"] and "draft" not in out["item"]
    assert c.get("/api/drafts/count").json()["count"] == 8

    # Nothing left to fill in for the accepted/rejected ones? Rejected is empty again, so it's a target.
    assert c.get("/api/ai/enrich/preview", params={"packId": pack["id"]}).json()["count"] == 1


def test_enrich_fills_missing_topics_and_flags_a_doubtful_key(env):
    c, llm, content = env
    llm.key_agrees = False
    pack = pack_for(c, "Mixed")
    item = c.get(f"/api/packs/{pack['id']}").json()["items"][0]
    assert item["topics"] == []
    wait(c, c.post("/api/ai/enrich", json={"itemIds": [item["id"]]}).json()["id"])
    on_disk = file_item(content, pack["path"], item["id"])
    assert on_disk["topics"] == ["model-development"]
    assert on_disk["draft"]["notes"].startswith("The AI thinks the answer key may be wrong. C looks right")
    assert on_disk["answer"] == item["answer"]  # the key itself is never changed
    stats = c.get(f"/api/stats/exams/{EXAM}").json()
    assert stats["untopicedCount"] == 19


def test_enrich_skips_questions_waiting_for_review(env):
    c, llm, _ = env
    pack = pack_for(c, "Section 2")
    llm_resources = llm.json
    llm.json = lambda s, p, schema: {k: v for k, v in llm_resources(s, p, schema).items() if k != "resources"}
    wait(c, c.post("/api/ai/enrich", json={"packId": pack["id"]}).json()["id"])
    # Every question still lacks links, but each has a draft waiting, so there's nothing to redo.
    assert c.get("/api/ai/enrich/preview", params={"packId": pack["id"]}).json()["count"] == 0


def test_enrich_refuses_when_nothing_is_missing(env):
    c, _, _ = env
    pack = pack_for(c, "Section 2")
    wait(c, c.post("/api/ai/enrich", json={"packId": pack["id"]}).json()["id"])
    r = c.post("/api/ai/enrich", json={"packId": pack["id"]})
    assert r.status_code == 422


def test_reject_restores_replaced_values():
    item = {"explanation": "old", "resources": []}
    tutor.apply_draft(item, {"explanation": "new", "resources": [{"title": "t", "url": "https://x"}]}, None, "m")
    assert item["draft"]["previous"] == {"explanation": "old"}
    assert item["draft"]["fields"] == ["explanation", "resources"]


def q(prompt, answer="B"):
    return {
        "prompt": prompt,
        "choices": [{"id": x, "text": f"choice {x}"} for x in "ABCD"],
        "answer": [answer],
        "explanation": "why",
        "choiceRationales": [{"choiceId": "A", "rationale": "nope"}, {"choiceId": "B", "rationale": "is the answer"}],
        "difficulty": 3,
        "resources": [{"title": "Docs", "url": "https://mlflow.org/docs/latest/index.html"}],
    }


def test_generate_saves_new_questions_as_drafts_outside_quizzes(env):
    c, llm, content = env
    existing = c.get(f"/api/packs/{pack_for(c, 'Section 3')['id']}").json()["items"][0]["prompt"]
    llm.questions = [q("Which metric suits an imbalanced binary classifier where false negatives are costly?"),
                     q(existing.upper() + "!"),  # near duplicate of an existing question
                     q("bad answer key", answer="Z")]
    before = next(e for e in c.get("/api/exams").json() if e["exam"] == EXAM)["questionCount"]
    job = wait(c, c.post("/api/ai/generate", json={"exam": EXAM, "topic": "model-development", "count": 3}).json()["id"])
    assert job["status"] == "done" and job["changed"] == 1
    gen = json.loads((content / EXAM / "generated.json").read_text(encoding="utf-8"))
    (made,) = gen["items"]
    assert made["status"] == "draft" and made["topics"] == ["model-development"]
    assert made["choiceRationales"] == {"A": "nope"}  # the correct choice's "rationale" is dropped
    assert gen["taxonomy"]["exam"] == EXAM
    # Drafts don't appear in quizzes or counts until accepted.
    assert next(e for e in c.get("/api/exams").json() if e["exam"] == EXAM)["questionCount"] == before
    c.post(f"/api/items/{made['id']}/accept")
    assert next(e for e in c.get("/api/exams").json() if e["exam"] == EXAM)["questionCount"] == before + 1


def test_rejecting_a_generated_question_deletes_it(env):
    c, llm, content = env
    llm.questions = [q("First new question about feature stores?"), q("Second new question about model serving?")]
    wait(c, c.post("/api/ai/generate", json={"exam": EXAM, "topic": "model-deployment", "count": 2}).json()["id"])
    gen = json.loads((content / EXAM / "generated.json").read_text(encoding="utf-8"))
    assert len(gen["items"]) == 2
    assert c.post(f"/api/items/{gen['items'][0]['id']}/reject").json()["deleted"] is True
    gen = json.loads((content / EXAM / "generated.json").read_text(encoding="utf-8"))
    assert len(gen["items"]) == 1


def test_generate_rejects_unknown_topic(env):
    c, _, _ = env
    r = c.post("/api/ai/generate", json={"exam": EXAM, "topic": "nope"})
    assert r.status_code == 422


def _wrong_choice(entry):
    return next(ch["id"] for ch in entry["item"]["choices"]
                if ch["id"] not in (entry["item"].get("answer") or {}).get("choiceIds", ["?"]))


def test_explain_my_mistake_only_after_the_answer_is_shown(env):
    c, llm, _ = env
    pack = pack_for(c, "Section 1")
    att = c.post("/api/attempts", json={"mode": "exam", "packId": pack["id"]}).json()
    iid = att["items"][0]["item"]["id"]
    c.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["A"]})
    # mid-exam: no help that could leak the answer
    assert c.post("/api/ai/explain", json={"attemptId": att["id"], "itemId": iid}).status_code == 409
    assert c.post("/api/ai/chat", json={"attemptId": att["id"], "itemId": iid,
                                        "messages": [{"role": "user", "content": "hint?"}]}).status_code == 409

    att = c.post("/api/attempts", json={"mode": "practice", "packId": pack["id"]}).json()
    first = att["items"][0]
    iid = first["item"]["id"]
    assert c.post("/api/ai/explain", json={"attemptId": att["id"], "itemId": iid}).status_code == 409
    entry = c.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": ["A"], "confidence": 3}).json()
    if entry["response"]["correct"]:
        pytest.skip("A happens to be right for this item")
    r = c.post("/api/ai/explain", json={"attemptId": att["id"], "itemId": iid}).json()
    assert r == {"text": "Your answer does X. **Remember:** Y.", "by": "fake-tutor via canned test answers", "cached": False}
    assert "They said they were sure" in llm.calls[-1] and "The learner answered: A." in llm.calls[-1]
    n = len(llm.calls)
    assert c.post("/api/ai/explain", json={"attemptId": att["id"], "itemId": iid}).json()["cached"] is True
    assert len(llm.calls) == n

    reply = c.post("/api/ai/chat", json={"attemptId": att["id"], "itemId": iid,
                                         "messages": [{"role": "user", "content": "Why not A?"}]}).json()
    assert reply["reply"].startswith("Good question")
    assert "Learner: Why not A?" in llm.calls[-1] and "Correct answer:" in llm.calls[-1]


def test_explain_refuses_a_right_answer(env):
    c, _, _ = env
    pack = pack_for(c, "Section 1")
    att = c.post("/api/attempts", json={"mode": "practice", "packId": pack["id"]}).json()
    iid = att["items"][0]["item"]["id"]
    key = c.get(f"/api/packs/{pack['id']}").json()["items"]
    answer = next(i for i in key if i["id"] == iid)["answer"]["choiceIds"]
    c.put(f"/api/attempts/{att['id']}/responses/{iid}", json={"choiceIds": answer})
    assert c.post("/api/ai/explain", json={"attemptId": att["id"], "itemId": iid}).status_code == 422


def test_topic_chat_and_validation(env):
    c, llm, _ = env
    r = c.post("/api/ai/chat", json={"exam": EXAM, "topic": "data-processing",
                                     "messages": [{"role": "user", "content": "What's one-hot encoding?"}]})
    assert r.status_code == 200 and 'topic "Data Processing"' in llm.calls[-1]
    r = c.post("/api/ai/chat", json={"exam": EXAM, "messages": [{"role": "assistant", "content": "hi"}]})
    assert r.status_code == 422


def test_duplicate_detection():
    assert tutor.is_duplicate("What does MLflow track?", ["what does mlflow  track"])
    assert not tutor.is_duplicate("What does MLflow track?", ["How do you scale out pandas on Spark?"])


def test_missing_fields():
    item = {"prompt": "p", "choices": [{"id": "A", "text": "a"}], "answer": {"choiceIds": ["A"]},
            "explanation": "x", "topics": ["t"], "resources": [], "difficulty": 2}
    assert tutor.missing_fields(item) == ["choiceRationales", "resources"]
