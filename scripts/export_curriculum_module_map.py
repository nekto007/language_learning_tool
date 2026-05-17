"""Export the canonical curriculum module map.

Reads every source module under ``module_completed/fixed/`` and (optionally)
reconciles it against the target DB. Produces a CSV at
``content/immersion/module_map.csv`` (one row per source module) intended as
the source of truth for content authors writing immersion lessons.

Columns:
    level, file_order, source_module_id, source_filename, title, title_en,
    db_module_id, db_module_number, db_module_title, db_match_status,
    source_lesson_order, source_lesson_count,
    listening_quiz_lesson_ids, translation_quiz_lesson_ids,
    listening_immersion_lesson_ids

* ``source_lesson_order`` is a ``|``-joined sequence of ``"<order>:<type>"``
  tokens, e.g. ``1:vocabulary|2:flashcards|3:grammar|...``.
* ``listening_*_lesson_ids`` columns hold ``|``-joined DB lesson ids for the
  matched module, or empty string when there is no DB match.
* ``db_match_status`` is one of ``matched``, ``only_in_source``, or
  ``unknown`` (when the DB audit was skipped via ``--no-db``).

Usage:
    python scripts/export_curriculum_module_map.py [--output PATH]
                                                   [--source-dir DIR] [--no-db]
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import Any

# Reuse the canonical source-loader from the audit script so both stay in sync.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from audit_immersion_data import (  # noqa: E402
    DEFAULT_SOURCE_DIR,
    SourceModule,
    load_source_modules,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "content" / "immersion" / "module_map.csv"

LISTENING_TYPES = ("listening_quiz", "translation_quiz", "listening_immersion")

CSV_HEADERS = [
    "level",
    "file_order",
    "source_module_id",
    "source_filename",
    "title",
    "title_en",
    "db_module_id",
    "db_module_number",
    "db_module_title",
    "db_match_status",
    "source_lesson_count",
    "source_lesson_order",
    "listening_quiz_lesson_ids",
    "translation_quiz_lesson_ids",
    "listening_immersion_lesson_ids",
]


def _source_lesson_order(module: SourceModule) -> str:
    """Build the ``|``-joined ``"<order>:<type>"`` token list. Lessons missing an
    explicit ``order`` keep their file index but mark the order as ``?`` to
    surface the gap to content authors."""
    tokens: list[str] = []
    for idx, lesson in enumerate(module.lessons, start=1):
        order = lesson.order if isinstance(lesson.order, int) else None
        order_token = str(order) if order is not None else f"?{idx}"
        tokens.append(f"{order_token}:{lesson.type or 'unknown'}")
    return "|".join(tokens)


def _query_db_state(db_session) -> dict[str, Any]:
    """Return ``{'modules': [...], 'lessons_by_module_type': {(mid, type): [ids]}}``.

    Caller is responsible for the Flask app context.
    """
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session

    module_rows = (
        session.query(Module.id, Module.number, Module.title, CEFRLevel.code)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .all()
    )
    db_modules = [
        {"id": r[0], "number": r[1], "title": r[2], "level": r[3]} for r in module_rows
    ]

    lesson_rows = (
        session.query(Lessons.module_id, Lessons.type, Lessons.id, Lessons.number)
        .filter(Lessons.type.in_(LISTENING_TYPES))
        .order_by(Lessons.module_id, Lessons.number, Lessons.id)
        .all()
    )
    lessons_by_module_type: dict[tuple[int, str], list[int]] = {}
    for module_id, lesson_type, lesson_id, _ in lesson_rows:
        lessons_by_module_type.setdefault((module_id, lesson_type), []).append(int(lesson_id))

    return {"modules": db_modules, "lessons_by_module_type": lessons_by_module_type}


def _match_db_module(
    source: SourceModule, db_modules: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Match by (level, file_order) first, then by (level, title)."""
    for m in db_modules:
        if m["level"] == source.level and m.get("number") == source.file_order:
            return m
    for m in db_modules:
        if m["level"] == source.level and (m.get("title") or "").strip() == source.title:
            return m
    return None


