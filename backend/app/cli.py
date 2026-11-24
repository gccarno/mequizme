"""`studypack` command line: generate the schema, validate packs, convert sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.adapters import markdown_quiz, studydeck_v1
from app.core.schema import StudyPack

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "studypack.v2.schema.json"


def schema_text() -> str:
    schema = StudyPack.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://mequizme.local/schema/studypack.v2.schema.json"
    return json.dumps(schema, indent=2) + "\n"


def cmd_schema(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else SCHEMA_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(schema_text(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def iter_pack_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.json")) if p.is_dir() else [p])
    return files


def cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    for f in iter_pack_files(args.paths):
        try:
            pack = StudyPack.from_json(f.read_text(encoding="utf-8"))
            print(f"ok    {f}  ({len(pack.items)} items, {len(pack.quizzes)} quizzes)")
        except ValidationError as e:
            failed += 1
            print(f"FAIL  {f}\n{e}", file=sys.stderr)
    return 1 if failed else 0


def _write(pack: StudyPack, out: str | None) -> None:
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(pack.to_json(), encoding="utf-8")
        print(f"wrote {out}  ({len(pack.items)} items)")
    else:
        sys.stdout.write(pack.to_json())


def cmd_convert_md(args: argparse.Namespace) -> int:
    pack, warnings = markdown_quiz.load(Path(args.file), name=args.name, topics=args.topic or None)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    _write(pack, args.out)
    return 0


def cmd_convert_studydeck(args: argparse.Namespace) -> int:
    path = Path(args.file)
    pack, progress = studydeck_v1.from_v1(
        path.read_text(encoding="utf-8"), pack_slug=path.stem, source_ref=path.name
    )
    if progress:
        print(f"note: {len(progress)} cards carry SM-2 progress (not written to the pack)", file=sys.stderr)
    _write(pack, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studypack")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schema", help="write the JSON Schema generated from the models")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_schema)

    v = sub.add_parser("validate", help="validate pack files or directories")
    v.add_argument("paths", nargs="+")
    v.set_defaults(fn=cmd_validate)

    m = sub.add_parser("convert-md", help="markdown quiz -> study pack")
    m.add_argument("file")
    m.add_argument("--out")
    m.add_argument("--name")
    m.add_argument("--topic", action="append", help="topic id applied to every item")
    m.set_defaults(fn=cmd_convert_md)

    d = sub.add_parser("convert-studydeck", help="StudyDeck v1 deck JSON -> study pack")
    d.add_argument("file")
    d.add_argument("--out")
    d.set_defaults(fn=cmd_convert_studydeck)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
