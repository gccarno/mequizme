"""What the AI tutor does: fill in missing explanations, explain a mistake, write new questions, chat.

Each function takes an `LLM` and plain dicts, so tests can swap in a fake model.
Nothing here writes to disk; callers save results as drafts for a person to review.
"""

from __future__ import annotations

import difflib
import re
import string

from app.core.schema import stable_id, utcnow
from app.llm.links import keep_live
from app.llm.provider import LLM, author

TUTOR = (
    "You are a precise, encouraging certification tutor. You write for a learner preparing for "
    "the exam named below. Be accurate above all: if you are unsure of a fact, say less rather than guess. "
    "Write plain, direct sentences in markdown. No preamble, no sign-off."
)

LINK_RULES = (
    "Links: at most 2, only official documentation pages you are confident exist "
    "(for example docs.databricks.com, mlflow.org/docs, spark.apache.org/docs, scikit-learn.org, "
    "docs.aws.amazon.com). Prefer a stable topic page over a deep anchor. Give none rather than guess."
)

_RESOURCE = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "url": {"type": "string", "pattern": "^https://"}},
    "required": ["title", "url"],
}


def _letters(item: dict) -> str:
    return "\n".join(f"{c['id']}. {c['text']}" for c in item.get("choices") or [])


def _key(item: dict) -> str:
    a = item.get("answer", {})
    return ", ".join(a.get("choiceIds") or []) or (a.get("text") or "")


def _exam_line(taxonomy: dict) -> str:
    return f"Exam: {taxonomy.get('name') or taxonomy.get('exam') or 'unspecified'}."


def _topic_lines(taxonomy: dict) -> str:
    return "\n".join(f"- {t['id']}: {t['name']}" for t in taxonomy.get("topics", []))


def describe(item: dict, topic_names: dict[str, str] | None = None) -> str:
    """The question as the model sees it."""
    parts = [f"Question:\n{item['prompt']}"]
    if item.get("choices"):
        parts.append(f"Choices:\n{_letters(item)}")
    parts.append(f"Correct answer: {_key(item)}")
    if item.get("topics") and topic_names:
        parts.append("Topic: " + ", ".join(topic_names.get(t, t) for t in item["topics"]))
    if item.get("explanation"):
        parts.append(f"Explanation on file:\n{item['explanation']}")
    return "\n\n".join(parts)


# --- fill in missing fields ----------------------------------------------------------------

ENRICHABLE = ("explanation", "choiceRationales", "resources", "topics", "difficulty")


def missing_fields(item: dict) -> list[str]:
    """Fields the enrich step would fill: empty ones only. Topics only when the item has none."""
    out = []
    if not item.get("explanation"):
        out.append("explanation")
    if item.get("choices") and not item.get("choiceRationales"):
        out.append("choiceRationales")
    if not item.get("resources"):
        out.append("resources")
    if not item.get("topics"):
        out.append("topics")
    if item.get("difficulty") is None:
        out.append("difficulty")
    return out


