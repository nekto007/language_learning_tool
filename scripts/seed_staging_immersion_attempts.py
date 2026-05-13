"""Seed staging ListeningAttempt, UserWritingAttempt, and PronunciationAttempt rows.

Finds imported dictation, writing_prompt, and pronunciation lessons in the DB,
then inserts sample attempt rows for the target user so that dashboard widgets
(get_listening_stats, get_writing_stats, get_pronunciation_stats) show non-empty
data in a staging environment.

Flags:
    --user-id       target user id (required unless --no-db)
    --dry-run       show what would be inserted, no DB writes
    --report PATH   write markdown summary to PATH
    --no-db         skip DB, exit 0 (for CI)

Usage:
    python scripts/seed_staging_immersion_attempts.py --user-id 1
    python scripts/seed_staging_immersion_attempts.py --user-id 1 --dry-run

Task 47 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DICTATION_LESSON_TYPE = "dictation"
WRITING_LESSON_TYPE = "writing_prompt"
PRONUNCIATION_LESSON_TYPE = "pronunciation"

PRONUNCIATION_WORDS = [
    "thought",
    "through",
    "thoroughly",
    "comfortable",
    "necessary",
]


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class AttemptPlan:
    kind: str  # 'listening' | 'writing' | 'pronunciation'
    label: str
    count: int


@dataclass
class SeedSummary:
    user_id: int
    listening_seeded: int = 0
    writing_seeded: int = 0
    pronunciation_seeded: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Repository helpers — thin layer for testability
# ---------------------------------------------------------------------------


def _find_lessons_by_type(session, lesson_type: str, limit: int = 5) -> list:
    """Return up to *limit* Lessons rows with the given type."""
    from app.curriculum.models import Lessons

    return (
        session.query(Lessons)
        .filter(Lessons.type == lesson_type)
        .order_by(Lessons.id)
        .limit(limit)
        .all()
    )


def _count_existing_listening(session, user_id: int) -> int:
    from app.curriculum.models import ListeningAttempt

    return (
        session.query(ListeningAttempt)
        .filter(ListeningAttempt.user_id == user_id)
        .count()
    )


def _count_existing_writing(session, user_id: int) -> int:
    from app.curriculum.models import UserWritingAttempt

    return (
        session.query(UserWritingAttempt)
        .filter(UserWritingAttempt.user_id == user_id)
        .count()
    )


def _count_existing_pronunciation(session, user_id: int) -> int:
    from app.curriculum.models import PronunciationAttempt

    return (
        session.query(PronunciationAttempt)
        .filter(PronunciationAttempt.user_id == user_id)
        .count()
    )


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------


def seed_listening_attempts(
    session, user_id: int, lessons: list, dry_run: bool = False
) -> int:
    """Insert one ListeningAttempt per lesson in *lessons*."""
    from app.curriculum.models import ListeningAttempt

    inserted = 0
    for idx, lesson in enumerate(lessons):
        if dry_run:
            inserted += 1
            continue
        days_ago = idx % 7
        attempt = ListeningAttempt(
            user_id=user_id,
            lesson_id=lesson.id,
            score=round(70.0 + idx * 5.0 % 30, 1),
            replay_count=idx % 3,
        )
        attempt.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        session.add(attempt)
        inserted += 1
    return inserted


def seed_writing_attempts(
    session, user_id: int, lessons: list, dry_run: bool = False
) -> int:
    """Insert one UserWritingAttempt per lesson in *lessons*."""
    from app.curriculum.models import UserWritingAttempt

    inserted = 0
    for idx, lesson in enumerate(lessons):
        if dry_run:
            inserted += 1
            continue
        days_ago = idx % 7
        text = f"Staging writing attempt {idx + 1}. " * 5
        attempt = UserWritingAttempt(
            user_id=user_id,
            lesson_id=lesson.id,
            response_text=text,
            word_count=len(text.split()),
            checklist_completed=True,
        )
        attempt.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        session.add(attempt)
        inserted += 1
    return inserted


def seed_pronunciation_attempts(
    session, user_id: int, words: list[str], dry_run: bool = False
) -> int:
    """Insert PronunciationAttempt rows for each word in *words*."""
    from app.curriculum.models import PronunciationAttempt

    inserted = 0
    for idx, word in enumerate(words):
        if dry_run:
            inserted += 1
            continue
        matched = idx % 3 != 0
        attempt = PronunciationAttempt(
            user_id=user_id,
            word=word,
            recognized_text=word if matched else f"wrong_{word}",
            matched=matched,
        )
        attempt.created_at = datetime.now(timezone.utc) - timedelta(days=idx % 7)
        session.add(attempt)
        inserted += 1
    return inserted


def run_seed(session, user_id: int, dry_run: bool = False) -> SeedSummary:
    summary = SeedSummary(user_id=user_id, dry_run=dry_run)

    dictation_lessons = _find_lessons_by_type(session, DICTATION_LESSON_TYPE, limit=5)
    writing_lessons = _find_lessons_by_type(session, WRITING_LESSON_TYPE, limit=5)
    pronunciation_lessons = _find_lessons_by_type(
        session, PRONUNCIATION_LESSON_TYPE, limit=5
    )

    if not dictation_lessons:
        summary.errors.append(
            "No dictation lessons found in DB — run dictation import first."
        )
    if not writing_lessons:
        summary.errors.append(
            "No writing_prompt lessons found in DB — run writing_prompt import first."
        )
    if not pronunciation_lessons:
        summary.errors.append(
            "No pronunciation lessons found in DB — run pronunciation import first."
        )

    summary.listening_seeded = seed_listening_attempts(
        session, user_id, dictation_lessons, dry_run=dry_run
    )
    summary.writing_seeded = seed_writing_attempts(
        session, user_id, writing_lessons, dry_run=dry_run
    )
    summary.pronunciation_seeded = seed_pronunciation_attempts(
        session, user_id, PRONUNCIATION_WORDS, dry_run=dry_run
    )

    if not dry_run:
        session.flush()

    return summary


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(summary: SeedSummary) -> str:
    lines = [
        "# Staging Immersion Attempts Seed Report",
        "",
        f"User ID: {summary.user_id}",
        f"Dry run: {summary.dry_run}",
        "",
        "## Results",
        f"- ListeningAttempt rows seeded: {summary.listening_seeded}",
        f"- UserWritingAttempt rows seeded: {summary.writing_seeded}",
        f"- PronunciationAttempt rows seeded: {summary.pronunciation_seeded}",
        "",
    ]
    if summary.errors:
        lines.append("## Errors / Warnings")
        for err in summary.errors:
            lines.append(f"- {err}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed staging immersion attempt rows for dashboard widget verification."
    )
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show plan without writing to DB"
    )
    parser.add_argument("--report", default=None, help="Write markdown report to PATH")
    parser.add_argument(
        "--no-db", action="store_true", help="Skip DB entirely (for CI)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.no_db:
        print("--no-db: skipping DB operations.")
        return 0

    if args.user_id is None:
        print("Error: --user-id is required.", file=sys.stderr)
        return 1

    sys.path.insert(0, str(PROJECT_ROOT))

    from app import create_app
    from app.utils.db import db

    flask_app = create_app()
    with flask_app.app_context():
        summary = run_seed(db.session, args.user_id, dry_run=args.dry_run)
        if not args.dry_run and not summary.errors:
            db.session.commit()
        elif not args.dry_run and summary.errors:
            # Partial errors — still commit what was seeded
            db.session.commit()

        report = build_report(summary)
        print(report)

        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
            print(f"Report written to {args.report}")

    return 0 if not summary.errors else 2


if __name__ == "__main__":
    sys.exit(main())
