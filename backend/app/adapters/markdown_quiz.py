"""Import the Aiken-like markdown quizzes (e.g. ../ml_associate_exam/*.md).

Recognised shape:
    1. Question stem (may continue on following lines)
    A. option
    B. option
    ...
    ## Answer Key | # Answers
    1. B            (one per line)      -- or --
    1B, 2C, 3A      (comma separated, one line)
Lines before the first question are treated as the description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.schema import (
    Answer,
    Choice,
    Item,
    ItemType,
    Quiz,
    Source,
    StudyPack,
    Taxonomy,
    stable_id,
    utcnow,
)

_QUESTION = re.compile(r"^(\d+)\.\s+(.*)$")
_OPTION = re.compile(r"^([A-H])[.)]\s+(.*)$")
_KEY_HEADER = re.compile(r"^#{1,6}\s*(answer key|answers)\s*$", re.IGNORECASE)
_KEY_LINE = re.compile(r"^(\d+)\.\s*([A-H](?:\s*,\s*[A-H])*)\s*$")
_KEY_INLINE = re.compile(r"(\d+)\s*([A-H]+)\b")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass
class ParseResult:
    title: str | None
    description: str
    questions: list[tuple[int, str, list[tuple[str, str]]]]
    key: dict[int, list[str]]
    warnings: list[str] = field(default_factory=list)


def parse(text: str) -> ParseResult:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    title: str | None = None
    intro: list[str] = []
    questions: list[tuple[int, str, list[tuple[str, str]]]] = []
    key: dict[int, list[str]] = {}
    warnings: list[str] = []

    in_key = False
    cur: tuple[int, list[str], list[tuple[str, str]]] | None = None

    def flush() -> None:
        nonlocal cur
        if cur:
            n, stem, opts = cur
            questions.append((n, "\n".join(stem).strip(), opts))
        cur = None

    for raw in lines:
        line = raw.strip()
        if _KEY_HEADER.match(line):
            flush()
            in_key = True
            continue
        if in_key:
            if not line:
                continue
            m = _KEY_LINE.match(line)
            if m:
                key[int(m.group(1))] = [c.strip() for c in m.group(2).split(",")]
            else:
                for n, letters in _KEY_INLINE.findall(line):
                    key[int(n)] = list(letters)
            continue

        q = _QUESTION.match(line)
        o = _OPTION.match(line)
        if q:
            flush()
            cur = (int(q.group(1)), [q.group(2)], [])
        elif o and cur:
            cur[2].append((o.group(1), o.group(2).strip()))
        elif cur:
            if line and not cur[2]:
                cur[1].append(line)  # stem continuation
            elif line:
                letter, txt = cur[2][-1]
                cur[2][-1] = (letter, f"{txt} {line}")  # option continuation
        else:
            h = _HEADING.match(line)
            if h:
                if title is None:
                    title = h.group(1).strip()
                continue  # headings like "## Questions" are structure, not description
            intro.append(line)
    flush()

    numbers = [n for n, _, _ in questions]
    if numbers != list(range(1, len(numbers) + 1)):
        warnings.append(f"question numbers not sequential: {numbers}")
    for n, _, opts in questions:
        if len(opts) < 2:
            warnings.append(f"Q{n}: fewer than 2 options")
        if n not in key:
            warnings.append(f"Q{n}: missing from answer key")
        elif not set(key[n]) <= {letter for letter, _ in opts}:
            warnings.append(f"Q{n}: key {key[n]} not among options")
    extra = sorted(set(key) - set(numbers))
    if extra:
        warnings.append(f"answer key has entries with no question: {extra}")

    description = re.sub(r"\n{3,}", "\n\n", "\n".join(intro)).strip()
    return ParseResult(title, description, questions, key, warnings)


def to_pack(
    text: str,
    *,
    pack_slug: str,
    name: str | None = None,
    source_ref: str | None = None,
    taxonomy: Taxonomy | None = None,
    topics: list[str] | None = None,
    seconds_per_question: int = 120,
    created_at: datetime | None = None,
) -> tuple[StudyPack, list[str]]:
    """Convert markdown quiz text to a StudyPack. Returns (pack, warnings).

    Questions that are missing from the key are skipped (and reported) rather than guessed.
    """
    res = parse(text)
    now = created_at or utcnow()
    items: list[Item] = []
    warnings = list(res.warnings)
    for n, stem, opts in res.questions:
        if n not in res.key or len(opts) < 2:
            warnings.append(f"Q{n}: skipped")
            continue
        answer = res.key[n]
        items.append(
            Item(
                id=stable_id(pack_slug, "q", n),
                type=ItemType.mcq_multi if len(answer) > 1 else ItemType.mcq_single,
                prompt=stem,
                choices=[Choice(id=letter, text=t) for letter, t in opts],
                answer=Answer(choiceIds=answer),
                topics=list(topics or []),
                createdAt=now,
                updatedAt=now,
            )
        )
    pack_name = name or res.title or pack_slug
    pack = StudyPack(
        id=stable_id(pack_slug),
        name=pack_name,
        description=res.description,
        source=Source(kind="import", ref=source_ref, format="markdown-quiz"),
        taxonomy=taxonomy or Taxonomy(),
        items=items,
        quizzes=[
            Quiz(
                id=stable_id(pack_slug, "quiz"),
                name=pack_name,
                itemIds=[i.id for i in items],
                timeLimitSec=seconds_per_question * len(items),
            )
        ],
        createdAt=now,
        updatedAt=now,
    )
    return pack, warnings


def load(path: Path, **kwargs) -> tuple[StudyPack, list[str]]:
    kwargs.setdefault("pack_slug", path.stem)
    kwargs.setdefault("source_ref", path.name)
    mtime = datetime.fromtimestamp(int(path.stat().st_mtime), tz=timezone.utc)
    kwargs.setdefault("created_at", mtime)
    return to_pack(path.read_text(encoding="utf-8"), **kwargs)