def build_rows(
    source_modules: list[SourceModule],
    db_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Produce one row per source module, ordered by (level, file_order)."""
    sorted_modules = sorted(source_modules, key=lambda m: (m.level, m.file_order))
    db_modules = (db_state or {}).get("modules", [])
    lessons_by_module_type: dict[tuple[int, str], list[int]] = (
        (db_state or {}).get("lessons_by_module_type", {})
    )

    rows: list[dict[str, Any]] = []
    for src in sorted_modules:
        row: dict[str, Any] = {
            "level": src.level,
            "file_order": src.file_order,
            "source_module_id": src.module_id or "",
            "source_filename": src.filename,
            "title": src.title,
            "title_en": src.title_en,
            "db_module_id": "",
            "db_module_number": "",
            "db_module_title": "",
            "db_match_status": "unknown" if db_state is None else "only_in_source",
            "source_lesson_count": len(src.lessons),
            "source_lesson_order": _source_lesson_order(src),
            "listening_quiz_lesson_ids": "",
            "translation_quiz_lesson_ids": "",
            "listening_immersion_lesson_ids": "",
        }
        if db_state is not None:
            match = _match_db_module(src, db_modules)
            if match is not None:
                row["db_module_id"] = match["id"]
                row["db_module_number"] = match.get("number") or ""
                row["db_module_title"] = match.get("title") or ""
                row["db_match_status"] = "matched"
                for ltype in LISTENING_TYPES:
                    ids = lessons_by_module_type.get((match["id"], ltype), [])
                    row[f"{ltype}_lesson_ids"] = "|".join(str(i) for i in ids)
        rows.append(row)
    return rows


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})
    return buf.getvalue()


def collect_mismatches(rows: list[dict[str, Any]], db_state: dict[str, Any] | None) -> dict[str, Any]:
    """Return a small dict useful for log output: counts + only_in_db rows."""
    only_in_source = [r for r in rows if r["db_match_status"] == "only_in_source"]
    matched_ids: set[int] = {
        r["db_module_id"] for r in rows if r["db_match_status"] == "matched"
    }
    only_in_db: list[dict[str, Any]] = []
    if db_state is not None:
        for m in db_state.get("modules", []):
            if m["id"] not in matched_ids:
                only_in_db.append(m)
    return {
        "matched": sum(1 for r in rows if r["db_match_status"] == "matched"),
        "only_in_source": only_in_source,
        "only_in_db": only_in_db,
    }


def _try_get_db_session():
    try:
        from app import create_app
        from app.utils.db import db
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot import Flask app: {exc}", file=sys.stderr)
        return None, None
    try:
        app = create_app()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: create_app() failed: {exc}", file=sys.stderr)
        return None, None
    return app, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export canonical curriculum module map.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Path to source module JSON directory (default: module_completed/fixed).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output CSV path (default: content/immersion/module_map.csv).",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip the DB audit. db_module_id columns will be empty and "
        "db_match_status will be 'unknown'.",
    )
    args = parser.parse_args(argv)

    source_modules = load_source_modules(args.source_dir)

    db_state: dict[str, Any] | None = None
    if not args.no_db:
        app, db_session = _try_get_db_session()
        if app is not None and db_session is not None:
            try:
                with app.app_context():
                    db_state = _query_db_state(db_session)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: DB query failed: {exc}", file=sys.stderr)
                db_state = None

    rows = build_rows(source_modules, db_state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rows_to_csv(rows), encoding="utf-8")

    mismatches = collect_mismatches(rows, db_state)
    print(f"wrote {args.output} ({len(rows)} rows)")
    if db_state is None:
        print("note: ran without DB; db_module_id columns left empty.")
    else:
        print(
            f"matched={mismatches['matched']} "
            f"only_in_source={len(mismatches['only_in_source'])} "
            f"only_in_db={len(mismatches['only_in_db'])}"
        )
        for m in mismatches["only_in_source"]:
            print(f"  only_in_source: {m['level']}/{m['file_order']} {m['source_filename']}")
        for m in mismatches["only_in_db"]:
            print(f"  only_in_db: {m['level']}/{m['number']} id={m['id']} {m.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
