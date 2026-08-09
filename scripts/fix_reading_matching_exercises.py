#!/usr/bin/env python3
"""Turn unrenderable `matching` exercises in reading lessons into multiple choice.

Audit CNT-002 (cross-zone audit 2026-08-08): `curriculum/lessons/text.html`
renders `true_false`, `multiple_choice`, `fill_blank`+options and `ordering`;
anything else falls through to a bare text input. Fourteen reading lessons carry
a `matching` exercise, so the learner is shown "Соотнесите слова с переводом"
above an empty input box with no pairs on screen — a question that cannot be
answered. Worse, `data-correct` is taken from `question.correct`, which is the
literal `false` in these payloads.

Each matching exercise is expanded into one `multiple_choice` question per pair
("Что означает «can»?" with translations of the sibling pairs as distractors),
which keeps every vocabulary item the author put there and produces payloads the
existing renderer and grader already handle.

Deterministic: option order and distractor choice depend only on the pair list,
so re-running produces byte-identical output. Idempotent: exercises that are no
longer `matching` are left alone.

Usage:
    python scripts/fix_reading_matching_exercises.py                  # report
    python scripts/fix_reading_matching_exercises.py --apply          # JSON
    python scripts/fix_reading_matching_exercises.py --apply --db     # + database
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "module_completed" / "fixed"

MAX_OPTIONS = 4


def _pair_sides(pair: dict) -> tuple[str, str]:
    """Read a pair in any of the shapes the corpus uses."""
    left = pair.get("english") or pair.get("left") or pair.get("word") or pair.get("term") or ""
    right = (
        pair.get("russian") or pair.get("right")
        or pair.get("translation") or pair.get("match") or ""
    )
    return str(left).strip(), str(right).strip()


def expand_matching(exercise: dict) -> list[dict]:
    """Expand one `matching` exercise into a list of `multiple_choice` ones.

    Returns `[exercise]` unchanged when the payload is not an expandable
    matching item, so callers can map over a whole exercise list.
    """
    if exercise.get("type") != "matching":
        return [exercise]

    pairs = [p for p in (exercise.get("pairs") or []) if isinstance(p, dict)]
    sides = [_pair_sides(p) for p in pairs]
    sides = [(left, right) for left, right in sides if left and right]
    if len(sides) < 2:
        # Nothing to build options from — leave it for a human.
        return [exercise]

    all_right = [right for _left, right in sides]
    expanded: list[dict] = []

    for index, (left, right) in enumerate(sides):
        distractors = [r for r in all_right if r != right][: MAX_OPTIONS - 1]
        options = sorted({right, *distractors})
        # Rotate so the answer lands in a different slot on each question —
        # deterministically, and relative to the answer rather than to the list,
        # otherwise sorting can keep it in the same position every time.
        target_slot = index % len(options)
        shift = (options.index(right) - target_slot) % len(options)
        options = options[shift:] + options[:shift]

        expanded.append({
            "type": "multiple_choice",
            "question": f"Что означает «{left}»?",
            "options": options,
            "correct": right,
            "correct_answer": right,
            "explanation": exercise.get("explanation") or "",
            "instruction": None,
            "words": None,
        })

    return expanded


def _exercise_lists(content: dict) -> list[list]:
    """Every list in a reading payload that can hold exercises."""
    lists = []
    for key in ("exercises", "questions"):
        value = content.get(key)
        if isinstance(value, list):
            lists.append(value)
    return lists


def fix_content(content: dict) -> tuple[dict, int]:
    """Return (new_content, number_of_matching_exercises_expanded)."""
    if not isinstance(content, dict):
        return content, 0

    expanded_count = 0
    new_content = dict(content)

    for key in ("exercises", "questions"):
        value = new_content.get(key)
        if not isinstance(value, list):
            continue
        rebuilt: list[Any] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "matching":
                replacement = expand_matching(item)
                if replacement != [item]:
                    expanded_count += 1
                rebuilt.extend(replacement)
            else:
                rebuilt.append(item)
        new_content[key] = rebuilt

    return new_content, expanded_count


def _iter_reading_lessons(module: dict):
    for lesson in module.get("lessons") or []:
        if lesson.get("type") == "reading":
            yield lesson


def fix_json_corpus(source_dir: Path, apply: bool) -> int:
    files = sorted(source_dir.glob("module_*.json"))
    total = 0

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        module = data.get("module") or data
        changed = 0

        for lesson in _iter_reading_lessons(module):
            new_content, count = fix_content(lesson.get("content") or {})
            if count:
                lesson["content"] = new_content
                changed += count

        if changed:
            total += changed
            print(f"  {path.name}: expanded {changed} matching exercise(s)")
            if apply:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    print(f"JSON corpus: {total} matching exercise(s) in {len(files)} module(s)")
    return total


def fix_database(apply: bool) -> int:
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app
    from app.curriculum.models import Lessons
    from app.utils.db import db

    app = create_app()
    with app.app_context():
        lessons = Lessons.query.filter(Lessons.type == "reading").all()
        total = 0

        for lesson in lessons:
            new_content, count = fix_content(lesson.content or {})
            if not count:
                continue
            total += count
            print(f"  lesson {lesson.id}: expanded {count} matching exercise(s)")
            if apply:
                lesson.content = new_content
                flag_modified(lesson, "content")

        if apply:
            db.session.commit()

        print(f"database: {total} matching exercise(s) across {len(lessons)} reading lesson(s)")
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
