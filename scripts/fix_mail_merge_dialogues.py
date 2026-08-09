#!/usr/bin/env python3
"""Remove dialogue-completion exercises whose slot was mail-merged incorrectly.

Audit CNT-009 (cross-zone audit 2026-08-08). The generator dropped a word from
the module vocabulary into a fixed dialogue frame without checking its part of
speech, then declared the result the correct answer:

    "Do you have a brown?"          → correct: "Yes, I have a brown."
    "Tell me about your tell — told." → correct: "My tell — told is special to me."
    "What is your favorite keep — kept?" → correct: "My favorite keep — kept is the new one."

Writing replacements is authorial work, so this script only deletes — an absent
question is better than one that teaches ungrammatical English.

**Deliberately narrow.** The audit's own regex reported ~110 candidates and
called that a lower bound with an unverified spread up to 226. Reproducing a
loose frame match here would delete good content: "a piece of cake — easier than
I thought", "once in a blue moon" and "found a wallet on the street — what would
you do?" all trip naive dash/adjective rules. This script fires only on the
mechanical mail-merge signature, where the slot filler is *echoed verbatim* from
the prompt into the answer:

  * ``verb_pair_echoed`` — a determiner followed by an irregular-verb pair
    ("your tell — told") that reappears in the correct answer.
  * ``adjective_echoed_without_head_noun`` — "a/an <adjective>" with no head
    noun, in both the prompt and the answer ("Do you have a brown?").

Everything the audit flagged on semantic grounds ("What is your favorite debt?")
needs a human and is left in place; the script prints how many exercises it
looked at so the gap is visible rather than implied.

Usage:
    python scripts/fix_mail_merge_dialogues.py                # report
    python scripts/fix_mail_merge_dialogues.py --apply        # JSON corpus
    python scripts/fix_mail_merge_dialogues.py --apply --db   # + database
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "module_completed" / "fixed"

LESSON_TYPE = "dialogue_completion_quiz"

_DETERMINER = r"(?:a|an|the|my|your|his|her|our|their|favorite|favourite)"
_VERB_PAIR = re.compile(rf"\b{_DETERMINER}\s+([a-z]+\s*[—–]\s*[a-z]+)", re.IGNORECASE)

# Closed list — every one of these appears in the corpus as a colour/quality
# adjective, never as a head noun.
_ADJECTIVES = (
    "brown", "red", "blue", "green", "black", "white", "yellow", "orange",
    "cold", "hot", "warm", "cool", "tasty", "healthy", "fresh", "honest",
    "delicious", "sunny", "rainy", "cloudy", "foggy", "clean", "viral", "wireless",
)
_ADJ_NO_HEAD = re.compile(
    rf"\b(?:a|an)\s+(?:{'|'.join(_ADJECTIVES)})\s*[?.!]", re.IGNORECASE,
)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or ""))


def prompt_text(exercise: dict) -> str:
    """Flatten the dialogue, which appears as a string or a list of turns."""
    dialogue = exercise.get("dialogue")
    if isinstance(dialogue, str):
        return dialogue
    if isinstance(dialogue, list):
        return " | ".join(
            f"{turn.get('speaker')}: {turn.get('text')}"
            for turn in dialogue if isinstance(turn, dict)
        )
    return ""


def broken_reasons(exercise: dict) -> list[str]:
    """Why this exercise is provably mail-merge broken (empty list = keep it)."""
    prompt = _squash(prompt_text(exercise))
    answer = _squash(exercise.get("correct") or exercise.get("answer") or "")
    reasons: list[str] = []

    for match in _VERB_PAIR.finditer(prompt):
        if _squash(match.group(1)) in answer:
            reasons.append("verb_pair_echoed")
            break

    if _ADJ_NO_HEAD.search(prompt) and _ADJ_NO_HEAD.search(answer):
        reasons.append("adjective_echoed_without_head_noun")

    return reasons


def filter_exercises(content: dict) -> tuple[dict, list[tuple[int, list[str], str]]]:
    """Return (new_content, [(index, reasons, prompt), …])."""
    exercises = content.get("exercises")
    if not isinstance(exercises, list):
        return content, []

    kept: list[Any] = []
    dropped: list[tuple[int, list[str], str]] = []

    for index, exercise in enumerate(exercises):
        reasons = broken_reasons(exercise) if isinstance(exercise, dict) else []
        if reasons:
            dropped.append((index, reasons, _squash(prompt_text(exercise))))
        else:
            kept.append(exercise)

    if not dropped:
        return content, []

    new_content = dict(content)
    new_content["exercises"] = kept
    return new_content, dropped


def fix_json_corpus(source_dir: Path, apply: bool) -> tuple[int, int]:
    total_dropped = 0
    total_seen = 0

    for path in sorted(source_dir.glob("module_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        module = data.get("module") or data
        changed = False

        for lesson in module.get("lessons") or []:
            if lesson.get("type") != LESSON_TYPE:
                continue
            content = lesson.get("content") or {}
            total_seen += len(content.get("exercises") or [])
            new_content, dropped = filter_exercises(content)
            if not dropped:
                continue
            changed = True
            total_dropped += len(dropped)
            lesson["content"] = new_content
            for index, reasons, prompt in dropped:
                print(f"  {path.name} L{lesson.get('number')} ex[{index}] {reasons}: {prompt}")

        if changed and apply:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )

    print(f"JSON corpus: dropped {total_dropped} of {total_seen} dialogue exercise(s)")
    return total_dropped, total_seen


def fix_database(apply: bool) -> int:
    from sqlalchemy.orm.attributes import flag_modified

    from app import create_app
    from app.curriculum.models import Lessons
    from app.utils.db import db

    app = create_app()
    with app.app_context():
        lessons = Lessons.query.filter(Lessons.type == LESSON_TYPE).all()
        total = 0
        for lesson in lessons:
            new_content, dropped = filter_exercises(lesson.content or {})
            if not dropped:
                continue
            total += len(dropped)
            for index, reasons, prompt in dropped:
                print(f"  lesson {lesson.id} ex[{index}] {reasons}: {prompt}")
            if apply:
                lesson.content = new_content
                flag_modified(lesson, "content")

        if apply:
            db.session.commit()
        print(f"database: dropped {total} exercise(s) from {len(lessons)} lesson(s)")
        return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", action="store_true")
    parser.add_argument("--no-json", action="store_true")
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
