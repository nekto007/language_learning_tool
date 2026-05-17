"""Migrate translation lessons to multi-item + mode schema.

For each translation lesson this script:
  1. Wraps legacy single ``russian``/``english`` content into
     ``items: [{russian, english, hint_words, alternatives}]``.
  2. Sets ``mode`` per CEFR level: guided (A0/A1) / open (A2/B1) /
     rubric (B2/C1/C2).
  3. Preserves any existing ``hints``, ``alternatives``, ``notes``.
  4. Skips lessons that already have both ``items[]`` and ``mode``.

Usage:
    python scripts/migrate_translation_lessons.py [--apply] [--level CODE]
                                                  [--report PATH]

Flags:
    --apply         Write changes to DB (default: dry-run only)
    --level CODE    Only process lessons in this CEFR level (A1, A2, …)
    --report PATH   Write markdown report to PATH
                    (default: reports/translation_migration.md)

Design notes:
  - Scripts default to dry-run; --apply is required to mutate the DB.
  - Idempotent: a second run on already-migrated content is a no-op.
  - mode is assigned from CEFR level only; it is never overwritten if
    already present with a valid value.
  - hint_words, alternatives, notes at the top level are moved into the
    first item (or the respective items) so legacy data is not lost.
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "translation_migration.md"

VALID_MODES = ("guided", "open", "rubric")

# CEFR level → default mode
LEVEL_MODE: dict[str, str] = {
    "A0": "guided",
    "A1": "guided",
    "A2": "open",
    "B1": "open",
    "B2": "rubric",
    "C1": "rubric",
    "C2": "rubric",
}

DEFAULT_MODE = "open"


# ---------------------------------------------------------------------------
# Pure-function content patching — no DB dependency
# ---------------------------------------------------------------------------


def _mode_for_level(level_code: str) -> str:
    return LEVEL_MODE.get((level_code or "").upper(), DEFAULT_MODE)


def patch_content(content: dict, level_code: str = "") -> tuple[dict, list[str]]:
    """Return (patched_content, list_of_change_descriptions).

    If nothing changed, patched_content is content (same object).
    Idempotent: calling twice produces no more changes.
    """
    content = copy.deepcopy(content)
    changes: list[str] = []

    existing_items = content.get("items")
    existing_mode = content.get("mode")

    already_has_items = isinstance(existing_items, list) and len(existing_items) > 0
    already_has_mode = existing_mode in VALID_MODES

    # ---- 1. If both items[] and mode are present: nothing to do ----
    if already_has_items and already_has_mode:
        return content, []

    # ---- 2. Build items list ----
    if already_has_items:
        # items already present, just normalise structure
        items = _normalise_items(existing_items)
        if items != existing_items:
            content["items"] = items
            changes.append("normalised_items")
    else:
        # Wrap legacy single russian/english pair
        russian = (content.get("russian") or "").strip()
        english = (content.get("english") or "").strip()

        if not russian or not english:
            # Nothing to wrap — content is incomplete, leave as is
            return content, []

        item: dict = {
            "russian": russian,
            "english": english,
            "hint_words": _as_list(content.get("hint_words")),
            "alternatives": _as_list(content.get("alternatives")),
        }
        # Preserve notes if present
        notes = content.get("notes")
        if notes:
            item["notes"] = notes

        content["items"] = [item]
        changes.append("wrapped_legacy_to_items")

    # ---- 3. Set mode ----
    if not already_has_mode:
        new_mode = _mode_for_level(level_code)
        content["mode"] = new_mode
        changes.append(f"set_mode={new_mode}")

    return content, changes


def _as_list(value: Any) -> list:
    """Return value if it's a non-empty list, else empty list."""
    if isinstance(value, list):
        return value
    return []


def _normalise_items(items: list) -> list:
    """Ensure each item has required keys with correct types."""
    result = []
    for it in items:
        if not isinstance(it, dict):
            continue
        normalised = dict(it)
        normalised.setdefault("hint_words", [])
        normalised.setdefault("alternatives", [])
        if not isinstance(normalised["hint_words"], list):
            normalised["hint_words"] = []
        if not isinstance(normalised["alternatives"], list):
            normalised["alternatives"] = []
        result.append(normalised)
    return result


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


@dataclass
class MigrateRow:
    lesson_id: int
    level_code: str
    module_number: int
    module_title: str
    lesson_number: int
    lesson_title: str
    action: str  # "migrate" | "noop"
    changes: list[str] = field(default_factory=list)
    before_snapshot: dict = field(default_factory=dict)
    after_snapshot: dict = field(default_factory=dict)


