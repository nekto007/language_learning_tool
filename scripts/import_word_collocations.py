"""Idempotent word collocations importer for collection_words.

Reads a CSV from content/vocabulary/collocations.csv (or a supplied path)
and upserts rows into the `word_collocations` table.

CSV format:
    english_word,collocation_phrase,translation,example
  - english_word: case-insensitive match against collection_words.english_word
  - collocation_phrase: the collocation text (e.g. "make a decision")
  - translation: Russian translation of the phrase (required)
  - example: full example sentence (optional)

Upsert key: (word_id, collocation_phrase) — case-insensitive phrase comparison
for noop detection, but the original case is stored.

Idempotency:
  - Rows whose phrase already exists are skipped unless --force.
  - Running twice on the same CSV produces zero changes on the second run.

Flags:
    --dry-run           plan only, no DB writes
    --force             overwrite existing translation/example values
    --report PATH       write markdown report to PATH
    --priority-tier N   only update words whose priority_tier in
                        content/vocabulary/priority_words.csv equals N (1/2/3)
    FILE                one or more CSV files; defaults to
                        content/vocabulary/collocations.csv

Usage:
    python scripts/import_word_collocations.py [FILE ...] [options]

Task 39 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "content" / "vocabulary" / "collocations.csv"
PRIORITY_WORDS_PATH = PROJECT_ROOT / "content" / "vocabulary" / "priority_words.csv"


# ---------------------------------------------------------------------------
# Entry data classes
# ---------------------------------------------------------------------------


@dataclass
class CollocationEntry:
    english_word: str
    collocation_phrase: str
    translation: str
    example: Optional[str]
    word_id: Optional[int] = None
    raw_row: dict = field(default_factory=dict)


@dataclass
class CollocationChange:
    action: str  # 'insert' | 'noop' | 'update' | 'skip_force' | 'skip_no_match' | 'skip_tier'
    english_word: str
    collocation_phrase: str
    translation: str
    example: Optional[str] = None
    word_id: Optional[int] = None
    existing_id: Optional[int] = None  # WordCollocation.id when row exists
    reason: str = ""


@dataclass
class CollocationPlan:
    changes: List[CollocationChange] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        c: dict = {}
        for ch in self.changes:
            c[ch.action] = c.get(ch.action, 0) + 1
        return c

    def action_count(self, action: str) -> int:
        return sum(1 for ch in self.changes if ch.action == action)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_row(row: dict) -> tuple:
    """Return (CollocationEntry, None) or (None, error_str)."""
    word = str(row.get("english_word") or "").strip()
    if not word:
        return None, "empty english_word"

    phrase = str(row.get("collocation_phrase") or "").strip()
    if not phrase:
        return None, f"empty collocation_phrase for word {word!r}"

    translation = str(row.get("translation") or "").strip()
    if not translation:
        return None, f"empty translation for phrase {phrase!r}"

    raw_example = row.get("example") or ""
    example: Optional[str] = str(raw_example).strip() or None

    raw_word_id = row.get("word_id") or ""
    word_id: Optional[int] = None
    if str(raw_word_id).strip():
        try:
            word_id = int(str(raw_word_id).strip())
        except ValueError:
            return None, f"invalid word_id: {raw_word_id!r}"

    return CollocationEntry(
        english_word=word,
        collocation_phrase=phrase,
        translation=translation,
        example=example,
        word_id=word_id,
        raw_row=dict(row),
    ), None


def load_csv(paths: list) -> tuple:
    """Return (entries, errors) from one or more CSV files."""
    entries: list = []
    errors: list = []
    seen: set = set()  # (english_word_lower, phrase_lower)

    for path in paths:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                lines = [ln for ln in fh if not ln.startswith("#")]
            reader = csv.DictReader(lines)
            if reader.fieldnames is None or "english_word" not in reader.fieldnames:
                errors.append(f"{path}: missing 'english_word' column")
                continue
            if "collocation_phrase" not in (reader.fieldnames or []):
                errors.append(f"{path}: missing 'collocation_phrase' column")
                continue
            for idx, row in enumerate(reader):
                entry, err = parse_row(row)
                if err:
                    errors.append(f"{path}[{idx}]: {err}")
                    continue
                key = (entry.english_word.lower(), entry.collocation_phrase.lower())
                if key in seen:
                    # Last row for same (word, phrase) wins — remove earlier entry
                    entries = [
                        e for e in entries
                        if (e.english_word.lower(), e.collocation_phrase.lower()) != key
                    ]
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

    def find_collocation(self, word_id: int, phrase: str) -> Optional[object]:
        raise NotImplementedError

    def insert_collocation(
        self,
        word_id: int,
        phrase: str,
        translation: str,
        example: Optional[str],
    ) -> object:
        raise NotImplementedError

    def update_collocation(
        self,
        collocation_id: int,
        translation: str,
        example: Optional[str],
    ) -> None:
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

    def find_collocation(self, word_id: int, phrase: str) -> Optional[object]:
        from app.curriculum.models import WordCollocation
        return (
            self._session.query(WordCollocation)
            .filter(
                WordCollocation.word_id == word_id,
                WordCollocation.collocation_phrase.ilike(phrase),
            )
            .first()
        )

    def insert_collocation(
        self,
        word_id: int,
        phrase: str,
        translation: str,
        example: Optional[str],
    ) -> object:
        from app.curriculum.models import WordCollocation
        row = WordCollocation(
            word_id=word_id,
            collocation_phrase=phrase,
            translation=translation,
            example=example,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_collocation(
        self,
        collocation_id: int,
        translation: str,
        example: Optional[str],
    ) -> None:
        from app.curriculum.models import WordCollocation
        row = self._session.query(WordCollocation).get(collocation_id)
        if row is not None:
            row.translation = translation
            row.example = example
            self._session.flush()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _resolve_word(entry: CollocationEntry, repo: Repository) -> Optional[object]:
    if entry.word_id is not None:
        return repo.find_word_by_id(entry.word_id)
    return repo.find_word_by_name(entry.english_word)


def plan_import(
    entries: list,
    repo: Repository,
    *,
    force: bool = False,
    priority_tier: Optional[int] = None,
    priority_map: Optional[dict] = None,
) -> CollocationPlan:
    plan = CollocationPlan()

    for entry in entries:
        key = entry.english_word.lower()

        if priority_tier is not None and priority_map is not None:
            tier = priority_map.get(key)
            if tier != priority_tier:
                plan.changes.append(
                    CollocationChange(
                        action="skip_tier",
                        english_word=entry.english_word,
                        collocation_phrase=entry.collocation_phrase,
                        translation=entry.translation,
                        example=entry.example,
                        reason=f"tier={tier} != requested {priority_tier}",
                    )
                )
                continue

        word = _resolve_word(entry, repo)
        if word is None:
            plan.changes.append(
                CollocationChange(
                    action="skip_no_match",
                    english_word=entry.english_word,
                    collocation_phrase=entry.collocation_phrase,
                    translation=entry.translation,
                    example=entry.example,
                    reason="not found in collection_words",
                )
            )
            continue

        existing = repo.find_collocation(word.id, entry.collocation_phrase)

        if existing is None:
            plan.changes.append(
                CollocationChange(
                    action="insert",
                    english_word=entry.english_word,
                    collocation_phrase=entry.collocation_phrase,
                    translation=entry.translation,
                    example=entry.example,
                    word_id=word.id,
                )
            )
        else:
            same = (
                existing.translation == entry.translation
                and existing.example == entry.example
            )
            if same:
                plan.changes.append(
                    CollocationChange(
                        action="noop",
                        english_word=entry.english_word,
                        collocation_phrase=entry.collocation_phrase,
                        translation=entry.translation,
                        example=entry.example,
                        word_id=word.id,
                        existing_id=existing.id,
                        reason="already identical",
                    )
                )
            elif not force:
                plan.changes.append(
                    CollocationChange(
                        action="skip_force",
                        english_word=entry.english_word,
                        collocation_phrase=entry.collocation_phrase,
                        translation=entry.translation,
                        example=entry.example,
                        word_id=word.id,
                        existing_id=existing.id,
                        reason="existing values preserved (use --force to overwrite)",
                    )
                )
            else:
                plan.changes.append(
                    CollocationChange(
                        action="update",
                        english_word=entry.english_word,
                        collocation_phrase=entry.collocation_phrase,
                        translation=entry.translation,
                        example=entry.example,
                        word_id=word.id,
                        existing_id=existing.id,
                    )
                )

    return plan


def apply_plan(plan: CollocationPlan, repo: Repository) -> int:
    """Apply all 'insert' and 'update' changes; return count of rows written."""
    count = 0
    for ch in plan.changes:
        if ch.action == "insert" and ch.word_id is not None:
            repo.insert_collocation(ch.word_id, ch.collocation_phrase, ch.translation, ch.example)
            count += 1
        elif ch.action == "update" and ch.existing_id is not None:
            repo.update_collocation(ch.existing_id, ch.translation, ch.example)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(
    plan: CollocationPlan,
    *,
    dry_run: bool,
    force: bool,
    elapsed: float,
) -> str:
    lines: list = []
    lines.append("# Word Collocations Import Report")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Generated: {ts}  ")
    lines.append(f"Mode: {'dry-run' if dry_run else 'live'}  ")
    lines.append(f"Force overwrite: {force}  ")
    lines.append(f"Elapsed: {elapsed:.2f}s")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Action | Count |")
    lines.append("|--------|-------|")
    for action in ("insert", "update", "noop", "skip_force", "skip_no_match", "skip_tier"):
        lines.append(f"| {action} | {plan.action_count(action)} |")
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

    total_written = plan.action_count("insert") + plan.action_count("update")
    lines.append(f"**Total rows written: {total_written}** (0 if dry-run)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import word collocations into word_collocations table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files",
        nargs="*",
        help="CSV files to import (default: content/vocabulary/collocations.csv)",
    )
    p.add_argument("--dry-run", action="store_true", help="plan only, no DB writes")
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing translation/example values",
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
    from app.utils.db import db

    app = create_app()
    t0 = time.monotonic()

    with app.app_context():
        repo = DBRepository(db.session)
        plan = plan_import(
            entries,
            repo,
            force=args.force,
            priority_tier=args.priority_tier,
            priority_map=priority_map,
        )

        if not args.dry_run:
            written = apply_plan(plan, repo)
            db.session.commit()
        else:
            written = 0

        elapsed = time.monotonic() - t0
        report = format_report(plan, dry_run=args.dry_run, force=args.force, elapsed=elapsed)
        print(report)

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"Report written to {report_path}")

        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}insert: {plan.action_count('insert')}, "
            f"update: {plan.action_count('update')}, "
            f"noop: {plan.action_count('noop')}, "
            f"skip_force: {plan.action_count('skip_force')}, "
            f"not_found: {plan.action_count('skip_no_match')}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
