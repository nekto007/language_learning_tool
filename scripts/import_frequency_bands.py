"""Idempotent frequency-band importer for collection_words.

Reads a CSV from content/vocabulary/frequency_bands.csv (or a supplied path)
and patches the `frequency_band` column in collection_words.  Only values
1, 2, and 3 are accepted (1=top-1000, 2=top-3000, 3=top-10000).

Match key: english_word (case-insensitive exact match).

Idempotency:
  - Words whose frequency_band is already set are skipped unless --force.
  - Running twice on the same CSV produces zero changes on the second run.

Flags:
    --dry-run           plan only, no DB writes
    --force             overwrite existing non-null frequency_band values
    --report PATH       write markdown report to PATH
    --priority-tier N   only update words whose priority_tier in
                        content/vocabulary/priority_words.csv equals N (1/2/3)
    --cefr-fallback     after processing the CSV, assign bands to remaining
                        null-band words using their CEFR level:
                        A1/A2 -> 1, B1/B2 -> 2, C1/C2/unknown -> 3
    FILE                one or more CSV files; defaults to
                        content/vocabulary/frequency_bands.csv

Usage:
    python scripts/import_frequency_bands.py [FILE ...] [options]

Task 36 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "content" / "vocabulary" / "frequency_bands.csv"
PRIORITY_WORDS_PATH = PROJECT_ROOT / "content" / "vocabulary" / "priority_words.csv"

ALLOWED_BANDS = {1, 2, 3}
CEFR_TO_BAND: dict[str, int] = {
    "A1": 1, "A2": 1,
    "B1": 2, "B2": 2,
    "C1": 3, "C2": 3,
}


# ---------------------------------------------------------------------------
# Entry data classes
# ---------------------------------------------------------------------------


@dataclass
class BandEntry:
    english_word: str
    frequency_band: int
    raw_row: dict = field(default_factory=dict)


@dataclass
class BandChange:
    action: str  # 'set' | 'noop' | 'skip_force' | 'skip_no_match' | 'skip_tier'
    english_word: str
    frequency_band: int
    word_id: Optional[int] = None
    old_band: Optional[int] = None
    reason: str = ""


@dataclass
class BandPlan:
    changes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        c: dict = {}
        for ch in self.changes:
            c[ch.action] = c.get(ch.action, 0) + 1
        return c


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_row(row: dict) -> tuple:
    """Return (BandEntry, None) or (None, error_str)."""
    word = str(row.get("english_word") or "").strip()
    if not word:
        return None, "empty english_word"
    raw_band = row.get("frequency_band")
    try:
        band = int(str(raw_band).strip())
    except (ValueError, TypeError):
        return None, f"invalid frequency_band: {raw_band!r}"
    if band not in ALLOWED_BANDS:
        return None, f"frequency_band must be 1, 2 or 3; got {band!r}"
    return BandEntry(english_word=word, frequency_band=band, raw_row=dict(row)), None


def load_csv(paths: list) -> tuple:
    """Return (entries, errors) from one or more CSV files."""
    entries: list = []
    errors: list = []
    seen: set = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                # Skip comment lines
                lines = [ln for ln in fh if not ln.startswith("#")]
            reader = csv.DictReader(lines)
            if reader.fieldnames is None or "english_word" not in reader.fieldnames:
                errors.append(f"{path}: missing 'english_word' column")
                continue
            if "frequency_band" not in reader.fieldnames:
                errors.append(f"{path}: missing 'frequency_band' column")
                continue
            for idx, row in enumerate(reader):
                entry, err = parse_row(row)
                if err:
                    errors.append(f"{path}[{idx}]: {err}")
                    continue
                key = entry.english_word.lower()
                if key in seen:
                    # last writer wins; just replace
                    entries = [e for e in entries if e.english_word.lower() != key]
                seen.add(key)
                entries.append(entry)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return entries, errors


# ---------------------------------------------------------------------------
# Priority-tier filtering
# ---------------------------------------------------------------------------


def load_priority_tiers(path: Path) -> dict:
    """Return mapping {english_word_lower: priority_tier} from priority_words.csv."""
    result: dict = {}
    if not path.exists():
        return result
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            lines = [ln for ln in fh if not ln.startswith("#")]
        reader = csv.DictReader(lines)
        for row in reader:
            word = str(row.get("english_word") or "").strip().lower()
            try:
                tier = int(row.get("priority_tier", 0))
            except ValueError:
                continue
            if word:
                result[word] = tier
    except OSError:
        pass
    return result


# ---------------------------------------------------------------------------
# Repository abstraction
# ---------------------------------------------------------------------------


class Repository:
    def find_word(self, english_word: str) -> Optional[object]:
        raise NotImplementedError

    def get_all_null_band_words(self) -> list:
        """Return list of (word_id, english_word, cefr_level) for words with frequency_band IS NULL."""
        raise NotImplementedError

    def set_frequency_band(self, word_id: int, band: int) -> None:
        raise NotImplementedError


class DBRepository(Repository):
    def __init__(self, session):
        self._session = session

    def find_word(self, english_word: str) -> Optional[object]:
        from app.words.models import CollectionWords
        return (
            self._session.query(CollectionWords)
            .filter(CollectionWords.english_word.ilike(english_word))
            .first()
        )

    def get_all_null_band_words(self) -> list:
        from app.words.models import CollectionWords
        rows = (
            self._session.query(
                CollectionWords.id,
                CollectionWords.english_word,
                CollectionWords.level,
            )
            .filter(CollectionWords.frequency_band.is_(None))
            .all()
        )
        return [(r.id, r.english_word, r.level) for r in rows]

    def set_frequency_band(self, word_id: int, band: int) -> None:
        from app.words.models import CollectionWords
        row = self._session.query(CollectionWords).get(word_id)
        if row is not None:
            row.frequency_band = band
            self._session.flush()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_bands(
    entries: list,
    repo: Repository,
    *,
    force: bool = False,
    priority_tier: Optional[int] = None,
    priority_map: Optional[dict] = None,
) -> BandPlan:
    plan = BandPlan()
    for entry in entries:
        key = entry.english_word.lower()

        # Priority tier filter
        if priority_tier is not None and priority_map is not None:
            tier = priority_map.get(key)
            if tier != priority_tier:
                plan.changes.append(
                    BandChange(
                        action="skip_tier",
                        english_word=entry.english_word,
                        frequency_band=entry.frequency_band,
                        reason=f"tier={tier} != requested {priority_tier}",
                    )
                )
                continue

        word = repo.find_word(entry.english_word)
        if word is None:
            plan.changes.append(
                BandChange(
                    action="skip_no_match",
                    english_word=entry.english_word,
                    frequency_band=entry.frequency_band,
                    reason="not found in collection_words",
                )
            )
            continue

        old_band = getattr(word, "frequency_band", None)
        if old_band is not None and not force:
            plan.changes.append(
                BandChange(
                    action="skip_force",
                    english_word=entry.english_word,
                    frequency_band=entry.frequency_band,
                    word_id=word.id,
                    old_band=old_band,
                    reason="existing value preserved (use --force to overwrite)",
                )
            )
            continue

        action = "set" if old_band != entry.frequency_band else "noop"
        plan.changes.append(
            BandChange(
                action=action,
                english_word=entry.english_word,
                frequency_band=entry.frequency_band,
                word_id=word.id,
                old_band=old_band,
            )
        )
    return plan


def plan_cefr_fallback(
    repo: Repository,
    *,
    force: bool = False,
) -> BandPlan:
    """Build a patch plan for all null-band words using CEFR level."""
    plan = BandPlan()
    null_words = repo.get_all_null_band_words()
    for word_id, english_word, level in null_words:
        band = CEFR_TO_BAND.get(str(level or "").upper().strip(), 3)
        plan.changes.append(
            BandChange(
                action="set",
                english_word=english_word,
                frequency_band=band,
                word_id=word_id,
                old_band=None,
                reason=f"cefr_fallback level={level!r}",
            )
        )
    return plan


def apply_plan(plan: BandPlan, repo: Repository) -> int:
    """Apply all 'set' changes; return count of rows written."""
    count = 0
    for ch in plan.changes:
        if ch.action == "set" and ch.word_id is not None:
            repo.set_frequency_band(ch.word_id, ch.frequency_band)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(
    csv_plan: BandPlan,
    fallback_plan: Optional[BandPlan],
    *,
    dry_run: bool,
    force: bool,
    elapsed: float,
) -> str:
    lines: list = []
    lines.append("# Frequency Band Import Report")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Generated: {ts}  ")
    lines.append(f"Mode: {'dry-run' if dry_run else 'live'}  ")
    lines.append(f"Force overwrite: {force}  ")
    lines.append(f"Elapsed: {elapsed:.2f}s")
    lines.append("")

    def _section(title: str, plan: BandPlan) -> None:
        lines.append(f"## {title}")
        lines.append("")
        c = plan.counts
        lines.append("| Action | Count |")
        lines.append("|--------|-------|")
        for action in ("set", "noop", "skip_force", "skip_no_match", "skip_tier"):
            n = c.get(action, 0)
            if n:
                lines.append(f"| {action} | {n} |")
        if plan.errors:
            lines.append(f"| errors | {len(plan.errors)} |")
        lines.append("")
        if plan.errors:
            lines.append("### Errors")
            lines.append("")
            for e in plan.errors[:20]:
                lines.append(f"- {e}")
            if len(plan.errors) > 20:
                lines.append(f"- … and {len(plan.errors) - 20} more")
            lines.append("")
        skipped_no_match = [ch for ch in plan.changes if ch.action == "skip_no_match"]
        if skipped_no_match:
            lines.append("### Words Not Found in DB")
            lines.append("")
            for ch in skipped_no_match[:20]:
                lines.append(f"- `{ch.english_word}`")
            if len(skipped_no_match) > 20:
                lines.append(f"- … and {len(skipped_no_match) - 20} more")
            lines.append("")

    _section("CSV Import", csv_plan)
    if fallback_plan is not None:
        _section("CEFR Fallback", fallback_plan)

    total_set = csv_plan.counts.get("set", 0)
    if fallback_plan is not None:
        total_set += fallback_plan.counts.get("set", 0)
    lines.append(f"**Total rows written: {total_set}** (0 if dry-run)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import frequency bands into collection_words",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files",
        nargs="*",
        help="CSV files to import (default: content/vocabulary/frequency_bands.csv)",
    )
    p.add_argument("--dry-run", action="store_true", help="plan only, no DB writes")
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing non-null frequency_band values",
    )
    p.add_argument(
        "--report",
        metavar="PATH",
        help="write markdown report to PATH",
    )
    p.add_argument(
        "--priority-tier",
        type=int,
        choices=[1, 2, 3],
        metavar="N",
        dest="priority_tier",
        help="only update words whose priority_tier equals N (requires priority_words.csv)",
    )
    p.add_argument(
        "--cefr-fallback",
        action="store_true",
        dest="cefr_fallback",
        help="after CSV import, fill remaining null-band words from their CEFR level",
    )
    p.add_argument(
        "--no-db",
        action="store_true",
        dest="no_db",
        help="exit immediately without DB connection (for CI import checks)",
    )
    return p


def main(argv: Optional[list] = None) -> int:
    import time

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.no_db:
        print("--no-db: skipping DB connection")
        return 0

    paths = [Path(p) for p in args.files] if args.files else [DEFAULT_CSV_PATH]

    entries, load_errors = load_csv(paths)
    if load_errors:
        for e in load_errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    priority_map: Optional[dict] = None
    if args.priority_tier is not None:
        priority_map = load_priority_tiers(PRIORITY_WORDS_PATH)
        if not priority_map:
            print(
                f"WARNING: --priority-tier set but {PRIORITY_WORDS_PATH} not found or empty; "
                "skipping tier filter",
                file=sys.stderr,
            )
            priority_map = None

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("FLASK_ENV", "development")

    from app import create_app
    from app.extensions import db

    app = create_app()
    t0 = time.monotonic()

    with app.app_context():
        repo = DBRepository(db.session)

        csv_plan = plan_bands(
            entries,
            repo,
            force=args.force,
            priority_tier=args.priority_tier,
            priority_map=priority_map,
        )

        fallback_plan: Optional[BandPlan] = None
        if args.cefr_fallback:
            fallback_plan = plan_cefr_fallback(repo, force=args.force)

        if not args.dry_run:
            written = apply_plan(csv_plan, repo)
            if fallback_plan is not None:
                written += apply_plan(fallback_plan, repo)
            db.session.commit()
        else:
            written = 0

        elapsed = time.monotonic() - t0
        report = format_report(
            csv_plan,
            fallback_plan,
            dry_run=args.dry_run,
            force=args.force,
            elapsed=elapsed,
        )
        print(report)

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"Report written to {report_path}")

        c = csv_plan.counts
        total_set = c.get("set", 0)
        if fallback_plan is not None:
            total_set += fallback_plan.counts.get("set", 0)
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}frequency_band: {total_set} set, "
            f"{c.get('noop', 0)} noop, "
            f"{c.get('skip_force', 0)} preserved, "
            f"{c.get('skip_no_match', 0)} not found"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
