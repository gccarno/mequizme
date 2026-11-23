import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from app.adapters import markdown_quiz, studydeck_v1
from app.cli import SCHEMA_PATH, schema_text
from app.core.schema import Answer, Choice, Item, ItemType, StudyPack

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
QUIZ_DIR = REPO.parent / "ml_associate_exam"
DECK_DIR = REPO.parents[1] / "note_card_app" / "note_card_app" / "flashcards"
PACK_FILES = sorted(CONTENT.rglob("*.json"))


# --- schema --------------------------------------------------------------------------

def test_checked_in_schema_matches_models():
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_text(), "run: uv run studypack schema"


@pytest.mark.parametrize("path", PACK_FILES, ids=lambda p: p.name)
def test_content_packs_valid(path):
    text = path.read_text(encoding="utf-8")
    StudyPack.from_json(text)
    jsonschema.validate(json.loads(text), json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_unknown_fields_survive_round_trip():
    pack = StudyPack.model_validate(
        {"id": "p", "name": "n", "futureField": {"x": 1},
         "items": [{"id": "i", "type": "flashcard", "prompt": "q", "answer": {"text": "a"},
                    "hint": "new in v3"}]}
    )
    again = json.loads(pack.to_json())
    assert again["futureField"] == {"x": 1}
    assert again["items"][0]["hint"] == "new in v3"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(type=ItemType.mcq_single, answer=Answer(choiceIds=["A"])),  # no choices
        dict(type=ItemType.mcq_single, choices=[Choice(id="A", text="x")], answer=Answer(choiceIds=["Z"])),
        dict(type=ItemType.mcq_single, choices=[Choice(id="A", text="x"), Choice(id="B", text="y")],
             answer=Answer(choiceIds=["A", "B"])),
        dict(type=ItemType.flashcard, answer=Answer()),  # no answer text
    ],
)
def test_item_validation_rejects_bad_shapes(kwargs):
    with pytest.raises(ValidationError):
        Item(id="i", prompt="q", **kwargs)


def test_pack_rejects_dangling_refs():
    base = {"id": "p", "name": "n",
            "items": [{"id": "i", "type": "flashcard", "prompt": "q", "answer": {"text": "a"}, "topics": ["t"]}]}
    with pytest.raises(ValidationError):
        StudyPack.model_validate(base | {"taxonomy": {"topics": [{"id": "other", "name": "o"}]}})
    with pytest.raises(ValidationError):
        StudyPack.model_validate(base | {"quizzes": [{"id": "q", "name": "q", "itemIds": ["nope"]}]})


# --- markdown quiz adapter -------------------------------------------------------------

def test_parse_list_key_and_continuations():
    text = """# My Quiz
Intro line.

1. First stem
continues here

A. one
B. two
wraps on

2. Pick two
A. a
B. b
C. c

## Answer Key
1. B
2. A, C
"""
    pack, warnings = markdown_quiz.to_pack(text, pack_slug="t")
    assert warnings == []
    assert pack.name == "My Quiz" and pack.description == "Intro line."
    q1, q2 = pack.items
    assert q1.prompt == "First stem\ncontinues here"
    assert q1.choices[1].text == "two wraps on"
    assert q2.type == ItemType.mcq_multi and q2.answer.choiceIds == ["A", "C"]
    assert pack.quizzes[0].timeLimitSec == 240


def test_parse_inline_key_and_missing_answers():
    text = "1. Q\nA. x\nB. y\n2. Q2\nA. x\nB. y\n# Answers\n1B, 3A\n"
    pack, warnings = markdown_quiz.to_pack(text, pack_slug="t")
    assert [i.answer.choiceIds for i in pack.items] == [["B"]]
    assert any("Q2: missing" in w for w in warnings)
    assert any("no question: [3]" in w for w in warnings)


def test_ids_are_deterministic():
    text = "1. Q\nA. x\nB. y\n# Answers\n1A\n"
    a, _ = markdown_quiz.to_pack(text, pack_slug="same")
    b, _ = markdown_quiz.to_pack(text, pack_slug="same")
    assert a.id == b.id and a.items[0].id == b.items[0].id


GOLDEN_KEYS = {
    "section1_quiz1.md": "B D A B C D D A C B",
    "section2_quiz1.md": "C D B D B C B D A C",
    "section3_quiz1.md": "C B D A C C D A B C",
    "section4_quiz1.md": "B C A D B D C A C B",
    "more_quizes.md": "B C A D B D A C B C D A B D C A D B C B",
}


@pytest.mark.skipif(not QUIZ_DIR.exists(), reason="source quizzes not present")
@pytest.mark.parametrize("name,keys", GOLDEN_KEYS.items())
def test_real_quizzes_golden(name, keys):
    pack, warnings = markdown_quiz.load(QUIZ_DIR / name)
    assert warnings == []
    assert [i.answer.choiceIds[0] for i in pack.items] == keys.split()
    assert all(len(i.choices) == 4 for i in pack.items)


# --- StudyDeck v1 adapter -------------------------------------------------------------

V1 = {
    "formatVersion": 1,
    "name": "Deck",
    "description": "desc",
    "cards": [
        {"question": "Q1", "answer": "A1", "createdAt": 1700000000000, "topic": "Lambda Basics"},
        {"question": "Q2", "answer": "A2", "createdAt": 1700000000001,
         "sm2EasinessFactor": 2.2, "sm2Repetitions": 3, "sm2IntervalDays": 12},
    ],
}


def test_studydeck_v1_round_trip_lossless():
    pack, progress = studydeck_v1.from_v1(V1, pack_slug="deck")
    assert [t.id for t in pack.taxonomy.topics] == ["lambda-basics"]
    assert len(progress) == 1 and progress[0].interval_days == 12
    pack2 = StudyPack.from_json(pack.to_json())  # through the file format
    assert studydeck_v1.to_v1(pack2, progress) == V1


@pytest.mark.skipif(not DECK_DIR.exists(), reason="StudyDeck decks not present")
@pytest.mark.parametrize("path", sorted(DECK_DIR.glob("*.json")) if DECK_DIR.exists() else [], ids=lambda p: p.name)
def test_real_decks_round_trip(path):
    original = json.loads(path.read_text(encoding="utf-8"))
    pack, progress = studydeck_v1.from_v1(original, pack_slug=path.stem)
    assert studydeck_v1.to_v1(pack, progress) == original
