"""One-off: convert the existing quizzes and StudyDeck decks into content/.

Run from the repo root:
    uv run --project backend python scripts/import_existing.py \
        --quizzes ../ml_associate_exam \
        --decks ../../note_card_app/note_card_app/flashcards

Re-running is safe: ids are deterministic, so items keep their ids (and your progress).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.adapters import markdown_quiz, studydeck_v1
from app.core.schema import Taxonomy, Topic

ROOT = Path(__file__).resolve().parents[1]

DATABRICKS_ML = Taxonomy(
    exam="databricks-ml-associate",
    name="Databricks Certified Machine Learning Associate",
    topics=[
        Topic(id="databricks-ml", name="Databricks Machine Learning", weight=0.38),
        Topic(id="data-processing", name="Data Processing", weight=0.19),
        Topic(id="model-development", name="Model Development", weight=0.31),
        Topic(id="model-deployment", name="Model Deployment", weight=0.12),
    ],
)
QUIZ_TOPICS = {
    "section1_quiz1": ["databricks-ml"],
    "section2_quiz1": ["data-processing"],
    "section3_quiz1": ["model-development"],
    "section4_quiz1": ["model-deployment"],
    "more_quizes": [],  # mixed; per-item topics to be filled by the enrich step
}
QUIZ_NAMES = {
    "section1_quiz1": "Section 1 Quiz 1: Databricks Machine Learning",
    "section2_quiz1": "Section 2 Quiz 1: Data Processing",
    "section3_quiz1": "Section 3 Quiz 1: Model Development",
    "section4_quiz1": "Section 4 Quiz 1: Model Deployment",
    "more_quizes": "Mixed Practice Exam 1",
}

AWS_DVA = Taxonomy(
    exam="aws-dva-c02",
    name="AWS Certified Developer – Associate (DVA-C02)",
    topics=[
        Topic(id="development", name="Development with AWS Services", weight=0.32),
        Topic(id="security", name="Security", weight=0.26),
        Topic(id="deployment", name="Deployment", weight=0.24),
        Topic(id="troubleshooting", name="Troubleshooting and Optimization", weight=0.18),
    ],
)
DECK_TOPICS = {
    "dva_c02_domain1_development": "development",
    "dva_c02_domain2_security": "security",
    "dva_c02_domain3_deployment": "deployment",
    "dva_c02_domain4_troubleshooting": "troubleshooting",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quizzes", type=Path, required=True)
    ap.add_argument("--decks", type=Path, required=True)
    args = ap.parse_args()

    out_q = ROOT / "content" / "databricks-ml-associate"
    out_d = ROOT / "content" / "aws-dva-c02"
    out_q.mkdir(parents=True, exist_ok=True)
    out_d.mkdir(parents=True, exist_ok=True)

    for md in sorted(args.quizzes.glob("*.md")):
        pack, warnings = markdown_quiz.load(
            md,
            pack_slug=f"databricks-ml-associate/{md.stem}",
            name=QUIZ_NAMES.get(md.stem),
            taxonomy=DATABRICKS_ML,
            topics=QUIZ_TOPICS.get(md.stem, []),
        )
        for w in warnings:
            print(f"  warning [{md.name}]: {w}", file=sys.stderr)
        (out_q / f"{md.stem}.json").write_text(pack.to_json(), encoding="utf-8")
        print(f"{md.name} -> {out_q.name}/{md.stem}.json ({len(pack.items)} items)")

    for deck in sorted(args.decks.glob("*.json")):
        pack, progress = studydeck_v1.from_v1(
            deck.read_text(encoding="utf-8"),
            pack_slug=f"aws-dva-c02/{deck.stem}",
            source_ref=deck.name,
            taxonomy=AWS_DVA,
            default_topic=DECK_TOPICS.get(deck.stem),
        )
        if progress:
            print(f"  note [{deck.name}]: {len(progress)} cards have SM-2 progress (skipped)")
        (out_d / f"{deck.stem}.json").write_text(pack.to_json(), encoding="utf-8")
        print(f"{deck.name} -> {out_d.name}/{deck.stem}.json ({len(pack.items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
