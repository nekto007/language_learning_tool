"""Idempotent synonyms/antonyms importer for collection_words.

Reads a CSV from content/vocabulary/synonyms_antonyms.csv (or a supplied path)
and patches the `synonyms` and `antonyms` JSON columns in collection_words.

CSV format:
    english_word,synonyms,antonyms
  - synonyms/antonyms: semicolon-separated word list, stored as JSON list.
  - Either field may be empty; empty fields are skipped for that column.

Match key: english_word (case-insensitive exact match).  An optional word_id
column is supported; when present and non-empty it takes priority over the
english_word lookup.

Validation:
  - Empty values after stripping are rejected with a parse error.
  - Non-string items in a parsed list are rejected.
  - Lists containing duplicate entries after lower-casing are deduplicated.

Idempotency:
  - Words whose synonyms (or antonyms) are already set are skipped for that
    field unless --force.
  - Running twice on the same CSV produces zero changes on the second run.

Flags:
    --dry-run           plan only, no DB writes
    --force             overwrite existing non-null synonym/antonym values
    --field synonyms|antonyms|both
                        which field(s) to update (default: both)
    --report PATH       write markdown report to PATH
    --priority-tier N   only update words whose priority_tier in
                        content/vocabulary/priority_words.csv equals N (1/2/3)
    FILE                one or more CSV files; defaults to
                        content/vocabulary/synonyms_antonyms.csv

Usage:
    python scripts/import_synonyms_antonyms.py [FILE ...] [options]

Task 38 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "content" / "vocabulary" / "synonyms_antonyms.csv"
PRIORITY_WORDS_PATH = PROJECT_ROOT / "content" / "vocabulary" / "priority_words.csv"

FIELDS = ("synonyms", "antonyms")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def parse_word_list(raw: str) -> tuple:
    """Parse a semicolon-separated word list into a deduplicated list.

    Returns (list_of_strings, None) on success, or (None, error_str) on failure.
    Empty raw string returns (None, None) — caller skips the field.
    """
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    if not raw:
        return None, None

    parts = [p.strip() for p in raw.split(";")]
    parts = [p for p in parts if p]
    if not parts:
        return None, f"empty list after parsing: {raw!r}"

    for p in parts:
        if not isinstance(p, str) or not p:
            return None, f"invalid item in list: {p!r}"

    # Deduplicate preserving order, case-insensitive key
    seen: set = set()
    deduped: List[str] = []
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return deduped, None


# ---------------------------------------------------------------------------
# Entry data classes
# ---------------------------------------------------------------------------


@dataclass
class SynAntEntry:
    english_word: str
    synonyms: Optional[List[str]]  # None means "not specified in CSV"
    antonyms: Optional[List[str]]
    word_id: Optional[int] = None
    raw_row: dict = field(default_factory=dict)


@dataclass
class FieldChange:
    action: str   # 'set' | 'noop' | 'skip_force' | 'skip_no_match' | 'skip_tier' | 'skip_empty'
    english_word: str
    field_name: str  # 'synonyms' or 'antonyms'
    new_value: Optional[List[str]] = None
    old_value: Optional[List[str]] = None
    word_id: Optional[int] = None
    reason: str = ""


@dataclass
class SynAntPlan:
    changes: List[FieldChange] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        c: dict = {}
        for ch in self.changes:
            key = f"{ch.action}:{ch.field_name}"
            c[key] = c.get(key, 0) + 1
        return c

    def action_count(self, action: str, field_name: Optional[str] = None) -> int:
        return sum(
            1 for ch in self.changes
            if ch.action == action and (field_name is None or ch.field_name == field_name)
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_row(row: dict) -> tuple:
    """Return (SynAntEntry, None) or (None, error_str)."""
    word = str(row.get("english_word") or "").strip()
    if not word:
        return None, "empty english_word"

    raw_word_id = row.get("word_id") or ""
    word_id: Optional[int] = None
    if str(raw_word_id).strip():
        try:
            word_id = int(str(raw_word_id).strip())
        except ValueError:
            return None, f"invalid word_id: {raw_word_id!r}"

    raw_synonyms = row.get("synonyms") or ""
    synonyms, syn_err = parse_word_list(raw_synonyms)
    if syn_err:
        return None, f"synonyms: {syn_err}"

    raw_antonyms = row.get("antonyms") or ""
    antonyms, ant_err = parse_word_list(raw_antonyms)
    if ant_err:
        return None, f"antonyms: {ant_err}"

    if synonyms is None and antonyms is None:
        return None, "both synonyms and antonyms are empty"

    return SynAntEntry(
        english_word=word,
        synonyms=synonyms,
        antonyms=antonyms,
        word_id=word_id,
        raw_row=dict(row),
    ), None


def load_csv(paths: list) -> tuple:
    """Return (entries, errors) from one or more CSV files."""
    entries: list = []
    errors: list = []
    seen: set = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                lines = [ln for ln in fh if not ln.startswith("#")]
            reader = csv.DictReader(lines)
            if reader.fieldnames is None or "english_word" not in reader.fieldnames:
                errors.append(f"{path}: missing 'english_word' column")
                continue
            for idx, row in enumerate(reader):
                entry, err = parse_row(row)
                if err:
                    errors.append(f"{path}[{idx}]: {err}")
                    continue
                key = entry.english_word.lower()
                if key in seen:
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
    def find_word_by_id(self, word_id: int) -> Optional[object]:
        raise NotImplementedError

    def find_word_by_name(self, english_word: str) -> Optional[object]:
        raise NotImplementedError

    def set_field(self, word_id: int, field_name: str, value: List[str]) -> None:
        raise NotImplementedError


class DBRepository(Repository):
    def __init__(self, session):
        self._session = session

    def find_word_by_id(self, word_id: int) -> Optional[object]:
        from app.words.models import CollectionWords
        return self._session.query(CollectionWords).get(word_id)

    def find_word_by_name(self, english_word: str) -> Optional[object]:
        from app.words.models import CollectionWords
        return (
            self._session.query(CollectionWords)
            .filter(CollectionWords.english_word.ilike(english_word))
            .first()
        )

    def set_field(self, word_id: int, field_name: str, value: List[str]) -> None:
        from app.words.models import CollectionWords
        row = self._session.query(CollectionWords).get(word_id)
        if row is not None:
            setattr(row, field_name, value)
            self._session.flush()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _resolve_word(entry: SynAntEntry, repo: Repository) -> Optional[object]:
    if entry.word_id is not None:
        return repo.find_word_by_id(entry.word_id)
    return repo.find_word_by_name(entry.english_word)


def _plan_single_field(
    entry: SynAntEntry,
    word,
    field_name: str,
    new_value: Optional[List[str]],
    force: bool,
) -> FieldChange:
    """Return a FieldChange for one field of one entry."""
    if new_value is None:
        return FieldChange(
            action="skip_empty",
            english_word=entry.english_word,
            field_name=field_name,
            word_id=word.id if word else None,
            reason="not specified in CSV",
        )

    if word is None:
        return FieldChange(
            action="skip_no_match",
            english_word=entry.english_word,
            field_name=field_name,
            reason="not found in collection_words",
        )

    old_value = getattr(word, field_name, None)
    if old_value is not None and not force:
        return FieldChange(
            action="skip_force",
            english_word=entry.english_word,
            field_name=field_name,
            new_value=new_value,
            old_value=old_value,
            word_id=word.id,
            reason="existing value preserved (use --force to overwrite)",
        )

    # Compare as sorted lower-case sets to detect semantic noop
    def _canonical(lst: Optional[List[str]]) -> frozenset:
        return frozenset(x.lower() for x in lst) if lst else frozenset()

    action = "noop" if _canonical(old_value) == _canonical(new_value) else "set"
    return FieldChange(
        action=action,
        english_word=entry.english_word,
        field_name=field_name,
        new_value=new_value,
        old_value=old_value,
        word_id=word.id,
    )


def plan_import(
    entries: list,
    repo: Repository,
    *,
    force: bool = False,
    field_names: Optional[List[str]] = None,
    priority_tier: Optional[int] = None,
    priority_map: Optional[dict] = None,
) -> SynAntPlan:
    if field_names is None:
        field_names = list(FIELDS)

    plan = SynAntPlan()
    for entry in entries:
        key = entry.english_word.lower()

        if priority_tier is not None and priority_map is not None:
            tier = priority_map.get(key)
            if tier != priority_tier:
                for fn in field_names:
                    plan.changes.append(
                        FieldChange(
                            action="skip_tier",
                            english_word=entry.english_word,
                            field_name=fn,
                            reason=f"tier={tier} != requested {priority_tier}",
                        )
                    )
                continue

        word = _resolve_word(entry, repo)

        for fn in field_names:
            new_value = getattr(entry, fn)
            change = _plan_single_field(entry, word, fn, new_value, force)
            plan.changes.append(change)

    return plan


def apply_plan(plan: SynAntPlan, repo: Repository) -> int:
    """Apply all 'set' changes; return count of field writes."""
    count = 0
    for ch in plan.changes:
        if ch.action == "set" and ch.word_id is not None and ch.new_value is not None:
            repo.set_field(ch.word_id, ch.field_name, ch.new_value)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(
    plan: SynAntPlan,
    *,
    dry_run: bool,
    force: bool,
    field_names: List[str],
    elapsed: float,
) -> str:
    lines: list = []
    lines.append("# Synonyms/Antonyms Import Report")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Generated: {ts}  ")
    lines.append(f"Mode: {'dry-run' if dry_run else 'live'}  ")
    lines.append(f"Force overwrite: {force}  ")
    lines.append(f"Fields updated: {', '.join(field_names)}  ")
    lines.append(f"Elapsed: {elapsed:.2f}s")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Field | set | noop | skip_force | skip_no_match | skip_empty | skip_tier |")
    lines.append("|-------|-----|------|------------|---------------|------------|-----------|")
    for fn in field_names:
        row_parts = [fn]
        for action in ("set", "noop", "skip_force", "skip_no_match", "skip_empty", "skip_tier"):
            row_parts.append(str(plan.action_count(action, fn)))
        lines.append("| " + " | ".join(row_parts) + " |")
    lines.append("")

    if plan.errors:
        lines.append("## Parse Errors")
        lines.append("")
        for e in plan.errors[:20]:
            lines.append(f"- {e}")
        if len(plan.errors) > 20:
            lines.append(f"- … and {len(plan.errors) - 20} more")
        lines.append("")

    skipped_no_match = list({ch.english_word for ch in plan.changes if ch.action == "skip_no_match"})
    if skipped_no_match:
        lines.append("## Words Not Found in DB")
        lines.append("")
        for w in sorted(skipped_no_match)[:20]:
            lines.append(f"- `{w}`")
        if len(skipped_no_match) > 20:
            lines.append(f"- … and {len(skipped_no_match) - 20} more")
        lines.append("")

    total_set = plan.action_count("set")
    lines.append(f"**Total field writes: {total_set}** (0 if dry-run)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import synonyms and antonyms into collection_words",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files",
        nargs="*",
        help="CSV files to import (default: content/vocabulary/synonyms_antonyms.csv)",
    )
    p.add_argument("--dry-run", action="store_true", help="plan only, no DB writes")
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing non-null synonym/antonym values",
    )
    p.add_argument(
        "--field",
        choices=["synonyms", "antonyms", "both"],
        default="both",
        help="which field(s) to update (default: both)",
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
    field_names = list(FIELDS) if args.field == "both" else [args.field]

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
        plan = plan_import(
            entries,
            repo,
            force=args.force,
            field_names=field_names,
            priority_tier=args.priority_tier,
            priority_map=priority_map,
        )

        if not args.dry_run:
            written = apply_plan(plan, repo)
            db.session.commit()
        else:
            written = 0

        elapsed = time.monotonic() - t0
        report = format_report(
            plan,
            dry_run=args.dry_run,
            force=args.force,
            field_names=field_names,
            elapsed=elapsed,
        )
        print(report)

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"Report written to {report_path}")

        prefix = "[dry-run] " if args.dry_run else ""
        for fn in field_names:
            print(
                f"{prefix}{fn}: "
                f"{plan.action_count('set', fn)} set, "
                f"{plan.action_count('noop', fn)} noop, "
                f"{plan.action_count('skip_force', fn)} preserved, "
                f"{plan.action_count('skip_no_match', fn)} not found"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
