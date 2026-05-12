"""Idempotent cultural-notes importer for cultural_notes table.

Reads a CSV from content/vocabulary/cultural_notes.csv (or supplied paths)
and inserts rows into the `cultural_notes` table.  A word may have multiple
notes; the dedup key is (word_id, normalised_note_text) — re-running the
script produces zero new rows when the content has not changed.

CSV columns:
    english_word  — case-insensitive match against collection_words.english_word
    note          — cultural context text (required, max 200 chars)
    context       — optional label: idiom / phrasal verb / politeness / etc.
    word_id       — optional numeric id; takes priority over english_word lookup

Flags:
    --dry-run           plan only, no DB writes
    --report PATH       write markdown report to PATH
    --priority-tier N   only insert notes for words whose priority_tier equals N
    FILE                one or more CSV files; defaults to
                        content/vocabulary/cultural_notes.csv

Usage:
    python scripts/import_cultural_notes.py [FILE ...] [options]

Task 41 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
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
DEFAULT_CSV_PATH = PROJECT_ROOT / "content" / "vocabulary" / "cultural_notes.csv"
PRIORITY_WORDS_PATH = PROJECT_ROOT / "content" / "vocabulary" / "priority_words.csv"

MAX_NOTE_LENGTH = 200     # hard ceiling
MAX_CONTEXT_LENGTH = 100  # matches DB column size


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_note(raw: str) -> tuple:
    """Strip whitespace; enforce max length.

    Returns (normalized_str, None) on success or (None, error_str) on failure.
    """
    if not isinstance(raw, str):
        raw = str(raw)
    value = raw.strip()
    if not value:
        return None, f"empty note: {raw!r}"
    if len(value) > MAX_NOTE_LENGTH:
        return None, f"note too long ({len(value)} chars, max {MAX_NOTE_LENGTH}): {value[:40]!r}…"
    return value, None


def normalize_context(raw: str) -> str:
    """Strip whitespace and truncate to max context length; empty → None."""
    if not isinstance(raw, str):
        raw = str(raw)
    value = raw.strip()[:MAX_CONTEXT_LENGTH]
    return value or ""


# ---------------------------------------------------------------------------
# Entry data classes
# ---------------------------------------------------------------------------


@dataclass
class CulturalNoteEntry:
    english_word: str
    note: str
    context: str = ""
    word_id: Optional[int] = None
    raw_row: dict = field(default_factory=dict)


@dataclass
class CulturalNoteChange:
    action: str  # 'insert' | 'noop' | 'skip_no_match' | 'skip_tier'
    english_word: str
    note: str
    context: str = ""
    word_id: Optional[int] = None
    reason: str = ""


@dataclass
class CulturalNotePlan:
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
    """Return (CulturalNoteEntry, None) or (None, error_str)."""
    word = str(row.get("english_word") or "").strip()
    if not word:
        return None, "empty english_word"

    raw_note = row.get("note") or row.get("etymology") or ""
    note, err = normalize_note(raw_note)
    if err:
        return None, err

    context = normalize_context(row.get("context") or "")

    raw_word_id = row.get("word_id") or ""
    word_id: Optional[int] = None
    if str(raw_word_id).strip():
        try:
            word_id = int(str(raw_word_id).strip())
        except ValueError:
            return None, f"invalid word_id: {raw_word_id!r}"

    return (
        CulturalNoteEntry(
            english_word=word,
            note=note,
            context=context,
            word_id=word_id,
            raw_row=dict(row),
        ),
        None,
    )


def load_csv(paths: list) -> tuple:
    """Return (entries, errors) from one or more CSV files.

    Unlike etymology importer, multiple rows with the same english_word are
    kept (each row represents a distinct cultural note).
    """
    entries: list = []
    errors: list = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                lines = [ln for ln in fh if not ln.startswith("#")]
            reader = csv.DictReader(lines)
            if reader.fieldnames is None or "english_word" not in reader.fieldnames:
                errors.append(f"{path}: missing 'english_word' column")
                continue
            if "note" not in reader.fieldnames and "etymology" not in reader.fieldnames:
                errors.append(f"{path}: missing 'note' column")
                continue
            for idx, row in enumerate(reader):
                entry, err = parse_row(row)
                if err:
                    errors.append(f"{path}[{idx}]: {err}")
                    continue
                entries.append(entry)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return entries, errors


# ---------------------------------------------------------------------------
# Priority-tier filtering
# ---------------------------------------------------------------------------


def load_priority_tiers(path: Path) -> dict:
    """Return mapping {english_word_lower: priority_tier}."""
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

    def get_existing_notes(self, word_id: int) -> list:
        """Return list of (note_text,) tuples for a word."""
        raise NotImplementedError

    def insert_note(self, word_id: int, note: str, context: str) -> None:
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

    def get_existing_notes(self, word_id: int) -> list:
        from app.curriculum.models import CulturalNote
        rows = (
            self._session.query(CulturalNote.note)
            .filter(CulturalNote.word_id == word_id)
            .all()
        )
        return [r.note for r in rows]

    def insert_note(self, word_id: int, note: str, context: str) -> None:
        from app.curriculum.models import CulturalNote
        cn = CulturalNote(word_id=word_id, note=note, context=context or None)
        self._session.add(cn)
        self._session.flush()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _resolve_word(entry: CulturalNoteEntry, repo: Repository) -> Optional[object]:
    if entry.word_id is not None:
        return repo.find_word_by_id(entry.word_id)
    return repo.find_word_by_name(entry.english_word)


def plan_cultural_notes(
    entries: list,
    repo: Repository,
    *,
    priority_tier: Optional[int] = None,
    priority_map: Optional[dict] = None,
) -> CulturalNotePlan:
    plan = CulturalNotePlan()
    # Cache existing notes per word_id to avoid repeated DB queries
    existing_cache: dict = {}

    for entry in entries:
        key = entry.english_word.lower()

        if priority_tier is not None and priority_map is not None:
            tier = priority_map.get(key)
            if tier != priority_tier:
                plan.changes.append(
                    CulturalNoteChange(
                        action="skip_tier",
                        english_word=entry.english_word,
                        note=entry.note,
                        context=entry.context,
                        reason=f"tier={tier} != requested {priority_tier}",
                    )
                )
                continue

        word = _resolve_word(entry, repo)
        if word is None:
            plan.changes.append(
                CulturalNoteChange(
                    action="skip_no_match",
                    english_word=entry.english_word,
                    note=entry.note,
                    context=entry.context,
                    reason="not found in collection_words",
                )
            )
            continue

        wid = word.id
        if wid not in existing_cache:
            existing_cache[wid] = set(repo.get_existing_notes(wid))

        existing_texts = existing_cache[wid]
        if entry.note in existing_texts:
            plan.changes.append(
                CulturalNoteChange(
                    action="noop",
                    english_word=entry.english_word,
                    note=entry.note,
                    context=entry.context,
                    word_id=wid,
                    reason="identical note already exists",
                )
            )
        else:
            plan.changes.append(
                CulturalNoteChange(
                    action="insert",
                    english_word=entry.english_word,
                    note=entry.note,
                    context=entry.context,
                    word_id=wid,
                )
            )
            # Update cache so subsequent CSV rows for the same word are deduped
            existing_cache[wid].add(entry.note)

    return plan


def apply_plan(plan: CulturalNotePlan, repo: Repository) -> int:
    """Insert all 'insert' changes; return count of rows written."""
    count = 0
    for ch in plan.changes:
        if ch.action == "insert" and ch.word_id is not None:
            repo.insert_note(ch.word_id, ch.note, ch.context)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(
    plan: CulturalNotePlan,
    *,
    dry_run: bool,
    elapsed: float,
) -> str:
    lines: list = []
    lines.append("# Cultural Notes Import Report")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Generated: {ts}  ")
    lines.append(f"Mode: {'dry-run' if dry_run else 'live'}  ")
    lines.append(f"Elapsed: {elapsed:.2f}s")
    lines.append("")
    lines.append("## Results")
    lines.append("")

    c = plan.counts
    lines.append("| Action | Count |")
    lines.append("|--------|-------|")
    for action in ("insert", "noop", "skip_no_match", "skip_tier"):
        n = c.get(action, 0)
        if n:
            lines.append(f"| {action} | {n} |")
    if plan.errors:
        lines.append(f"| errors | {len(plan.errors)} |")
    lines.append("")

    if plan.errors:
        lines.append("## Parse Errors")
        lines.append("")
        for e in plan.errors[:20]:
            lines.append(f"- {e}")
        if len(plan.errors) > 20:
            lines.append(f"- … and {len(plan.errors) - 20} more")
        lines.append("")

    skipped_no_match = [ch for ch in plan.changes if ch.action == "skip_no_match"]
    if skipped_no_match:
        lines.append("## Words Not Found in DB")
        lines.append("")
        for ch in skipped_no_match[:20]:
            lines.append(f"- `{ch.english_word}`")
        if len(skipped_no_match) > 20:
            lines.append(f"- … and {len(skipped_no_match) - 20} more")
        lines.append("")

    total_inserted = c.get("insert", 0)
    lines.append(f"**Total rows written: {total_inserted}** (0 if dry-run)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import cultural notes into cultural_notes table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files",
        nargs="*",
        help="CSV files to import (default: content/vocabulary/cultural_notes.csv)",
    )
    p.add_argument("--dry-run", action="store_true", help="plan only, no DB writes")
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
        help="only insert notes for words whose priority_tier equals N",
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
        plan = plan_cultural_notes(
            entries,
            repo,
            priority_tier=args.priority_tier,
            priority_map=priority_map,
        )

        if not args.dry_run:
            written = apply_plan(plan, repo)
            db.session.commit()
        else:
            written = 0

        elapsed = time.monotonic() - t0
        report = format_report(plan, dry_run=args.dry_run, elapsed=elapsed)
        print(report)

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"Report written to {report_path}")

        c = plan.counts
        total_inserted = c.get("insert", 0)
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}cultural notes: {total_inserted} inserted, "
            f"{c.get('noop', 0)} noop, "
            f"{c.get('skip_no_match', 0)} not found"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
