"""Tutor analytics: topic mastery, exam readiness, confidence calibration and weak-topic drills.

The scoring functions are pure (observations in, numbers out) so they are easy to test and tune.
`load_observations` and `exam_context` are the only parts that touch the database.

What counts as evidence:
- every answered question, in practice or exam mode;
- unanswered questions in a *submitted exam* (time pressure is part of the exam), but not in a
  practice session you ended early;
- nothing from an exam still in progress, so stats can't leak answers mid-exam.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.core.grading import is_gradable

HALF_LIFE_DAYS = 21  # an answer from three weeks ago counts half as much as one from today
PER_ITEM_RECENT = 3  # only the latest few answers per question count, so re-taking one quiz can't inflate a topic
GUESS_CREDIT = 0.5  # a correct answer you marked as a guess earns half credit
MIN_ANSWERS = 20  # below this, readiness is shown as an early estimate
MIN_COVERAGE = 0.75  # share of exam weight that must have evidence
MIN_TOPIC_SEEN = 3  # distinct questions seen before a topic counts as covered
DEFAULT_PASSING = 0.7
BORDERLINE = 0.05  # +/- band around the passing score
TREND_POINTS = 10

GUESS, UNSURE, SURE = 1, 2, 3


@dataclass(frozen=True)
class Obs:
    item_id: str
    attempt_id: str
    at: datetime
    correct: bool
    confidence: int | None = None


def credit(o: Obs) -> float:
    if not o.correct:
        return 0.0
    return GUESS_CREDIT if o.confidence == GUESS else 1.0


def by_item(obs: list[Obs]) -> dict[str, list[Obs]]:
    """item id -> observations, newest first."""
    out: dict[str, list[Obs]] = defaultdict(list)
    for o in sorted(obs, key=lambda o: o.at, reverse=True):
        out[o.item_id].append(o)
    return out


def mastery(item_ids: list[str], history: dict[str, list[Obs]], now: datetime) -> float:
    """Recency-weighted share of credit over the latest answers to these questions, with a
    Laplace prior: no evidence gives 0.5, and a few answers can't swing it to 0 or 1."""
    num = den = 0.0
    for iid in item_ids:
        for o in history.get(iid, [])[:PER_ITEM_RECENT]:
            age_days = max(0.0, (now - o.at).total_seconds() / 86400)
            w = 0.5 ** (age_days / HALF_LIFE_DAYS)
            num += w * credit(o)
            den += w
    return (num + 1) / (den + 2)


def readiness(topics: list[dict], answered: int, passing: float | None) -> dict:
    """topics: [{weight, mastery, seen}]. Weighted by the exam blueprint (equal if unweighted)."""
    passing = passing or DEFAULT_PASSING
    if not topics:
        return {"score": None, "coverage": 0.0, "answered": answered, "passingScore": passing, "status": "no_topics"}
    weights = [t.get("weight") or 0 for t in topics]
    if not any(weights):
        weights = [1.0] * len(topics)
    total = sum(weights)
    score = sum(w * t["mastery"] for w, t in zip(weights, topics)) / total
    coverage = sum(w for w, t in zip(weights, topics) if t["seen"] >= MIN_TOPIC_SEEN) / total
    if answered < MIN_ANSWERS or coverage < MIN_COVERAGE:
        status = "early"
    elif score >= passing + BORDERLINE:
        status = "on_track"
    elif score >= passing - BORDERLINE:
        status = "borderline"
    else:
        status = "below"
    return {"score": score, "coverage": coverage, "answered": answered, "passingScore": passing, "status": status}


def calibration(obs: list[Obs], history: dict[str, list[Obs]]) -> dict:
    """How often you're right at each confidence level, plus the questions to revisit:
    confidently wrong (sure, but wrong) and lucky guesses (guessed, and right) on the latest try."""
    levels = {c: {"confidence": c, "correct": 0, "total": 0} for c in (SURE, UNSURE, GUESS)}
    unrated = 0
    for o in obs:
        if o.confidence in levels:
            levels[o.confidence]["total"] += 1
            levels[o.confidence]["correct"] += o.correct
        else:
            unrated += 1
    latest = {iid: hs[0] for iid, hs in history.items() if hs}
    return {
        "levels": list(levels.values()),
        "unrated": unrated,
        "confidentlyWrong": [iid for iid, o in latest.items() if not o.correct and o.confidence == SURE],
        "luckyGuesses": [iid for iid, o in latest.items() if o.correct and o.confidence == GUESS],
    }


