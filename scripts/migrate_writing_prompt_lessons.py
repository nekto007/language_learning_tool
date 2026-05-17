"""Migrate writing_prompt lessons to the new schema fields.

For each writing_prompt lesson this script:
  1. Sets ``mode`` per CEFR level:
       A0/A1 → guided, A2 → structured, B1 → paragraph,
       B2 → opinion, C1 → style, C2 → rhetoric.
  2. Adds ``prompt_ru`` (Russian task copy) — falls back to
     "Напишите ответ:" if not available in the lookup table.
  3. Sets ``min_sentences`` per level (A0/A1: 3, A2: 4, B1: 5,
     B2: 6, C1: 7, C2: 8) when not already present.
  4. Sets ``min_checklist`` (guided → 3, all others → 2) when absent.
  5. Defaults ``hint_words`` and ``target_phrases`` to ``[]`` if absent.
  6. Skips lessons that already have both ``prompt_ru`` (non-empty)
     and ``mode`` (valid value).

Usage:
    python scripts/migrate_writing_prompt_lessons.py [--apply] [--level CODE]
                                                     [--report PATH]

Flags:
    --apply         Write changes to DB (default: dry-run only)
    --level CODE    Only process lessons in this CEFR level (A1, A2, …)
    --report PATH   Write markdown report to PATH
                    (default: reports/writing_prompt_migration.md)

Design notes:
  - Scripts default to dry-run; --apply is required to mutate the DB.
  - Idempotent: a second run on already-migrated content is a no-op.
  - mode is never overwritten when already set to a valid value.
  - prompt_ru is never overwritten when already set to a non-empty string.
  - min_sentences, min_checklist are not overwritten if already present.
  - hint_words, target_phrases default to [] only when key is absent entirely.
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "writing_prompt_migration.md"

VALID_MODES = ("guided", "structured", "paragraph", "opinion", "style", "rhetoric")

# CEFR level → default mode
LEVEL_MODE: dict[str, str] = {
    "A0": "guided",
    "A1": "guided",
    "A2": "structured",
    "B1": "paragraph",
    "B2": "opinion",
    "C1": "style",
    "C2": "rhetoric",
}

DEFAULT_MODE = "structured"

# CEFR level → min_sentences
LEVEL_MIN_SENTENCES: dict[str, int] = {
    "A0": 3,
    "A1": 3,
    "A2": 4,
    "B1": 5,
    "B2": 6,
    "C1": 7,
    "C2": 8,
}

DEFAULT_MIN_SENTENCES = 4

# mode → min_checklist
MODE_MIN_CHECKLIST: dict[str, int] = {
    "guided": 3,
}
DEFAULT_MIN_CHECKLIST = 2

DEFAULT_PROMPT_RU = "Напишите ответ:"


# ---------------------------------------------------------------------------
# Pure-function content patching — no DB dependency
# ---------------------------------------------------------------------------


def _mode_for_level(level_code: str) -> str:
    return LEVEL_MODE.get((level_code or "").upper(), DEFAULT_MODE)


def _min_sentences_for_level(level_code: str) -> int:
    return LEVEL_MIN_SENTENCES.get((level_code or "").upper(), DEFAULT_MIN_SENTENCES)


def _min_checklist_for_mode(mode: str) -> int:
    return MODE_MIN_CHECKLIST.get(mode, DEFAULT_MIN_CHECKLIST)


def patch_content(content: dict, level_code: str = "") -> tuple[dict, list[str]]:
    """Return (patched_content, list_of_change_descriptions).

    If nothing changed, returns (content, []).
    Idempotent: calling twice produces no more changes.
    """
    content = copy.deepcopy(content)
    changes: list[str] = []

    existing_mode = content.get("mode")
    existing_prompt_ru = content.get("prompt_ru")

    already_has_mode = existing_mode in VALID_MODES
    already_has_prompt_ru = bool(existing_prompt_ru and str(existing_prompt_ru).strip())

    # ---- 1. If both prompt_ru and mode are present: nothing to do ----
    if already_has_mode and already_has_prompt_ru:
        return content, []

    # ---- 2. Set mode ----
    if not already_has_mode:
        new_mode = _mode_for_level(level_code)
        content["mode"] = new_mode
        changes.append(f"set_mode={new_mode}")
    else:
        new_mode = existing_mode  # type: ignore[assignment]

    # ---- 3. Set prompt_ru ----
    if not already_has_prompt_ru:
        content["prompt_ru"] = DEFAULT_PROMPT_RU
        changes.append("set_prompt_ru=default")

    # ---- 4. Set min_sentences (only if not already set) ----
    if not content.get("min_sentences"):
        min_sent = _min_sentences_for_level(level_code)
        content["min_sentences"] = min_sent
        changes.append(f"set_min_sentences={min_sent}")

    # ---- 5. Set min_checklist (only if not already set) ----
    if not content.get("min_checklist"):
        mode_for_checklist = content.get("mode") or DEFAULT_MODE
        min_cl = _min_checklist_for_mode(mode_for_checklist)
        content["min_checklist"] = min_cl
        changes.append(f"set_min_checklist={min_cl}")

    # ---- 6. Default hint_words to [] if key is absent ----
    if "hint_words" not in content:
        content["hint_words"] = []
        changes.append("set_hint_words=[]")

    # ---- 7. Default target_phrases to [] if key is absent ----
    if "target_phrases" not in content:
        content["target_phrases"] = []
        changes.append("set_target_phrases=[]")

    return content, changes


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
        .filter(Lessons.type == "writing_prompt")
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
    mode_label = "DRY-RUN" if dry_run else "APPLIED"
    migrated = [r for r in rows if r.action == "migrate"]
    noop = [r for r in rows if r.action == "noop"]
    lines = [
        f"# Writing Prompt Lessons Migration Report ({mode_label})\n",
        f"Total writing_prompt lessons: **{len(rows)}**  ",
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
        "Mode is assigned from CEFR level: A0/A1=guided, A2=structured,  \n"
        "B1=paragraph, B2=opinion, C1=style, C2=rhetoric.  \n"
        "`prompt_ru` defaults to \"Напишите ответ:\" when absent; hand-curated  \n"
        "translations can be applied via a separate patch once curated.  \n"
        "`min_sentences` defaults by level (A0/A1: 3, A2: 4, B1: 5, B2: 6, C1: 7, C2: 8).  \n"
        "`min_checklist` defaults to 3 for guided mode, 2 otherwise.  \n"
        "`hint_words` and `target_phrases` default to [] when the key is absent.  \n"
        "Lessons that already have both `prompt_ru` and `mode` are left untouched.  \n"
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
        description="Migrate writing_prompt lesson content to new schema (dry-run by default)."
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
    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(
        f"\n[{mode}] {migrated_count}/{len(rows)} lessons migrated. "
        f"Report written to {args.report}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
