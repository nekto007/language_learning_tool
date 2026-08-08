#!/usr/bin/env python3
"""Detach the A1 starter scaffolding from writing prompts it does not belong to.

Audit CNT-010 (cross-zone audit 2026-08-08). Thirty-two `writing_prompt` lessons
carry the same generated scaffolding — `target_phrases: ["This is","That is",
"I have","I like"]`, the template "This is a ___. That is a ___. …" and a
`hint_words` list that opens with those same four phrases plus "a"/"an" — while
the prompt above asks for something else entirely ("Describe your plans for next
week … Use 'going to'").

Two consequences, in order of weight:

1. `lessons.py:1775` sets `target_phrases_required = bool(target_phrases and
   mode == 'guided')`, so completion is gated on the learner using one of four
   phrases from a different exercise. Natural answers often contain "I like" by
   accident, which is why the lesson usually passes — but when it doesn't, the
   learner has no way to know what is missing.
2. The on-screen template contradicts the task it sits under.

The rule here is mechanical and touches nothing that was authored:

* `target_phrases` is dropped only when it is exactly the four-phrase starter set;
* `template` is dropped only when it is the generated "This is a ___." skeleton —
  the two lessons with a bespoke, on-topic template keep it;
* `hint_words` loses only the leading generic prefix, keeping every topical word.

`mode` is left alone (all 32 declare `guided` explicitly, so the auto-derive in
`lessons.py:1645` never sees these lessons).

Idempotent: a second run finds nothing.

Usage:
    python scripts/fix_writing_prompt_scaffolding.py                  # report
    python scripts/fix_writing_prompt_scaffolding.py --apply          # JSON
    python scripts/fix_writing_prompt_scaffolding.py --apply --db     # + database
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "module_completed" / "fixed"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The generated starter set, matched exactly — an authored list that merely
# overlaps is left alone.
STARTER_PHRASES = ["This is", "That is", "I have", "I like"]
# Leading filler in `hint_words`; everything after it is topical vocabulary.
STARTER_HINT_PREFIX = ["This is", "That is", "I have", "I like", "a", "an"]
# Both generated template variants start with these two lines.
TEMPLATE_HEAD = "This is a ___.\nThat is a ___."


def _is_starter_scaffolded(content: dict) -> bool:
    return isinstance(content, dict) and content.get("target_phrases") == STARTER_PHRASES


def strip_starter_scaffolding(content: dict) -> tuple[dict, list[str]]:
    """Return (new_content, list of fields cleared)."""
    if not _is_starter_scaffolded(content):
        return content, []

    new_content = dict(content)
    cleared: list[str] = []

    new_content.pop("target_phrases", None)
    cleared.append("target_phrases")

    template = new_content.get("template")
    if isinstance(template, str) and template.startswith(TEMPLATE_HEAD):
        new_content.pop("template", None)
        cleared.append("template")

    hints = new_content.get("hint_words")
    if isinstance(hints, list) and hints[: len(STARTER_HINT_PREFIX)] == STARTER_HINT_PREFIX:
        remainder = hints[len(STARTER_HINT_PREFIX):]
        if remainder:
            new_content["hint_words"] = remainder
        else:
            new_content.pop("hint_words", None)
        cleared.append("hint_words")

    return new_content, cleared


def fix_json_corpus(source_dir: Path, apply: bool) -> int:
    files = sorted(source_dir.glob("module_*.json"))
    total = 0

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        module = data.get("module") or data
        changed: list[str] = []

        for lesson in module.get("lessons") or []:
            if lesson.get("type") != "writing_prompt":
                continue
            new_content, cleared = strip_starter_scaffolding(lesson.get("content") or {})
            if cleared:
                lesson["content"] = new_content
                changed.extend(cleared)

        if changed:
            total += 1
            print(f"  {path.name}: cleared {', '.join(changed)}")
            if apply:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    print(f"JSON corpus: {total} writing_prompt lesson(s) in {len(files)} module(s)")
    return total


def fix_database(apply: bool) -> int:
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app
    from app.curriculum.models import Lessons
    from app.utils.db import db

    app = create_app()
    with app.app_context():
        lessons = Lessons.query.filter(Lessons.type == "writing_prompt").all()
        total = 0

        for lesson in lessons:
            new_content, cleared = strip_starter_scaffolding(lesson.content or {})
            if cleared:
                total += 1
                lesson.content = new_content
                flag_modified(lesson, "content")

        if apply:
            db.session.commit()

        print(f"database: {total} writing_prompt lesson(s) of {len(lessons)}")
        return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--db", action="store_true", help="also patch lessons.content")
    parser.add_argument("--no-json", action="store_true", help="skip the JSON corpus")
    args = parser.parse_args()

    if not args.no_json:
        fix_json_corpus(Path(args.source_dir), args.apply)
    if args.db:
        fix_database(args.apply)

    if not args.apply:
        print("\ndry run — nothing written (pass --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