def _build_rows_from_db(db_session, level_filter: str | None) -> list[MigrateRow]:
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session
    q = (
        session.query(
            Lessons.id,
            Lessons.content,
            Lessons.number,
            Lessons.title,
            Module.id,
            Module.number,
            Module.title,
            CEFRLevel.code,
        )
        .filter(Lessons.type == "translation")
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
    )
    if level_filter:
        q = q.filter(CEFRLevel.code == level_filter.upper())

    rows = []
    for (
        lesson_id,
        content,
        lesson_number,
        lesson_title,
        _module_id,
        module_number,
        module_title,
        level_code,
    ) in q.all():
        if not isinstance(content, dict):
            content = {}
        patched, changes = patch_content(content, level_code=level_code or "")
        action = "migrate" if changes else "noop"
        rows.append(
            MigrateRow(
                lesson_id=lesson_id,
                level_code=level_code or "",
                module_number=module_number or 0,
                module_title=module_title or "",
                lesson_number=lesson_number or 0,
                lesson_title=lesson_title or "",
                action=action,
                changes=changes,
                before_snapshot=content,
                after_snapshot=patched,
            )
        )
    return rows


def apply_patches(rows: list[MigrateRow], db_session, dry_run: bool) -> None:
    if dry_run:
        return
    from app.curriculum.models import Lessons
    from sqlalchemy.orm.attributes import flag_modified

    session = db_session.session
    for row in rows:
        if row.action != "migrate":
            continue
        lesson = session.query(Lessons).filter_by(id=row.lesson_id).one()
        lesson.content = row.after_snapshot
        flag_modified(lesson, "content")
    session.commit()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(str(v) for v in r) + " |")
    return "\n".join(lines) + "\n"


def format_report(rows: list[MigrateRow], dry_run: bool) -> str:
    mode = "DRY-RUN" if dry_run else "APPLIED"
    migrated = [r for r in rows if r.action == "migrate"]
    noop = [r for r in rows if r.action == "noop"]
    lines = [
        f"# Translation Lessons Migration Report ({mode})\n",
        f"Total translation lessons: **{len(rows)}**  ",
        f"Migrated: **{len(migrated)}**  ",
        f"No-op (already in new schema): **{len(noop)}**\n",
    ]

    if migrated:
        lines.append("## Migrated Lessons\n")
        table_rows = [
            [
                r.level_code,
                r.module_number,
                r.module_title[:35],
                r.lesson_number,
                r.lesson_title[:40],
                "; ".join(r.changes),
            ]
            for r in migrated
        ]
        lines.append(
            _md_table(
                ["level", "mod#", "module", "les#", "lesson", "changes"],
                table_rows,
            )
        )

    lines.append("\n## Design Notes\n")
    lines.append(
        "Legacy single-item content (`russian`/`english` at root) is wrapped into  \n"
        "`items: [{russian, english, hint_words, alternatives}]`.  \n"
        "Mode is assigned from CEFR level: A0/A1=guided, A2/B1=open, B2/C1/C2=rubric.  \n"
        "The route (`_translation_items_from_content`) supports both shapes for backward  \n"
        "compatibility — this migration makes the stored shape canonical.  \n"
        "Lessons that already have both `items[]` and `mode` are left untouched.  \n"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _try_get_db():
    try:
        from app import create_app
        from app.utils.db import db
    except Exception as exc:
        print(f"WARN: cannot import Flask app: {exc}", file=sys.stderr)
        return None, None
    try:
        app = create_app()
    except Exception as exc:
        print(f"WARN: create_app() failed: {exc}", file=sys.stderr)
        return None, None
    return app, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate translation lesson content to multi-item schema (dry-run by default)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to DB (default: dry-run)",
    )
    parser.add_argument(
        "--level",
        metavar="CODE",
        default=None,
        help="Only process lessons in this CEFR level",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Markdown report output path (default: {DEFAULT_REPORT_PATH})",
    )
    args = parser.parse_args(argv)
    dry_run = not args.apply

    app, db = _try_get_db()
    if app is None or db is None:
        print("ERROR: could not initialise Flask app", file=sys.stderr)
        return 1

    with app.app_context():
        rows = _build_rows_from_db(db, level_filter=args.level)
        apply_patches(rows, db, dry_run=dry_run)

    report_text = format_report(rows, dry_run=dry_run)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_text, encoding="utf-8")
    print(report_text)

    migrated_count = sum(1 for r in rows if r.action == "migrate")
    mode_label = "DRY-RUN" if dry_run else "APPLIED"
    print(
        f"\n[{mode_label}] {migrated_count}/{len(rows)} lessons migrated. "
        f"Report written to {args.report}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