def drill_priority(iid: str, history: dict[str, list[Obs]], due: set[str]) -> tuple:
    """Lower sorts first: due for review, last answer wrong, never seen, last answer a lucky
    guess, then whatever you've gone longest without seeing."""
    hs = history.get(iid)
    if iid in due:
        return (0, "")
    if not hs:
        return (2, "")
    last = hs[0]
    if not last.correct:
        return (1, "")
    if last.confidence == GUESS:
        return (3, "")
    return (4, last.at.isoformat())


def weak_topics(topic_rows: list[dict], passing: float, limit: int = 2) -> list[str]:
    """Lowest-mastery topics below the passing line; if none are below it, the single weakest."""
    ranked = sorted(topic_rows, key=lambda t: t["mastery"])
    below = [t["id"] for t in ranked if t["mastery"] < passing][:limit]
    return below or [t["id"] for t in ranked[:1]]


# --- database ----------------------------------------------------------------------------------

def load_observations(conn: sqlite3.Connection, item_ids: set[str] | None = None) -> list[Obs]:
    obs: list[Obs] = []
    atts = conn.execute("SELECT id, mode, item_ids, submitted_at FROM attempts").fetchall()
    for a in atts:
        if a["mode"] == "exam" and a["submitted_at"] is None:
            continue  # exam in progress: correctness is hidden until submit
        responses = {r["item_id"]: r for r in conn.execute(
            "SELECT item_id, correct, confidence, answered_at FROM responses WHERE attempt_id = ?", (a["id"],))}
        for iid in json.loads(a["item_ids"]):
            if item_ids is not None and iid not in item_ids:
                continue
            r = responses.get(iid)
            if r is not None and r["answered_at"] and r["correct"] is not None:
                obs.append(Obs(iid, a["id"], datetime.fromisoformat(r["answered_at"]), bool(r["correct"]),
                               r["confidence"]))
            elif a["mode"] == "exam":  # submitted exam, left blank
                obs.append(Obs(iid, a["id"], datetime.fromisoformat(a["submitted_at"]), False,
                               r["confidence"] if r is not None else None))
    return obs


@dataclass
class ExamContext:
    exam: str
    name: str
    passing: float
    topics: list[dict]  # {id, name, weight}
    items: dict[str, dict] = field(default_factory=dict)  # gradable, non-draft items by id

    def topic_items(self, topic_id: str) -> list[str]:
        return [iid for iid, it in self.items.items() if topic_id in it.get("topics", [])]


def exam_context(conn: sqlite3.Connection, exam: str) -> ExamContext | None:
    packs = conn.execute("SELECT id, body FROM packs WHERE exam = ? ORDER BY path", (exam,)).fetchall()
    if not packs:
        return None
    name, passing, topics = exam, None, {}
    for p in packs:
        tax = json.loads(p["body"]).get("taxonomy", {})
        name = tax.get("name") or name
        passing = passing or tax.get("passingScore")
        for t in tax.get("topics", []):
            topics.setdefault(t["id"], {"id": t["id"], "name": t["name"], "weight": t.get("weight")})
    ids = [p["id"] for p in packs]
    rows = conn.execute(
        f"SELECT body FROM items WHERE status != 'draft' AND pack_id IN ({','.join('?' * len(ids))}) "
        "ORDER BY pack_id, position", ids)
    items = {b["id"]: b for b in (json.loads(r["body"]) for r in rows) if is_gradable(b)}
    return ExamContext(exam, name, passing or DEFAULT_PASSING, list(topics.values()), items)


def due_question_ids(conn: sqlite3.Connection, item_ids: set[str], now: datetime) -> set[str]:
    rows = conn.execute("SELECT item_id FROM srs_state WHERE due <= ?", (now.isoformat(),))
    return {r["item_id"] for r in rows} & item_ids


# --- composed views ----------------------------------------------------------------------------

