"""Study Pack format v2 — the canonical content format shared by mequizme and StudyDeck.

These pydantic models are the source of truth. `schema/studypack.v2.schema.json` is generated
from them (`studypack schema`) and a test keeps the checked-in copy in sync.

Evolution rules:
- Every model allows extra fields and preserves them on round-trip, so newer files survive
  older tools.
- Additive changes keep formatVersion; breaking changes bump it and add a migration in
  `app.core.migrate`.
- Content only. Personal progress (SRS state, review logs) never lives in a pack.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION = 2

# Namespace for deterministic ids, so re-converting the same source yields the same ids.
ID_NAMESPACE = uuid.UUID("6f1c4d0e-8a1b-4f8e-9a57-3e1f0c2b7d11")


def stable_id(*parts: object) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, ":".join(str(p) for p in parts)))


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class _Open(BaseModel):
    """Base: tolerate and keep unknown fields; serialize with the JSON field names."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ItemType(str, Enum):
    flashcard = "flashcard"
    cloze = "cloze"
    mcq_single = "mcq_single"
    mcq_multi = "mcq_multi"
    true_false = "true_false"
    short_answer = "short_answer"


CHOICE_TYPES = {ItemType.mcq_single, ItemType.mcq_multi, ItemType.true_false}


class ItemStatus(str, Enum):
    reviewed = "reviewed"
    draft = "draft"  # e.g. LLM-generated, awaiting human review


class Choice(_Open):
    id: str
    text: str


class Answer(_Open):
    choiceIds: list[str] | None = None  # choice-based items
    text: str | None = None  # flashcard / short_answer (markdown)
    accepted: list[str] | None = None  # short_answer alternatives


class Resource(_Open):
    title: str
    # http(s) only: packs may come from other people or an LLM, and a javascript: URL would run on click.
    url: str = Field(pattern=r"^https?://")
    kind: str | None = None  # doc | video | article | course ...


class Media(_Open):
    path: str  # relative to the pack file, or a URL
    role: Literal["prompt", "answer", "explanation"] = "prompt"
    alt: str | None = None


class Draft(_Open):
    """Fields written by an AI (or another tool) that a person hasn't reviewed yet.

    Accepting removes this marker. Rejecting restores `previous` for each listed field
    (fields absent from `previous` are removed). An item whose `status` is `draft` was
    wholly generated, and rejecting it deletes the item.
    """

    fields: list[str] = Field(description="Item fields awaiting review, e.g. explanation, resources")
    by: str | None = Field(default=None, description="Who wrote them, e.g. a model name")
    at: datetime | None = None
    previous: dict | None = Field(default=None, description="Values the draft replaced")
    notes: str | None = Field(default=None, description="Concerns for the reviewer, e.g. a doubtful answer key")


class Item(_Open):
    id: str
    type: ItemType
    prompt: str = Field(description="Markdown. For cloze, use {{c1::text}} deletions.")
    choices: list[Choice] | None = None
    answer: Answer
    explanation: str | None = None
    choiceRationales: dict[str, str] | None = None
    topics: list[str] = Field(default_factory=list, description="Topic ids from the pack taxonomy")
    tags: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    resources: list[Resource] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.reviewed
    draft: Draft | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    @model_validator(mode="after")
    def _check_answer_shape(self) -> Item:
        if self.type in CHOICE_TYPES:
            if not self.choices:
                raise ValueError(f"item {self.id}: {self.type.value} requires choices")
            ids = [c.id for c in self.choices]
            if len(set(ids)) != len(ids):
                raise ValueError(f"item {self.id}: duplicate choice ids")
            picked = self.answer.choiceIds or []
            if not picked or not set(picked) <= set(ids):
                raise ValueError(f"item {self.id}: answer.choiceIds must reference choices")
            if self.type in {ItemType.mcq_single, ItemType.true_false} and len(picked) != 1:
                raise ValueError(f"item {self.id}: {self.type.value} needs exactly one answer")
        elif not self.answer.text:
            raise ValueError(f"item {self.id}: {self.type.value} requires answer.text")
        return self


class Topic(_Open):
    id: str
    name: str
    weight: float | None = Field(default=None, ge=0, le=1, description="Share of the exam")
    parent: str | None = None


class Taxonomy(_Open):
    exam: str | None = None  # stable id, e.g. aws-dva-c02; packs sharing it form one exam
    name: str | None = None  # display name, e.g. "AWS Certified Developer – Associate"
    passingScore: float | None = Field(default=None, ge=0, le=1, description="Share needed to pass the real exam")
    topics: list[Topic] = Field(default_factory=list)


class Source(_Open):
    kind: Literal["authored", "llm", "import"] = "authored"
    ref: str | None = None
    format: str | None = None  # e.g. markdown-quiz, studydeck-v1, anki-apkg


class Quiz(_Open):
    id: str
    name: str
    itemIds: list[str]
    timeLimitSec: int | None = None
    shuffle: bool = False
    shuffleChoices: bool = False
    passingScore: float | None = Field(default=None, ge=0, le=1)


class StudyPack(_Open):
    format: Literal["studypack"] = "studypack"
    formatVersion: int = FORMAT_VERSION
    id: str
    name: str
    description: str = ""
    source: Source | None = None
    taxonomy: Taxonomy = Field(default_factory=Taxonomy)
    items: list[Item]
    quizzes: list[Quiz] = Field(default_factory=list)
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    @model_validator(mode="after")
    def _check_refs(self) -> StudyPack:
        item_ids = [i.id for i in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("duplicate item ids")
        known = set(item_ids)
        for q in self.quizzes:
            missing = [i for i in q.itemIds if i not in known]
            if missing:
                raise ValueError(f"quiz {q.id} references unknown items: {missing[:3]}")
        topic_ids = {t.id for t in self.taxonomy.topics}
        if topic_ids:
            for it in self.items:
                unknown = set(it.topics) - topic_ids
                if unknown:
                    raise ValueError(f"item {it.id} has topics not in taxonomy: {sorted(unknown)}")
        return self

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> StudyPack:
        return cls.model_validate_json(text)
