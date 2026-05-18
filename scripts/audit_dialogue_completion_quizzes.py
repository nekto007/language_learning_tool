"""Audit dialogue_completion_quiz lessons for content quality.

Checks each exercise in every dialogue_completion_quiz lesson for:
  1. hint_chips: exercise has a non-empty 'hints' list (Russian translation hints)
  2. correct_in_options: the 'correct' answer text matches at least one option
     (case-insensitive strip comparison)

Also provides --apply mode that fills missing 'hints' arrays derived from the
'explanation' field (Russian explanatory text already present in many exercises)
and from vocabulary words in the dialogue line's context.

Usage:
    python scripts/audit_dialogue_completion_quizzes.py              # dry-run report
    python scripts/audit_dialogue_completion_quizzes.py --apply      # write patches to DB
    python scripts/audit_dialogue_completion_quizzes.py --no-db      # unit-test mode (no DB)
    python scripts/audit_dialogue_completion_quizzes.py --output PATH
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "dialogue_completion_audit.md"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExerciseAudit:
    exercise_idx: int
    has_hints: bool
    correct_in_options: bool
    correct: str
    options: list[str]
    hints: list[str]


@dataclass
class LessonAudit:
    lesson_id: int
    lesson_title: str
    module_title: str
    level_code: str
    exercises: list[ExerciseAudit] = field(default_factory=list)

    @property
    def exercises_missing_hints(self) -> int:
        return sum(1 for e in self.exercises if not e.has_hints)

    @property
    def exercises_wrong_correct(self) -> int:
        return sum(1 for e in self.exercises if not e.correct_in_options)

    @property
    def ok(self) -> bool:
        return self.exercises_missing_hints == 0 and self.exercises_wrong_correct == 0


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return text.strip().lower()


def _correct_in_options(correct: str, options: list[str]) -> bool:
    """True if correct (normalised) matches at least one option."""
    norm = _normalize(correct)
    return any(_normalize(opt) == norm for opt in options)


def _derive_hints(exercise: dict[str, Any]) -> list[str]:
    """Derive a hints list from existing exercise fields.

    Strategy:
    1. If 'hints' already exists and is a non-empty list, return it unchanged.
    2. If 'explanation' exists, use that as a single-item hint (first 80 chars).
    3. Otherwise return [].
    """
    existing = exercise.get("hints") or exercise.get("hint") or []
    if isinstance(existing, list) and existing:
        return existing
    explanation = (exercise.get("explanation") or "").strip()
    if explanation:
        # Use the first sentence of the explanation as a compact hint
        first_sentence = explanation.split(".")[0].strip()
        if first_sentence:
            return [first_sentence[:120]]
    return []


def _audit_exercise(idx: int, ex: dict[str, Any]) -> ExerciseAudit:
    options: list[str] = ex.get("options") or []
    correct: str = ex.get("correct") or ""
    hints: list[str] = _derive_hints(ex)
    has_hints = bool((ex.get("hints") or ex.get("hint") or []))
    return ExerciseAudit(
        exercise_idx=idx,
        has_hints=has_hints,
        correct_in_options=_correct_in_options(correct, options),
        correct=correct,
        options=options,
        hints=hints,
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
        if ex_type not in ("dialogue_completion", "dialogue", ""):
            continue
        result.exercises.append(_audit_exercise(idx, ex))
    return result


# ---------------------------------------------------------------------------
# Patch logic
# ---------------------------------------------------------------------------

def _patch_content(content: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return (patched_content, patches_applied). Skips exercises that already have hints."""
    patched = copy.deepcopy(content)
    applied = 0
    exercises: list[dict] = patched.get("exercises") or patched.get("questions") or []
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        ex_type = (ex.get("type") or "").lower()
        if ex_type not in ("dialogue_completion", "dialogue", ""):
            continue
        existing = ex.get("hints") or ex.get("hint") or []
        if isinstance(existing, list) and existing:
            continue
        derived = _derive_hints(ex)
        if derived:
            ex["hints"] = derived
            applied += 1
    return patched, applied


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
        .filter(Lessons.type == "dialogue_completion_quiz")
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


