"""Draft-free copies of content/ for tests. Imports nothing from the app, so it can run before
the app reads its environment (see e2e_server.py)."""

import json
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[2] / "content"


def strip_drafts(item: dict) -> dict | None:
    """The item as it was before any unreviewed AI edits (None for an AI-written question)."""
    draft = item.pop("draft", None)
    if item.get("status") == "draft":
        return None
    if draft:
        previous = draft.get("previous") or {}
        for f in draft.get("fields", []):
            if f in previous:
                item[f] = previous[f]
            else:
                item.pop(f, None)
    return item


def pristine_copy(dest: Path) -> Path:
    """Copy content/ without unreviewed AI drafts, so tests don't depend on what the tutor has
    filled in so far, and writes never touch the real files."""
    for src in CONTENT.rglob("*.json"):
        doc = json.loads(src.read_text(encoding="utf-8"))
        doc["items"] = [i for i in (strip_drafts(i) for i in doc["items"]) if i is not None]
        if not doc["items"]:
            continue
        keep = {i["id"] for i in doc["items"]}
        for q in doc.get("quizzes", []):
            q["itemIds"] = [i for i in q["itemIds"] if i in keep]
        out = dest / src.relative_to(CONTENT)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest
