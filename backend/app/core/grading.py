"""Grade a response against an item (item = pack JSON dict)."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text.strip().lower().strip(".")).strip()


def is_gradable(item: dict) -> bool:
    return item["type"] in {"mcq_single", "mcq_multi", "true_false", "short_answer"}


def grade(item: dict, choice_ids: list[str] | None = None, text: str | None = None) -> bool | None:
    """True/False for auto-gradable items, None for self-graded ones (flashcard, cloze)."""
    kind = item["type"]
    answer = item.get("answer", {})
    if kind in {"mcq_single", "mcq_multi", "true_false"}:
        return bool(choice_ids) and set(choice_ids) == set(answer.get("choiceIds") or [])
    if kind == "short_answer":
        if not text:
            return False
        accepted = [answer.get("text") or "", *(answer.get("accepted") or [])]
        return _norm(text) in {_norm(a) for a in accepted if a}
    return None