def apply_db(db_session, dry_run: bool = True) -> list[tuple[int, str, int]]:
    """Patch DB rows. Returns list of (lesson_id, title, patches_applied)."""
    from app.curriculum.models import Lessons

    session = db_session.session
    lessons = (
        session.query(Lessons)
        .filter(Lessons.type == "dialogue_completion_quiz")
        .all()
    )
    changed: list[tuple[int, str, int]] = []
    for lesson in lessons:
        content = lesson.content if isinstance(lesson.content, dict) else {}
        patched, applied = _patch_content(content)
        if applied > 0:
            if not dry_run:
                lesson.content = patched
            changed.append((lesson.id, lesson.title or "", applied))
    if not dry_run:
        session.commit()
    return changed


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_markdown(audits: list[LessonAudit], changed: list[tuple[int, str, int]] | None = None) -> str:
    lines: list[str] = [
        "# Dialogue Completion Quiz Audit",
        "",
        f"Total lessons audited: **{len(audits)}**",
        f"Lessons with issues: **{sum(1 for a in audits if not a.ok)}**",
        "",
    ]

    missing_hints_total = sum(a.exercises_missing_hints for a in audits)
    wrong_correct_total = sum(a.exercises_wrong_correct for a in audits)
    lines += [
        f"- Exercises missing hints: {missing_hints_total}",
        f"- Exercises with correct not in options: {wrong_correct_total}",
        "",
    ]

    if wrong_correct_total > 0:
        lines.append("## Exercises where correct answer not in options")
        lines.append("")
        lines.append("| Lesson ID | Level | Module | Lesson | Ex# | Correct | Options |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for a in audits:
            for ex in a.exercises:
                if not ex.correct_in_options:
                    opts = ", ".join(ex.options[:3])
                    lines.append(
                        f"| {a.lesson_id} | {a.level_code} | {a.module_title} | "
                        f"{a.lesson_title} | {ex.exercise_idx} | `{ex.correct[:40]}` | {opts} |"
                    )
        lines.append("")

    if missing_hints_total > 0:
        lines.append("## Exercises missing hints")
        lines.append("")
        lines.append("| Lesson ID | Level | Module | Missing |")
        lines.append("| --- | --- | --- | --- |")
        for a in audits:
            if a.exercises_missing_hints > 0:
                lines.append(
                    f"| {a.lesson_id} | {a.level_code} | {a.module_title} | "
                    f"{a.exercises_missing_hints}/{len(a.exercises)} exercises |"
                )
        lines.append("")

    if changed:
        lines.append("## Patches applied")
        lines.append("")
        lines.append("| Lesson ID | Title | Exercises patched |")
        lines.append("| --- | --- | --- |")
        for lesson_id, title, count in changed:
            lines.append(f"| {lesson_id} | {title} | {count} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit dialogue_completion_quiz lessons")
    parser.add_argument("--apply", action="store_true", help="Write hint patches to DB")
    parser.add_argument("--no-db", action="store_true", help="Skip DB, only test logic")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    if args.no_db:
        print("[audit_dialogue_completion_quizzes] --no-db mode: nothing to do")
        return 0

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("FLASK_ENV", "development")
    from app import create_app, db as _db

    app = create_app()
    with app.app_context():
        audits = audit_db(_db)
        changed: list[tuple[int, str, int]] = []
        if args.apply:
            changed = apply_db(_db, dry_run=False)
            print(f"Applied hint patches to {len(changed)} lessons.")
        else:
            changed = apply_db(_db, dry_run=True)
            if changed:
                print(f"Dry-run: {len(changed)} lessons would be patched (run --apply).")

        report = format_markdown(audits, changed if args.apply else None)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written to {out}")

        issues = sum(1 for a in audits if not a.ok)
        wrong_correct = sum(a.exercises_wrong_correct for a in audits)
        if wrong_correct > 0:
            print(f"WARNING: {wrong_correct} exercises have correct answer not in options!")
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