def enrich(llm: LLM, item: dict, taxonomy: dict, fields: list[str]) -> tuple[dict, str | None]:
    """Returns (new values for `fields`, a note for the reviewer or None)."""
    topic_ids = [t["id"] for t in taxonomy.get("topics", [])]
    wrong = [c["id"] for c in item.get("choices") or [] if c["id"] not in (item["answer"].get("choiceIds") or [])]
    props: dict = {
        "keyCheck": {
            "type": "object",
            "properties": {
                "agrees": {"type": "boolean", "description": "true if the given correct answer is right"},
                "note": {"type": "string", "description": "if not, why, in one or two sentences"},
            },
            "required": ["agrees"],
        },
        "explanation": {"type": "string"},
        "choiceRationales": {
            "type": "array",
            "items": {"type": "object", "properties": {"choiceId": {"type": "string", "enum": wrong or ["-"]},
                                                       "rationale": {"type": "string"}},
                      "required": ["choiceId", "rationale"]},
        },
        "resources": {"type": "array", "items": _RESOURCE, "maxItems": 2},
        "topics": {"type": "array", "items": {"type": "string", "enum": topic_ids or ["-"]}, "maxItems": 2},
        "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
    }
    wanted = ["keyCheck", *[f for f in fields if f in props]]
    schema = {"type": "object", "properties": {k: props[k] for k in wanted}, "required": wanted}
    asks = {
        "explanation": "explanation: 2 to 4 sentences on why the correct answer is right, teaching the "
                       "underlying concept rather than restating the choice.",
        "choiceRationales": f"choiceRationales: for each wrong choice ({', '.join(wrong)}), one sentence on why "
                            "it's wrong or what it would actually do.",
        "resources": "resources: " + LINK_RULES,
        "topics": "topics: the exam topic ids this question belongs to (usually one):\n" + _topic_lines(taxonomy),
        "difficulty": "difficulty: 1 (recall) to 5 (hard multi-step reasoning) for this exam.",
    }
    prompt = "\n\n".join([
        _exam_line(taxonomy),
        describe(item),
        "First check the answer key. Set keyCheck.agrees to false only if you are confident it's wrong. "
        "Either way, write the rest for the answer key as given.",
        "Write:\n" + "\n".join(f"- {asks[f]}" for f in fields if f in asks),
    ])
    out = llm.json(TUTOR, prompt, schema)

    values: dict = {}
    if "explanation" in fields and out.get("explanation"):
        values["explanation"] = out["explanation"].strip()
    if "choiceRationales" in fields:
        r = {x["choiceId"]: x["rationale"].strip() for x in out.get("choiceRationales") or []
             if x.get("choiceId") in wrong and x.get("rationale")}
        if r:
            values["choiceRationales"] = r
    if "resources" in fields:
        res = [{"title": r["title"].strip(), "url": r["url"].strip(), "kind": "doc"}
               for r in out.get("resources") or [] if str(r.get("url", "")).startswith("https://")]
        res = keep_live(res)
        if res:
            values["resources"] = res
    if "topics" in fields:
        t = [x for x in out.get("topics") or [] if x in topic_ids]
        if t:
            values["topics"] = list(dict.fromkeys(t))
    if "difficulty" in fields and isinstance(out.get("difficulty"), int) and 1 <= out["difficulty"] <= 5:
        values["difficulty"] = out["difficulty"]
    check = out.get("keyCheck") or {}
    note = None
    if check.get("agrees") is False:
        note = "The AI thinks the answer key may be wrong. " + (check.get("note") or "").strip()
    return values, note


def apply_draft(item: dict, values: dict, note: str | None, by: str) -> dict:
    """Put AI values on the item and mark them as an unreviewed draft, remembering what they replaced."""
    if not values and not note:
        return item
    prior = item.get("draft") or {}
    previous = dict(prior.get("previous") or {})
    for f in values:
        if f not in (prior.get("fields") or []) and item.get(f) not in (None, "", [], {}):
            previous.setdefault(f, item[f])
    item.update(values)
    fields = list(dict.fromkeys([*(prior.get("fields") or []), *values]))
    draft = {"fields": fields, "by": by, "at": utcnow().isoformat()}
    if previous:
        draft["previous"] = previous
    notes = note or prior.get("notes")
    if notes:
        draft["notes"] = notes
    item["draft"] = draft
    return item


# --- explain a mistake ---------------------------------------------------------------------

def explain_mistake(llm: LLM, item: dict, chosen: list[str], confidence: int | None, taxonomy: dict) -> str:
    picked = [c for c in item.get("choices") or [] if c["id"] in chosen]
    sure = {1: "They said they were guessing.", 2: "They said they were unsure.",
            3: "They said they were sure, so this is a misconception worth correcting."}.get(confidence or 0, "")
    prompt = "\n\n".join([
        _exam_line(taxonomy),
        describe(item),
        "The learner answered: " + ("; ".join(f"{c['id']}. {c['text']}" for c in picked) or "nothing") + ". " + sure,
        "In under 150 words: say what their answer would actually do or mean, the idea that makes the correct "
        "answer right, and how to tell the two apart on the exam. End with one line starting "
        "'**Remember:**' that they could put on a flashcard.",
    ])
    return llm.text(TUTOR, prompt)


# --- write new questions -------------------------------------------------------------------

def _norm(text: str) -> str:
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", text).strip()


def is_duplicate(prompt: str, existing: list[str], threshold: float = 0.8) -> bool:
    p = _norm(prompt)
    return any(difflib.SequenceMatcher(None, p, _norm(e)).ratio() >= threshold for e in existing)


