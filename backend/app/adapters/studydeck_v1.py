"""StudyDeck (Android) deck JSON, formatVersion 1 <-> Study Pack v2.

v1: {formatVersion, name, description, cards: [{question, answer, createdAt(ms),
     sm2EasinessFactor?, sm2Repetitions?, sm2IntervalDays?, topic?}]}

SM-2 fields are personal progress, so they are returned separately from the pack
(see `Sm2State`) instead of being written into shared content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.schema import (
    Answer,
    Item,
    ItemType,
    Source,
    StudyPack,
    Taxonomy,
    Topic,
    stable_id,
    utcnow,
)

SM2_DEFAULTS = {"sm2EasinessFactor": 2.5, "sm2Repetitions": 0, "sm2IntervalDays": 1}
_V1_CARD_KEYS = {"question", "answer", "createdAt", "topic", *SM2_DEFAULTS}


@dataclass
class Sm2State:
    item_id: str
    easiness: float
    repetitions: int
    interval_days: int


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "topic"


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _dt_to_ms(dt: datetime | None) -> int:
    return int(dt.timestamp() * 1000) if dt else 0


def from_v1(
    data: dict | str,
    *,
    pack_slug: str,
    source_ref: str | None = None,
    taxonomy: Taxonomy | None = None,
    default_topic: str | None = None,
) -> tuple[StudyPack, list[Sm2State]]:
    if isinstance(data, str):
        data = json.loads(data)
    if data.get("formatVersion", 1) != 1:
        raise ValueError(f"expected StudyDeck formatVersion 1, got {data.get('formatVersion')}")

    taxonomy = taxonomy.model_copy(deep=True) if taxonomy else Taxonomy()
    known = {t.id for t in taxonomy.topics}
    items: list[Item] = []
    progress: list[Sm2State] = []
    for idx, card in enumerate(data["cards"]):
        topics: list[str] = []
        if card.get("topic"):
            tid = slugify(card["topic"])
            if tid not in known:
                taxonomy.topics.append(Topic(id=tid, name=card["topic"]))
                known.add(tid)
            topics = [tid]
        elif default_topic:
            topics = [default_topic]
        item_id = stable_id(pack_slug, "card", idx)
        created = _ms_to_dt(card["createdAt"]) if card.get("createdAt") else utcnow()
        extras = {k: v for k, v in card.items() if k not in _V1_CARD_KEYS}
        items.append(
            Item(
                id=item_id,
                type=ItemType.flashcard,
                prompt=card["question"],
                answer=Answer(text=card["answer"]),
                topics=topics,
                createdAt=created,
                updatedAt=created,
                **extras,
            )
        )
        sm2 = {k: card.get(k, d) for k, d in SM2_DEFAULTS.items()}
        if sm2 != SM2_DEFAULTS:
            progress.append(
                Sm2State(item_id, sm2["sm2EasinessFactor"], sm2["sm2Repetitions"], sm2["sm2IntervalDays"])
            )

    now = min((i.createdAt for i in items if i.createdAt), default=None) or utcnow()
    pack = StudyPack(
        id=stable_id(pack_slug),
        name=data["name"],
        description=data.get("description", ""),
        source=Source(kind="import", ref=source_ref, format="studydeck-v1"),
        taxonomy=taxonomy,
        items=items,
        createdAt=now,
        updatedAt=now,
    )
    return pack, progress


def to_v1(pack: StudyPack, progress: list[Sm2State] | None = None) -> dict:
    """Export flashcard items to StudyDeck v1. Non-flashcard items are rendered as cards."""
    names = {t.id: t.name for t in pack.taxonomy.topics}
    sm2 = {p.item_id: p for p in progress or []}
    cards = []
    for it in pack.items:
        if it.type == ItemType.flashcard:
            question, answer = it.prompt, it.answer.text or ""
        else:
            question = it.prompt
            if it.choices:
                question += "\n\n" + "\n".join(f"{c.id}. {c.text}" for c in it.choices)
            answer = ", ".join(it.answer.choiceIds or []) or (it.answer.text or "")
            if it.explanation:
                answer += "\n\n" + it.explanation
        card: dict = {"question": question, "answer": answer, "createdAt": _dt_to_ms(it.createdAt)}
        if it.topics:
            card["topic"] = names.get(it.topics[0], it.topics[0])
        if it.id in sm2:
            s = sm2[it.id]
            card |= {
                "sm2EasinessFactor": s.easiness,
                "sm2Repetitions": s.repetitions,
                "sm2IntervalDays": s.interval_days,
            }
        cards.append(card)
    return {"formatVersion": 1, "name": pack.name, "description": pack.description, "cards": cards}
