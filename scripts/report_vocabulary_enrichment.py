"""Report vocabulary enrichment coverage.

Produces a per-field, per-CEFR-level, and per-priority-tier breakdown of
how many words in `collection_words` have each enrichment field populated:

  - ipa_transcription
  - frequency_band
  - synonyms / antonyms
  - etymology
  - word_collocations (row count in the child table)
  - cultural_notes (row count in the child table)

Priority tiers follow the same logic as scripts/export_vocabulary_priority.py:
  Tier 1: A1/A2 OR curriculum_lessons >= 2 OR user_count >= 3
  Tier 2: B1/B2 OR curriculum_lessons == 1 OR user_count in {1, 2}
  Tier 3: everything else

Usage:
    python scripts/report_vocabulary_enrichment.py [--output PATH]
                                                   [--format markdown|json]
                                                   [--no-db]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "vocabulary_enrichment.md"

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
TIER_1_LEVELS = {"A1", "A2"}
TIER_2_LEVELS = {"B1", "B2"}

ENRICHMENT_FIELDS = [
    "ipa_transcription",
    "frequency_band",
    "synonyms",
    "antonyms",
    "etymology",
    "collocations",
    "cultural_notes",
]


# ---------------------------------------------------------------------------
# Pure data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldCoverage:
    """Coverage stats for one enrichment field."""
    total: int
    filled: int

    @property
    def missing(self) -> int:
        return self.total - self.filled

    @property
    def pct(self) -> float:
        return (self.filled / self.total * 100) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "filled": self.filled,
            "missing": self.missing,
            "pct": round(self.pct, 1),
        }


@dataclass
class LevelRow:
    """Coverage stats for one CEFR level across all enrichment fields."""
    level: str
    total_words: int
    coverage: dict[str, FieldCoverage] = field(default_factory=dict)


@dataclass
class TierRow:
    """Coverage stats for one priority tier across all enrichment fields."""
    tier: int
    total_words: int
    coverage: dict[str, FieldCoverage] = field(default_factory=dict)


@dataclass
class EnrichmentReport:
    """Full enrichment coverage report."""
    generated_at: str
    total_words: int
    overall: dict[str, FieldCoverage]
    by_level: list[LevelRow]
    by_tier: list[TierRow]
    db_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "total_words": self.total_words,
            "db_error": self.db_error,
            "overall": {k: v.to_dict() for k, v in self.overall.items()},
            "by_level": [
                {
                    "level": row.level,
                    "total_words": row.total_words,
                    "coverage": {k: v.to_dict() for k, v in row.coverage.items()},
                }
                for row in self.by_level
            ],
            "by_tier": [
                {
                    "tier": row.tier,
                    "total_words": row.total_words,
                    "coverage": {k: v.to_dict() for k, v in row.coverage.items()},
                }
                for row in self.by_tier
            ],
        }


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def assign_tier(level: str | None, curriculum_lessons: int, user_count: int) -> int:
    """Return priority tier 1 (highest), 2, or 3 (lowest)."""
    if level in TIER_1_LEVELS or curriculum_lessons >= 2 or user_count >= 3:
        return 1
    if level in TIER_2_LEVELS or curriculum_lessons == 1 or user_count in (1, 2):
        return 2
    return 3


def compute_overall_coverage(
    words: list[dict[str, Any]],
) -> dict[str, FieldCoverage]:
    """Compute per-field coverage totals across all words."""
    total = len(words)
    result: dict[str, FieldCoverage] = {}
    for f in ENRICHMENT_FIELDS:
        filled = sum(1 for w in words if w.get(f))
        result[f] = FieldCoverage(total=total, filled=filled)
    return result


def compute_coverage_by_level(words: list[dict[str, Any]]) -> list[LevelRow]:
    """Compute per-field coverage grouped by CEFR level."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for w in words:
        lvl = (w.get("level") or "").strip() or "(none)"
        buckets.setdefault(lvl, []).append(w)

    rows: list[LevelRow] = []
    for lvl in CEFR_LEVELS + ["(none)"]:
        grp = buckets.get(lvl, [])
        if not grp:
            continue
        row = LevelRow(level=lvl, total_words=len(grp))
        for f in ENRICHMENT_FIELDS:
            filled = sum(1 for w in grp if w.get(f))
            row.coverage[f] = FieldCoverage(total=len(grp), filled=filled)
        rows.append(row)
    return rows


def compute_coverage_by_tier(words: list[dict[str, Any]]) -> list[TierRow]:
    """Compute per-field coverage grouped by priority tier."""
    buckets: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    for w in words:
        tier = assign_tier(
            (w.get("level") or "").strip() or None,
            w.get("curriculum_lessons", 0),
            w.get("user_count", 0),
        )
        buckets[tier].append(w)

    rows: list[TierRow] = []
    for tier in (1, 2, 3):
        grp = buckets[tier]
        row = TierRow(tier=tier, total_words=len(grp))
        for f in ENRICHMENT_FIELDS:
            filled = sum(1 for w in grp if w.get(f))
            row.coverage[f] = FieldCoverage(total=len(grp), filled=filled)
        rows.append(row)
    return rows


