"""Audit ordering_quiz lessons for content quality.

Checks each exercise in every ordering_quiz lesson for:
  1. no_duplicate_words: 'words[]' has no repeated entries (same data-word value)
  2. correct_constructible: every token in the 'correct' answer can be found in
     'words[]', and the word count matches (correct is constructible from words)

An exercise whose words contain duplicates leads to ambiguous UX (two identical
buttons on screen). An exercise where 'correct' is not constructible from 'words'
means the task is unsolvable.

Usage:
    python scripts/audit_ordering_quizzes.py              # dry-run report
    python scripts/audit_ordering_quizzes.py --no-db      # unit-test mode (no DB)
    python scripts/audit_ordering_quizzes.py --output PATH
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "ordering_quiz_audit.md"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExerciseAudit:
    exercise_idx: int
    no_duplicate_words: bool
    correct_constructible: bool
    words: list[str]
    correct: str
    duplicate_words: list[str]


@dataclass
class LessonAudit:
    lesson_id: int
    lesson_title: str
    module_title: str
    level_code: str
    exercises: list[ExerciseAudit] = field(default_factory=list)

    @property
    def exercises_with_duplicates(self) -> int:
        return sum(1 for e in self.exercises if not e.no_duplicate_words)

    @property
    def exercises_not_constructible(self) -> int:
        return sum(1 for e in self.exercises if not e.correct_constructible)

    @property
    def ok(self) -> bool:
        return self.exercises_with_duplicates == 0 and self.exercises_not_constructible == 0


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def _check_no_duplicates(words: list[str]) -> tuple[bool, list[str]]:
    """Return (all_unique, list_of_duplicate_words)."""
    counts = Counter(words)
    dups = [w for w, c in counts.items() if c > 1]
    return len(dups) == 0, dups


def _check_correct_constructible(words: list[str], correct: str) -> bool:
    """True if correct can be formed exactly from the given words.

    Splits correct on whitespace and compares multiset to words multiset.
    Punctuation tokens (e.g. '?') are expected as separate entries in words[].
    """
    if not correct or not words:
        return False
    correct_tokens = correct.split()
    return Counter(correct_tokens) == Counter(words)


def _get_correct(ex: dict[str, Any]) -> str:
    """Return the correct answer, checking both 'correct' and 'correct_answer' keys."""
    return (ex.get("correct") or ex.get("correct_answer") or "").strip()


def _audit_exercise(idx: int, ex: dict[str, Any]) -> ExerciseAudit:
    words: list[str] = ex.get("words") or []
    correct: str = _get_correct(ex)
    no_dups, dup_words = _check_no_duplicates(words)
    constructible = _check_correct_constructible(words, correct)
    return ExerciseAudit(
        exercise_idx=idx,
        no_duplicate_words=no_dups,
        correct_constructible=constructible,
        words=words,
        correct=correct,
        duplicate_words=dup_words,
    )


def audit_content(
    lesson_id: int,
    lesson_title: str,
    module_title: str,
    level_code: str,
    content: dict[str, Any],
) -> LessonAudit:
    exercises: list[dict] = content.get("exercises") or content.get("questions") or []
    result = LessonAudit(
        lesson_id=lesson_id,
        lesson_title=lesson_title,
        module_title=module_title,
        level_code=level_code,
    )
    for idx, ex in enumerate(exercises):
        if not isinstance(ex, dict):
            continue
        ex_type = (ex.get("type") or "").lower()
        if ex_type not in ("ordering", "reorder", ""):
            continue
        result.exercises.append(_audit_exercise(idx, ex))
    return result


# ---------------------------------------------------------------------------
# DB mode
# ---------------------------------------------------------------------------

def audit_db(db_session) -> list[LessonAudit]:
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session
    rows = (
        session.query(
            Lessons.id,
            Lessons.title,
            Module.title,
            CEFRLevel.code,
            Lessons.content,
        )
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(Lessons.type == "ordering_quiz")
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
        .all()
    )
    results = []
    for lesson_id, lesson_title, module_title, level_code, content in rows:
        if not isinstance(content, dict):
            content = {}
        results.append(
            audit_content(
                lesson_id=lesson_id,
                lesson_title=lesson_title or "",
                module_title=module_title or "",
                level_code=level_code or "",
                content=content,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_markdown(audits: list[LessonAudit]) -> str:
    lines: list[str] = [
        "# Ordering Quiz Audit",
        "",
        f"Total lessons audited: **{len(audits)}**",
        f"Lessons with issues: **{sum(1 for a in audits if not a.ok)}**",
        "",
    ]

    dup_total = sum(a.exercises_with_duplicates for a in audits)
    nc_total = sum(a.exercises_not_constructible for a in audits)
    lines += [
        f"- Exercises with duplicate words: {dup_total}",
        f"- Exercises where correct is not constructible from words: {nc_total}",
        "",
    ]

    if dup_total > 0:
        lines.append("## Exercises with duplicate words")
        lines.append("")
        lines.append("| Lesson ID | Level | Module | Ex# | Duplicates | Words |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for a in audits:
            for ex in a.exercises:
                if not ex.no_duplicate_words:
                    lines.append(
                        f"| {a.lesson_id} | {a.level_code} | {a.module_title} | "
                        f"{ex.exercise_idx} | {', '.join(ex.duplicate_words)} | "
                        f"{' '.join(ex.words)} |"
                    )
        lines.append("")

    if nc_total > 0:
        lines.append("## Exercises where correct is not constructible from words")
        lines.append("")
        lines.append("| Lesson ID | Level | Module | Lesson | Ex# | Words | Correct |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for a in audits:
            for ex in a.exercises:
                if not ex.correct_constructible:
                    lines.append(
                        f"| {a.lesson_id} | {a.level_code} | {a.module_title} | "
                        f"{a.lesson_title} | {ex.exercise_idx} | "
                        f"`{' '.join(ex.words)}` | `{ex.correct}` |"
                    )
        lines.append("")

    if dup_total == 0 and nc_total == 0:
        lines.append("All ordering_quiz exercises pass both checks.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ordering_quiz lessons")
    parser.add_argument("--no-db", action="store_true", help="Skip DB, only test logic")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    if args.no_db:
        print("[audit_ordering_quizzes] --no-db mode: nothing to do")
        return 0

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("FLASK_ENV", "development")
    from app import create_app, db as _db

    app = create_app()
    with app.app_context():
        audits = audit_db(_db)
        report = format_markdown(audits)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written to {out}")

        issues = sum(1 for a in audits if not a.ok)
        nc_total = sum(a.exercises_not_constructible for a in audits)
        if nc_total > 0:
            print(f"WARNING: {nc_total} exercises have correct answer not constructible from words!")
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
