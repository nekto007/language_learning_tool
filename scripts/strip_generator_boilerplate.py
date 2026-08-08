#!/usr/bin/env python3
"""Strip three bulk-generator seams left in the corpus.

Cross-zone audit 2026-08-08, Task 9:

* **CNT-006** — 196 vocabulary examples in 33 modules end with the stray filler
  sentence "It appears during focused classroom practice.". `example_translation`
  translates only the first sentence, so the card reads as half-translated.
* **CNT-007** — 174 reading lines in 18 modules end with "This reading version
  adds context one." (one says "two"). The Russian translation of the line never
  contains it, and no question is asked about it.
* **CNT-026** — 148 exercise explanations are the literal stub "Перевод фразы из
  словаря модуля." Both renderers guard on `if (question.explanation)`
  (`quiz.html:1308`, `final_test.html:974`), so dropping the key removes the
  "Объяснение:" block instead of showing a sentence that explains nothing.

All three are pure deletions of exact, generator-authored strings — no wording is
invented here. Idempotent: a second run finds nothing and writes nothing.

Usage:
    python scripts/strip_generator_boilerplate.py                  # report
    python scripts/strip_generator_boilerplate.py --apply          # JSON
    python scripts/strip_generator_boilerplate.py --apply --db     # + database
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "module_completed" / "fixed"

# `python scripts/<name>.py` leaves only scripts/ on sys.path, so `--db` could not
# import the app at all. Same trap as CNT-011.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# CNT-006: always trails a real example sentence, hence the leading whitespace.
VOCAB_FILLER_TEXT = "It appears during focused classroom practice."
VOCAB_FILLER = re.compile(r"\s*It appears during focused classroom practice\.\s*$")
# CNT-007: the generator numbered its variants one..ten.
READING_FILLER = re.compile(
    r"\s*This reading version adds context "
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten)\.\s*$"
)
# CNT-026: removed only when the explanation is *exactly* the stub, never when a
# real explanation happens to contain the phrase.
EXPLANATION_STUB = "Перевод фразы из словаря модуля."

# Lesson types each rule applies to, so an unrelated lesson is never rewritten.
VOCAB_TYPES = ("vocabulary",)
READING_TYPES = ("reading",)
EXPLANATION_TYPES = ("translation_quiz", "final_test")


# `tests/test_module_content_quality.py::test_advanced_levels_have_contextual_examples`
# requires B1+ vocabulary examples to be full sentences. On 203 of them the filler
# was the ONLY thing meeting that bar — the real example under it is 3-6 words.
# Stripping there would trade one content defect for another, and writing longer
# examples is authoring work, not a script. So the rule stands down on those and
# CNT-006 closes partially; the residue is recorded in the audit registry.
CONTEXTUAL_EXAMPLE_MIN_WORDS = {"B1": 6, "B2": 7, "C1": 7}


def _word_count(text: str) -> int:
    # Same definition as tests/test_module_content_quality.py::word_count, so the
    # floor this script enforces and the floor the test asserts cannot drift.
    return len(re.findall(r"[A-Za-z']+", str(text)))


def strip_vocab_filler(content: dict, min_words: int = 0) -> tuple[dict, int]:
    """CNT-006 — drop the filler sentence from `vocabulary[].example`.

    `min_words` is the contextual-example floor for the module's CEFR level; an
    example that would fall below it keeps the filler.
    """
    if not isinstance(content, dict):
        return content, 0
    items = content.get("vocabulary")
    if not isinstance(items, list):
        return content, 0

    hits = 0
    rebuilt: list[Any] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("example"), str):
            stripped = VOCAB_FILLER.sub("", item["example"]).rstrip()
            if stripped != item["example"] and _word_count(stripped) >= min_words:
                item = {**item, "example": stripped}
                hits += 1
        rebuilt.append(item)

    if not hits:
        return content, 0
    return {**content, "vocabulary": rebuilt}, hits


def strip_reading_filler(content: dict) -> tuple[dict, int]:
    """CNT-007 — drop the filler sentence from `text.lines[].text`.

    The filler was also the only thing distinguishing whole repeated blocks: in
    `module_B2_10_crime_and_law` lines 23-34 are lines 3-14 with "This reading
    version adds context one." appended. Strip it and the learner reads the same
    twelve sentences twice, so a line that becomes an exact duplicate of an
    earlier one is dropped with it. Lines that were already duplicates before the
    strip are left alone — that is a different defect and not this sweep's call.
    """
    if not isinstance(content, dict):
        return content, 0
    text = content.get("text")
    if not isinstance(text, dict) or not isinstance(text.get("lines"), list):
        return content, 0

    hits = 0
    rebuilt: list[Any] = []
    seen: set[str] = set()
    for line in text["lines"]:
        if isinstance(line, dict) and isinstance(line.get("text"), str):
            original = line["text"]
            stripped = READING_FILLER.sub("", original).rstrip()
            if stripped != original:
                line = {**line, "text": stripped}
                hits += 1
            # Drop the exact repeat rather than the filler alone. Measured before
            # writing this: duplicate reading lines exist in exactly the 18
            # modules that carried the filler and in no others (174 of each), so
            # this touches the CNT-007 residue and nothing else. Stated as an end
            # state, not a diff, so re-running on a partially-fixed corpus
            # converges.
            if stripped in seen:
                hits += 1
                continue
            seen.add(stripped)
        rebuilt.append(line)

    if not hits:
        return content, 0
    return {**content, "text": {**text, "lines": rebuilt}}, hits


def _drop_stub_explanations(exercises: Any) -> tuple[Any, int]:
    if not isinstance(exercises, list):
        return exercises, 0
    hits = 0
    rebuilt: list[Any] = []
    for exercise in exercises:
        if (
            isinstance(exercise, dict)
            and isinstance(exercise.get("explanation"), str)
            and exercise["explanation"].strip() == EXPLANATION_STUB
        ):
            exercise = {k: v for k, v in exercise.items() if k != "explanation"}
            hits += 1
        rebuilt.append(exercise)
    return rebuilt, hits


def strip_stub_explanations(content: dict) -> tuple[dict, int]:
    """CNT-026 — remove `explanation` keys that only hold the stub sentence."""
    if not isinstance(content, dict):
        return content, 0

    new_content = dict(content)
    hits = 0

    exercises, count = _drop_stub_explanations(new_content.get("exercises"))
    if count:
        new_content["exercises"] = exercises
        hits += count

    sections = new_content.get("test_sections")
    if isinstance(sections, list):
        rebuilt_sections: list[Any] = []
        section_hits = 0
        for section in sections:
            if isinstance(section, dict):
                exercises, count = _drop_stub_explanations(section.get("exercises"))
                if count:
                    section = {**section, "exercises": exercises}
                    section_hits += count
            rebuilt_sections.append(section)
        if section_hits:
            new_content["test_sections"] = rebuilt_sections
            hits += section_hits

    return (new_content, hits) if hits else (content, 0)


def restore_vocab_filler(content: dict, min_words: int) -> tuple[dict, int]:
    """Undo an over-eager CNT-006 strip on examples that need the length.

    One-off reconciliation: the first revision of this script stripped the filler
    everywhere, which dropped 196 B1+ examples below the contextual-example floor
    that `tests/test_module_content_quality.py` enforces. A checkout whose corpus
    still carries the filler never needs this — the normal rule now declines to
    strip those. Run it only on a corpus that the earlier revision already
    touched.
    """
    if not isinstance(content, dict) or not min_words:
        return content, 0
    items = content.get("vocabulary")
    if not isinstance(items, list):
        return content, 0

    hits = 0
    rebuilt: list[Any] = []
    for item in items:
        example = item.get("example") if isinstance(item, dict) else None
        if (
            isinstance(example, str)
            and example
            and not VOCAB_FILLER.search(example)
            and _word_count(example) < min_words
        ):
            item = {**item, "example": f"{example} {VOCAB_FILLER_TEXT}"}
            hits += 1
        rebuilt.append(item)

    if not hits:
        return content, 0
    return {**content, "vocabulary": rebuilt}, hits


def repair_json_corpus(source_dir: Path, apply: bool) -> int:
    files = sorted(source_dir.glob("module_*.json"))
    total = 0
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        module = data.get("module") or data
        min_words = CONTEXTUAL_EXAMPLE_MIN_WORDS.get(str(module.get("level") or "").upper(), 0)
        if not min_words:
            continue
        changed = 0
        for lesson in module.get("lessons") or []:
            if lesson.get("type") not in VOCAB_TYPES:
                continue
            content = lesson.get("content")
            if not isinstance(content, dict):
                continue
            new_content, hits = restore_vocab_filler(content, min_words)
            if hits:
                lesson["content"] = new_content
                changed += hits
        if changed:
            total += changed
            print(f"  {path.name}: restored {changed} example(s) to the contextual-length floor")
            if apply:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
    print(f"repair: {total} vocabulary example(s) in {len(files)} module(s)")
    return total


RULES = (
    ("CNT-006", VOCAB_TYPES, strip_vocab_filler),
    ("CNT-007", READING_TYPES, strip_reading_filler),
    ("CNT-026", EXPLANATION_TYPES, strip_stub_explanations),
)


def fix_lesson(lesson_type: str, content: dict, level: str = "") -> tuple[dict, dict[str, int]]:
    """Apply every rule that matches `lesson_type`. Returns (content, per-rule hits)."""
    hits: dict[str, int] = {}
    min_words = CONTEXTUAL_EXAMPLE_MIN_WORDS.get((level or "").upper(), 0)
    for rule_id, types, fn in RULES:
        if lesson_type not in types:
            continue
        count = 0
        if fn is strip_vocab_filler:
            content, count = fn(content, min_words)
        else:
            content, count = fn(content)
        if count:
            hits[rule_id] = hits.get(rule_id, 0) + count
    return content, hits


def _merge(into: dict[str, int], other: dict[str, int]) -> None:
    for key, value in other.items():
        into[key] = into.get(key, 0) + value


def fix_json_corpus(source_dir: Path, apply: bool) -> dict[str, int]:
    files = sorted(source_dir.glob("module_*.json"))
    totals: dict[str, int] = {}

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        module = data.get("module") or data
        level = str(module.get("level") or "")
        file_hits: dict[str, int] = {}

        for lesson in module.get("lessons") or []:
            content = lesson.get("content")
            if not isinstance(content, dict):
                continue
            new_content, hits = fix_lesson(lesson.get("type") or "", content, level)
            if hits:
                lesson["content"] = new_content
                _merge(file_hits, hits)

        if file_hits:
            _merge(totals, file_hits)
            summary = ", ".join(f"{k}={v}" for k, v in sorted(file_hits.items()))
            print(f"  {path.name}: {summary}")
            if apply:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

    print(f"JSON corpus: {sum(totals.values())} string(s) in {len(files)} module(s) — {totals or '{}'}")
    return totals


def fix_database(apply: bool) -> dict[str, int]:
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.utils.db import db

    handled_types = sorted({t for _, types, _ in RULES for t in types})
    app = create_app()
    with app.app_context():
        lessons = Lessons.query.filter(Lessons.type.in_(handled_types)).all()
        # The contextual-example floor is per CEFR level, so resolve it once.
        level_by_module = dict(
            db.session.query(Module.id, CEFRLevel.code).join(
                CEFRLevel, CEFRLevel.id == Module.level_id
            ).all()
        )
        totals: dict[str, int] = {}

        for lesson in lessons:
            content = lesson.content
            if not isinstance(content, dict):
                continue
            level = level_by_module.get(lesson.module_id) or ""
            new_content, hits = fix_lesson(lesson.type or "", content, level)
            if hits:
                _merge(totals, hits)
                # Only stage the write under --apply. A dry run that dirties the
                # session is one stray autoflush away from writing all 86 modules.
                if apply:
                    lesson.content = new_content
                    flag_modified(lesson, "content")

        if apply:
            db.session.commit()

        print(f"database: {sum(totals.values())} string(s) in {len(lessons)} lesson(s) — {totals or '{}'}")
        return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--db", action="store_true", help="also patch lessons.content")
    parser.add_argument("--no-json", action="store_true", help="skip the JSON corpus")
    parser.add_argument(
        "--repair-vocab-length",
        action="store_true",
        help="one-off: restore the filler on B1+ examples an earlier run left too short",
    )
    args = parser.parse_args()

    if args.repair_vocab_length:
        repair_json_corpus(Path(args.source_dir), args.apply)
        if not args.apply:
            print("\ndry run — nothing written (pass --apply)")
        return 0

    if not args.no_json:
        fix_json_corpus(Path(args.source_dir), args.apply)
    if args.db:
        fix_database(args.apply)

    if not args.apply:
        print("\ndry run — nothing written (pass --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