def generate(llm: LLM, taxonomy: dict, topic: dict, count: int, existing: list[str],
             focus: str | None = None) -> list[dict]:
    """New multiple-choice items for one topic, deduplicated against `existing` prompts.
    Returned as draft items (status draft) with fresh ids."""
    schema = {
        "type": "object",
        "properties": {"questions": {"type": "array", "maxItems": count, "items": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "choices": {"type": "array", "minItems": 4, "maxItems": 5,
                            "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                                      "required": ["id", "text"]}},
                "answer": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "explanation": {"type": "string"},
                "choiceRationales": {"type": "array", "items": {
                    "type": "object", "properties": {"choiceId": {"type": "string"}, "rationale": {"type": "string"}},
                    "required": ["choiceId", "rationale"]}},
                "resources": {"type": "array", "items": _RESOURCE, "maxItems": 2},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["prompt", "choices", "answer", "explanation", "choiceRationales", "difficulty"],
        }}},
        "required": ["questions"],
    }
    sample = "\n".join(f"- {p[:200]}" for p in existing[:40]) or "(none yet)"
    prompt = "\n\n".join([
        _exam_line(taxonomy),
        f"Write {count} new exam-style multiple-choice questions for the topic \"{topic['name']}\"."
        + (f" Focus on: {focus}." if focus else ""),
        "Match the real exam: a short scenario, then a question, four choices labelled A to D, exactly one correct "
        "unless the question says 'Choose two'. Wrong choices should be plausible mistakes, not jokes. Vary which "
        "letter is correct. Test understanding, not trivia. Only use facts you are sure of for current versions.",
        "For each: explanation (2 to 4 sentences), choiceRationales for every wrong choice, difficulty 1 to 5, and "
        "resources. " + LINK_RULES,
        "Don't repeat or closely paraphrase these existing questions:\n" + sample,
    ])
    out = llm.json(TUTOR, prompt, schema)
    made: list[dict] = []
    seen = list(existing)
    now = utcnow().isoformat()
    for q in out.get("questions") or []:
        choices = [{"id": str(c["id"]).strip().upper()[:2], "text": c["text"].strip()} for c in q.get("choices") or []]
        ids = [c["id"] for c in choices]
        answer = [a.strip().upper() for a in q.get("answer") or [] if a.strip().upper() in ids]
        if len(choices) < 2 or len(set(ids)) != len(ids) or not answer or is_duplicate(q["prompt"], seen):
            continue
        seen.append(q["prompt"])
        rationales = {r["choiceId"].strip().upper(): r["rationale"].strip() for r in q.get("choiceRationales") or []
                      if r.get("choiceId", "").strip().upper() in ids and r["choiceId"].strip().upper() not in answer}
        resources = keep_live([{"title": r["title"].strip(), "url": r["url"].strip(), "kind": "doc"}
                               for r in q.get("resources") or [] if str(r.get("url", "")).startswith("https://")])
        item = {
            "id": stable_id("generated", topic["id"], _norm(q["prompt"])),
            "type": "mcq_multi" if len(answer) > 1 else "mcq_single",
            "prompt": q["prompt"].strip(),
            "choices": choices,
            "answer": {"choiceIds": answer},
            "explanation": q.get("explanation", "").strip() or None,
            "choiceRationales": rationales or None,
            "topics": [topic["id"]],
            "resources": resources,
            "difficulty": q.get("difficulty") if q.get("difficulty") in range(1, 6) else None,
            "status": "draft",
            "draft": {"fields": ["prompt", "choices", "answer", "explanation", "choiceRationales", "resources"],
                      "by": author(llm), "at": now},
            "createdAt": now,
            "updatedAt": now,
        }
        made.append({k: v for k, v in item.items() if v is not None})
        if len(made) >= count:
            break
    return made


# --- tutor chat ----------------------------------------------------------------------------

def chat(llm: LLM, messages: list[dict], taxonomy: dict, item: dict | None = None,
         topic: dict | None = None) -> str:
    context = [_exam_line(taxonomy)]
    if item:
        context.append("We're discussing this question, which the learner has already answered:\n\n" + describe(item))
    elif topic:
        context.append(f"We're discussing the exam topic \"{topic['name']}\".")
    transcript = "\n\n".join(
        f"{'Learner' if m['role'] == 'user' else 'Tutor'}: {m['content']}" for m in messages[-12:]
    )
    prompt = "\n\n".join([
        *context,
        "Conversation so far:\n\n" + transcript,
        "Reply as the tutor to the learner's last message, in under 200 words unless they ask for more. "
        "Ask a short check-for-understanding question when it helps.",
    ])
    return llm.text(TUTOR, prompt)
