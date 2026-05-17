"""Export vocabulary priority tiers for staged enrichment.

Ranks every word in `collection_words` by three signals:
  1. Curriculum usage — how many lessons reference the word via its collection
  2. User card usage — how many distinct users have the word in their SRS deck
  3. CEFR level — A1 words before A2 before B1 … before unknown

Tier assignment (all signals contribute; tier = max-priority tier for which
any signal qualifies):
  Tier 1: level in {A1, A2}  OR  curriculum_lessons >= 2  OR  user_count >= 3
  Tier 2: level in {B1, B2}  OR  curriculum_lessons == 1  OR  user_count in {1, 2}
  Tier 3: everything else (C1, C2, no level, no usage)

Output columns:
  word_id, english_word, level, curriculum_lessons, user_count, priority_tier,
  has_ipa, has_frequency_band, has_synonyms, has_antonyms, has_etymology

Usage:
    python scripts/export_vocabulary_priority.py [--output PATH] [--no-db]
                                                  [--tier 1|2|3] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "content" / "vocabulary" / "priority_words.csv"

LEVEL_ORDER: dict[str | None, int] = {
    "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6,
}

TIER_1_LEVELS = {"A1", "A2"}
TIER_2_LEVELS = {"B1", "B2"}

CSV_FIELDS = [
    "word_id",
    "english_word",
    "level",
    "curriculum_lessons",
    "user_count",
    "priority_tier",
    "has_ipa",
    "has_frequency_band",
    "has_synonyms",
    "has_antonyms",
    "has_etymology",
]

HEADER_COMMENT_PREFIX = "# "


@dataclass
class WordPriority:
    word_id: int
    english_word: str
    level: str | None
    curriculum_lessons: int
    user_count: int
    priority_tier: int
    has_ipa: bool
    has_frequency_band: bool
    has_synonyms: bool
    has_antonyms: bool
    has_etymology: bool


def assign_tier(level: str | None, curriculum_lessons: int, user_count: int) -> int:
    """Return priority tier 1 (highest), 2, or 3 (lowest)."""
    if level in TIER_1_LEVELS or curriculum_lessons >= 2 or user_count >= 3:
        return 1
    if level in TIER_2_LEVELS or curriculum_lessons == 1 or user_count in (1, 2):
        return 2
    return 3


def sort_key(w: WordPriority) -> tuple[int, int, int]:
    """Lower = more important. Sorts by tier, CEFR order, then word_id."""
    return (w.priority_tier, LEVEL_ORDER.get(w.level, 99), w.word_id)


def collect_priorities(session) -> list[WordPriority]:
    """Query DB and return a ranked list of WordPriority records."""
    from sqlalchemy import func

    from app.words.models import Collection, CollectionWordLink, CollectionWords
    from app.curriculum.models import Lessons
    from app.study.models import UserWord

    # Curriculum usage: count distinct lessons per word via collection link
    curriculum_counts_rows = (
        session.query(
            CollectionWordLink.word_id,
            func.count(func.distinct(Lessons.id)).label("lesson_count"),
        )
        .join(Collection, Collection.id == CollectionWordLink.collection_id)
        .join(Lessons, Lessons.collection_id == Collection.id)
        .group_by(CollectionWordLink.word_id)
        .all()
    )
    curriculum_by_word: dict[int, int] = {r.word_id: r.lesson_count for r in curriculum_counts_rows}

    # User card usage: count distinct users per word
    user_counts_rows = (
        session.query(
            UserWord.word_id,
            func.count(func.distinct(UserWord.user_id)).label("user_count"),
        )
        .group_by(UserWord.word_id)
        .all()
    )
    users_by_word: dict[int, int] = {r.word_id: r.user_count for r in user_counts_rows}

    # Fetch all words
    words = session.query(
        CollectionWords.id,
        CollectionWords.english_word,
        CollectionWords.level,
        CollectionWords.ipa_transcription,
        CollectionWords.frequency_band,
        CollectionWords.synonyms,
        CollectionWords.antonyms,
        CollectionWords.etymology,
    ).all()

    result: list[WordPriority] = []
    for w in words:
        curriculum_lessons = curriculum_by_word.get(w.id, 0)
        user_count = users_by_word.get(w.id, 0)
        level = (w.level or "").strip() or None
        tier = assign_tier(level, curriculum_lessons, user_count)
        result.append(
            WordPriority(
                word_id=w.id,
                english_word=w.english_word or "",
                level=level or "",
                curriculum_lessons=curriculum_lessons,
                user_count=user_count,
                priority_tier=tier,
                has_ipa=bool(w.ipa_transcription),
                has_frequency_band=w.frequency_band is not None,
                has_synonyms=bool(w.synonyms),
                has_antonyms=bool(w.antonyms),
                has_etymology=bool(w.etymology),
            )
        )

    result.sort(key=sort_key)
    return result


def export_csv(
    priorities: list[WordPriority],
    output_path: Path,
    tier_filter: int | None,
    dry_run: bool,
    generator: str,
) -> int:
    """Write CSV file. Returns number of rows written (or would-write in dry-run)."""
    rows = priorities if tier_filter is None else [p for p in priorities if p.priority_tier == tier_filter]

    if dry_run:
        print(f"[dry-run] would write {len(rows)} rows to {output_path}")
        return len(rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        # Header comment block (not a CSV header row)
        fh.write(f"# generated_by: {generator}\n")
        fh.write(f"# generated_at: {timestamp}\n")
        fh.write(f"# tier_filter: {tier_filter if tier_filter is not None else 'all'}\n")
        fh.write(f"# total_rows: {len(rows)}\n")
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for p in rows:
            writer.writerow(
                {
                    "word_id": p.word_id,
                    "english_word": p.english_word,
                    "level": p.level,
                    "curriculum_lessons": p.curriculum_lessons,
                    "user_count": p.user_count,
                    "priority_tier": p.priority_tier,
                    "has_ipa": int(p.has_ipa),
                    "has_frequency_band": int(p.has_frequency_band),
                    "has_synonyms": int(p.has_synonyms),
                    "has_antonyms": int(p.has_antonyms),
                    "has_etymology": int(p.has_etymology),
                }
            )
    print(f"wrote {len(rows)} rows → {output_path}")
    return len(rows)


def print_summary(priorities: list[WordPriority]) -> None:
    from collections import Counter

    tier_counts: Counter = Counter(p.priority_tier for p in priorities)
    level_counts: Counter = Counter(p.level or "(none)" for p in priorities)
    has_ipa = sum(1 for p in priorities if p.has_ipa)
    has_band = sum(1 for p in priorities if p.has_frequency_band)
    has_syn = sum(1 for p in priorities if p.has_synonyms)
    has_ant = sum(1 for p in priorities if p.has_antonyms)
    has_ety = sum(1 for p in priorities if p.has_etymology)
    total = len(priorities)

    print(f"\nTotal words: {total}")
    print("Priority tiers:")
    for tier in sorted(tier_counts):
        print(f"  Tier {tier}: {tier_counts[tier]}")
    print("CEFR levels (top 8):")
    for level, cnt in level_counts.most_common(8):
        print(f"  {level}: {cnt}")
    print("Enrichment coverage:")
    for label, count in [
        ("IPA", has_ipa),
        ("frequency_band", has_band),
        ("synonyms", has_syn),
        ("antonyms", has_ant),
        ("etymology", has_ety),
    ]:
        pct = f"{count / total * 100:.1f}%" if total else "–"
        print(f"  {label}: {count} / {total} ({pct})")


# ---------------------------------------------------------------------------
# Testable pure functions (no DB)
# ---------------------------------------------------------------------------

def assign_tier_pure(level: str | None, curriculum_lessons: int, user_count: int) -> int:
    return assign_tier(level, curriculum_lessons, user_count)


def sort_priorities(priorities: list[WordPriority]) -> list[WordPriority]:
    return sorted(priorities, key=sort_key)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _try_get_db():
    try:
        from app import create_app
        from extensions import db as _db
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot import Flask app: {exc}", file=sys.stderr)
        return None, None
    try:
        app = create_app(os.environ.get("FLASK_ENV", "development"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: create_app() failed: {exc}", file=sys.stderr)
        return None, None
    return app, _db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export vocabulary priority tiers to content/vocabulary/priority_words.csv."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output CSV path (default: content/vocabulary/priority_words.csv)",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        default=None,
        help="Only export words of this priority tier (default: all tiers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print row count without writing the file.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB access (for CI without a live database).",
    )
    args = parser.parse_args(argv)

    if args.no_db:
        print("WARN: --no-db passed; no output generated.", file=sys.stderr)
        return 0

    app, db = _try_get_db()
    if app is None or db is None:
        print("ERROR: could not initialise Flask app; aborting.", file=sys.stderr)
        return 1

    with app.app_context():
        priorities = collect_priorities(db.session)

    print_summary(priorities)
    export_csv(
        priorities,
        output_path=args.output,
        tier_filter=args.tier,
        dry_run=args.dry_run,
        generator="scripts/export_vocabulary_priority.py",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
