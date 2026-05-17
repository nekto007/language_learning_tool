"""Backfill source tags for existing user_card_directions rows.

For each UserCardDirection row with source=NULL:
  - lesson_vocab  : word is in a Collection linked to a curriculum Lesson
  - book_reading  : word is in the word_book_link table (book reading course)
  - manual        : ambiguous — cannot be attributed to a known import path

Priority: lesson_vocab > book_reading > manual

Flags:
    --dry-run           show what would change, no DB writes
    --report PATH       write markdown report to PATH
    --no-db             skip DB, exit 0 (for CI)

Usage:
    python scripts/backfill_card_sources.py [options]

Task 42 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_SOURCES = ("lesson_vocab", "book_reading", "manual")


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class CardRecord:
    card_id: int
    user_word_id: int
    word_id: int
    direction: str
    current_source: Optional[str]


@dataclass
class SourceChange:
    card_id: int
    word_id: int
    direction: str
    inferred_source: str
    action: str  # 'update'


@dataclass
class BackfillPlan:
    changes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        result: dict = {}
        for c in self.changes:
            result[c.action] = result.get(c.action, 0) + 1
        return result

    @property
    def source_counts(self) -> dict:
        result: dict = {}
        for c in self.changes:
            if c.action == "update":
                result[c.inferred_source] = result.get(c.inferred_source, 0) + 1
        return result


# ---------------------------------------------------------------------------
# Repository interface
# ---------------------------------------------------------------------------


class Repository:
    def get_cards_without_source(self) -> list:
        raise NotImplementedError

    def get_lesson_vocab_word_ids(self) -> set:
        """word_ids in collections linked to curriculum lessons."""
        raise NotImplementedError

    def get_book_reading_word_ids(self) -> set:
        """word_ids present in word_book_link."""
        raise NotImplementedError

    def update_source(self, card_id: int, source: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Pure backfill logic
# ---------------------------------------------------------------------------


def infer_source(word_id: int, lesson_vocab_ids: set, book_reading_ids: set) -> str:
    if word_id in lesson_vocab_ids:
        return "lesson_vocab"
    if word_id in book_reading_ids:
        return "book_reading"
    return "manual"


def plan_backfill(repo: Repository) -> BackfillPlan:
    plan = BackfillPlan()
    cards = repo.get_cards_without_source()
    lesson_vocab_ids = repo.get_lesson_vocab_word_ids()
    book_reading_ids = repo.get_book_reading_word_ids()

    for card in cards:
        source = infer_source(card.word_id, lesson_vocab_ids, book_reading_ids)
        plan.changes.append(SourceChange(
            card_id=card.card_id,
            word_id=card.word_id,
            direction=card.direction,
            inferred_source=source,
            action="update",
        ))

    return plan


def apply_plan(plan: BackfillPlan, repo: Repository) -> int:
    count = 0
    for change in plan.changes:
        if change.action == "update":
            repo.update_source(change.card_id, change.inferred_source)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------


def format_report(plan: BackfillPlan, dry_run: bool, elapsed: float) -> str:
    mode = "dry-run" if dry_run else "live"
    lines = [
        "# SRS Card Source Backfill Report",
        "",
        f"Mode: {mode}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Elapsed: {elapsed:.2f}s",
        "",
        "## Summary",
    ]

    counts = plan.counts
    source_counts = plan.source_counts
    total = counts.get("update", 0)

    lines.append(f"- Total cards without source: {total}")
    lines.append(f"- Cards to update: {total}")
    lines.append("")

    lines.append("## Source Attribution")
    for src in VALID_SOURCES:
        n = source_counts.get(src, 0)
        lines.append(f"- {src}: {n}")
    lines.append("")

    unresolved = source_counts.get("manual", 0)
    lines.append(f"## Unresolved (manual)")
    lines.append(f"- Cards with no curriculum or book link: {unresolved}")
    lines.append("")

    if plan.errors:
        lines.append("## Errors")
        for e in plan.errors:
            lines.append(f"- {e}")
        lines.append("")

    if dry_run:
        lines.append("_No changes written (dry-run mode)._")
    else:
        lines.append(f"Total rows written: {counts.get('update', 0)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB repository
# ---------------------------------------------------------------------------


class DbRepository(Repository):
    def __init__(self, db):
        self._db = db

    def get_cards_without_source(self) -> list:
        from sqlalchemy import text
        rows = self._db.session.execute(
            text("""
                SELECT ucd.id, ucd.user_word_id, uw.word_id, ucd.direction
                FROM user_card_directions ucd
                JOIN user_words uw ON uw.id = ucd.user_word_id
                WHERE ucd.source IS NULL
                ORDER BY ucd.id
            """)
        ).fetchall()
        return [
            CardRecord(
                card_id=row[0],
                user_word_id=row[1],
                word_id=row[2],
                direction=row[3],
                current_source=None,
            )
            for row in rows
        ]

    def get_lesson_vocab_word_ids(self) -> set:
        from sqlalchemy import text
        rows = self._db.session.execute(
            text("""
                SELECT DISTINCT cwl.word_id
                FROM collection_words_link cwl
                JOIN lessons l ON l.collection_id = cwl.collection_id
                WHERE l.collection_id IS NOT NULL
            """)
        ).fetchall()
        return {row[0] for row in rows}

    def get_book_reading_word_ids(self) -> set:
        from sqlalchemy import text
        rows = self._db.session.execute(
            text("SELECT DISTINCT word_id FROM word_book_link")
        ).fetchall()
        return {row[0] for row in rows}

    def update_source(self, card_id: int, source: str) -> None:
        from sqlalchemy import text
        self._db.session.execute(
            text("UPDATE user_card_directions SET source = :source WHERE id = :id"),
            {"source": source, "id": card_id},
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    import time

    parser = argparse.ArgumentParser(description="Backfill SRS card source tags.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no DB writes")
    parser.add_argument("--report", metavar="PATH", help="Write markdown report to PATH")
    parser.add_argument("--no-db", action="store_true", help="Skip DB; exit 0 (for CI)")
    args = parser.parse_args(argv)

    if args.no_db:
        return 0

    sys.path.insert(0, str(PROJECT_ROOT))
    from app import create_app
    from app.utils.db import db

    app = create_app()
    t0 = time.time()

    with app.app_context():
        repo = DbRepository(db)
        plan = plan_backfill(repo)

        if not args.dry_run:
            apply_plan(plan, repo)
            db.session.commit()

        elapsed = time.time() - t0
        report = format_report(plan, dry_run=args.dry_run, elapsed=elapsed)
        print(report)

        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
            print(f"\nReport written to {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