def _trend(obs: list[Obs], attempt_rows: dict[str, sqlite3.Row], limit: int = TREND_POINTS) -> list[dict]:
    per: dict[str, dict] = {}
    for o in obs:
        a = attempt_rows.get(o.attempt_id)
        if a is None or a["submitted_at"] is None:
            continue
        row = per.setdefault(o.attempt_id, {"attemptId": o.attempt_id, "name": a["name"], "mode": a["mode"],
                                            "at": a["submitted_at"], "correct": 0, "total": 0})
        row["total"] += 1
        row["correct"] += o.correct
    return sorted(per.values(), key=lambda r: r["at"])[-limit:]


def exam_stats(conn: sqlite3.Connection, ctx: ExamContext, now: datetime) -> dict:
    obs = load_observations(conn, set(ctx.items))
    history = by_item(obs)
    attempt_rows = {r["id"]: r for r in conn.execute("SELECT id, name, mode, submitted_at FROM attempts")}

    topic_rows = []
    for t in ctx.topics:
        iids = ctx.topic_items(t["id"])
        t_set = set(iids)
        t_obs = [o for o in obs if o.item_id in t_set]
        topic_rows.append({
            **t,
            "itemCount": len(iids),
            "seen": sum(1 for i in iids if history.get(i)),
            "answered": len(t_obs),
            "correct": sum(o.correct for o in t_obs),
            "mastery": mastery(iids, history, now),
            "trend": _trend(t_obs, attempt_rows),
        })

    latest_wrong = [iid for iid, hs in history.items() if hs and not hs[0].correct]
    resources: dict[str, dict] = {}
    bare = 0
    for iid in latest_wrong:
        item = ctx.items[iid]
        links = item.get("resources") or []
        if not links:
            bare += 1
        for r in links:
            row = resources.setdefault(r["url"], {"title": r["title"], "url": r["url"], "kind": r.get("kind"),
                                                  "missCount": 0, "topics": []})
            row["missCount"] += 1
            for t in item.get("topics", []):
                if t not in row["topics"]:
                    row["topics"].append(t)

    return {
        "exam": ctx.exam,
        "name": ctx.name,
        "questionCount": len(ctx.items),
        "untopicedCount": sum(1 for it in ctx.items.values() if not it.get("topics")),
        "readiness": readiness(topic_rows, len(obs), ctx.passing),
        "topics": topic_rows,
        "weakTopics": weak_topics(topic_rows, ctx.passing) if topic_rows else [],
        "trend": _trend(obs, attempt_rows),
        "calibration": calibration(obs, history),
        "missedCount": len(latest_wrong),
        "resources": sorted(resources.values(), key=lambda r: (-r["missCount"], r["title"])),
        "missedWithoutResources": bare,
        "dueCount": len(due_question_ids(conn, set(ctx.items), now)),
    }


def build_drill(conn: sqlite3.Connection, ctx: ExamContext, now: datetime, count: int,
                topics: list[str] | None, rng: random.Random) -> tuple[list[str], str]:
    """A practice set aimed at what you know least: the chosen (or weakest) topics, with
    questions that are due for review mixed in. Returns (item ids, attempt name)."""
    history = by_item(load_observations(conn, set(ctx.items)))
    names = {t["id"]: t["name"] for t in ctx.topics}
    chosen = bool(topics)  # you picked the topics: stay inside them
    if not topics:
        rows = [{"id": t["id"], "mastery": mastery(ctx.topic_items(t["id"]), history, now)} for t in ctx.topics]
        topics = weak_topics(rows, ctx.passing) if rows else []
    due = due_question_ids(conn, set(ctx.items), now)
    in_topics = {iid for iid, it in ctx.items.items() if set(it.get("topics", [])) & set(topics)}

    def key(iid: str) -> tuple:
        # random tiebreak so two drills on the same state don't repeat the same unseen questions
        return (*drill_priority(iid, history, due), rng.random())

    # Otherwise due questions from other topics may fill at most half the drill
    # (all of it when the exam has no topics).
    room = 0 if chosen else count // 2 if in_topics else count
    other_due = sorted(due - in_topics, key=key)[:room]
    picked = sorted(in_topics | set(other_due), key=key)[:count]
    rng.shuffle(picked)
    label = ", ".join(names.get(t, t) for t in topics) or "questions due for review"
    return picked, f"Drill: {label}"