def build_report_from_words(words: list[dict[str, Any]]) -> EnrichmentReport:
    """Build a full EnrichmentReport from a list of word dicts."""
    return EnrichmentReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        total_words=len(words),
        overall=compute_overall_coverage(words),
        by_level=compute_coverage_by_level(words),
        by_tier=compute_coverage_by_tier(words),
    )


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def _pct_bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _coverage_table(coverage: dict[str, FieldCoverage], total: int) -> str:
    header = "| Field | Filled | Missing | Coverage |\n|---|---:|---:|---:|\n"
    rows = []
    for f in ENRICHMENT_FIELDS:
        fc = coverage.get(f, FieldCoverage(total=total, filled=0))
        rows.append(
            f"| {f} | {fc.filled:,} | {fc.missing:,} | {fc.pct:.1f}% {_pct_bar(fc.pct)} |"
        )
    return header + "\n".join(rows) + "\n"


def format_markdown(report: EnrichmentReport) -> str:
    lines: list[str] = []
    lines.append("# Vocabulary Enrichment Coverage Report\n")
    lines.append(f"Generated: {report.generated_at}  ")
    lines.append(f"Total words: {report.total_words:,}\n")

    if report.db_error:
        lines.append(f"> WARNING: DB query failed — {report.db_error}\n")

    # Overall
    lines.append("## Overall Coverage\n")
    lines.append(_coverage_table(report.overall, report.total_words))

    # By CEFR level
    lines.append("## Coverage by CEFR Level\n")
    for row in report.by_level:
        lines.append(f"### {row.level} ({row.total_words:,} words)\n")
        lines.append(_coverage_table(row.coverage, row.total_words))

    # By priority tier
    tier_label = {1: "Tier 1 — highest priority", 2: "Tier 2 — medium priority", 3: "Tier 3 — low priority"}
    lines.append("## Coverage by Priority Tier\n")
    for row in report.by_tier:
        label = tier_label.get(row.tier, f"Tier {row.tier}")
        lines.append(f"### {label} ({row.total_words:,} words)\n")
        lines.append(_coverage_table(row.coverage, row.total_words))

    return "\n".join(lines)


def format_json(report: EnrichmentReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# DB collection
# ---------------------------------------------------------------------------

def collect_words(session) -> list[dict[str, Any]]:
    """Return one dict per word with all enrichment fields + usage counts."""
    from sqlalchemy import func, text

    from app.words.models import CollectionWords, CollectionWordLink, Collection
    from app.curriculum.models import Lessons, WordCollocation, CulturalNote
    from app.study.models import UserWord

    # Curriculum usage per word
    curriculum_rows = (
        session.query(
            CollectionWordLink.word_id,
            func.count(func.distinct(Lessons.id)).label("cnt"),
        )
        .join(Collection, Collection.id == CollectionWordLink.collection_id)
        .join(Lessons, Lessons.collection_id == Collection.id)
        .group_by(CollectionWordLink.word_id)
        .all()
    )
    curriculum_by_word: dict[int, int] = {r.word_id: r.cnt for r in curriculum_rows}

    # User usage per word
    user_rows = (
        session.query(
            UserWord.word_id,
            func.count(func.distinct(UserWord.user_id)).label("cnt"),
        )
        .group_by(UserWord.word_id)
        .all()
    )
    users_by_word: dict[int, int] = {r.word_id: r.cnt for r in user_rows}

    # Collocation coverage: set of word_ids with at least one row
    collocation_word_ids: set[int] = {
        r[0]
        for r in session.query(WordCollocation.word_id).distinct().all()
    }

    # Cultural note coverage
    cultural_word_ids: set[int] = {
        r[0]
        for r in session.query(CulturalNote.word_id).distinct().all()
    }

    words = session.query(
        CollectionWords.id,
        CollectionWords.level,
        CollectionWords.ipa_transcription,
        CollectionWords.frequency_band,
        CollectionWords.synonyms,
        CollectionWords.antonyms,
        CollectionWords.etymology,
    ).all()

    result: list[dict[str, Any]] = []
    for w in words:
        lvl = (w.level or "").strip() or None
        result.append(
            {
                "word_id": w.id,
                "level": lvl,
                "curriculum_lessons": curriculum_by_word.get(w.id, 0),
                "user_count": users_by_word.get(w.id, 0),
                "ipa_transcription": bool(w.ipa_transcription),
                "frequency_band": w.frequency_band is not None,
                "synonyms": bool(w.synonyms),
                "antonyms": bool(w.antonyms),
                "etymology": bool(w.etymology),
                "collocations": w.id in collocation_word_ids,
                "cultural_notes": w.id in cultural_word_ids,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Flask app bootstrap
# ---------------------------------------------------------------------------

def _try_get_db():
    try:
        from app import create_app
        from extensions import db as _db
    except Exception as exc:
        print(f"WARN: cannot import Flask app: {exc}", file=sys.stderr)
        return None, None
    try:
        app = create_app(os.environ.get("FLASK_ENV", "development"))
    except Exception as exc:
        print(f"WARN: create_app() failed: {exc}", file=sys.stderr)
        return None, None
    return app, _db


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report vocabulary enrichment coverage by field, CEFR level, and priority tier."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output path for the report (default: reports/vocabulary_enrichment.md).",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        dest="fmt",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB access (for CI without a live database).",
    )
    args = parser.parse_args(argv)

    if args.no_db:
        print("WARN: --no-db passed; no report generated.", file=sys.stderr)
        return 0

    app, db = _try_get_db()
    if app is None or db is None:
        print("ERROR: could not initialise Flask app; aborting.", file=sys.stderr)
        return 1

    with app.app_context():
        words = collect_words(db.session)

    report = build_report_from_words(words)

    if args.fmt == "json":
        text = format_json(report)
    else:
        text = format_markdown(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Report written → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
