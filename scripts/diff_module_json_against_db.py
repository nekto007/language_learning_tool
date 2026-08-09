"""Compare `module_completed/fixed/*.json` against the curriculum lessons in a
running database, using stable lesson identity.

This is the Task 7 verification tool: before any production import we must know
whether the JSON-to-DB upsert (see `app/admin/services/curriculum_import_service.py`)
will create new lessons, leave DB-only lessons orphaned, or silently mutate an
existing DB lesson's content because the new JSON happens to land on the same
`(module_id, number)`.

Identity resolution order (per lesson):

1. `content.external_key` — primary stable identity. Inserted new-style lessons
   are required to carry one (see Task 2 contract).
2. `(level, module_number, type, normalized_title)` — fallback for legacy
   lessons that pre-date `external_key`.

The script never writes to DB. It emits a structured Markdown report plus an
optional JSON dump and exits non-zero in `--strict` mode if any module has
position collisions or DB-only lessons that aren't explicitly deferred.

Usage:

    python scripts/diff_module_json_against_db.py
    python scripts/diff_module_json_against_db.py --output reports/...
    python scripts/diff_module_json_against_db.py --strict --format markdown
    python scripts/diff_module_json_against_db.py --no-db        # skips DB

Output:
    - `reports/module_completed_json_db_diff.md`  (markdown, default)
    - or `--output PATH --format json`            (JSON dump)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_module_completed_json_gaps import (  # noqa: E402
    SourceLesson,
    SourceModule,
    load_source_modules,
)

DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "module_completed_json_db_diff.md"

# JSON `flashcards` lesson type maps to DB `card`.
TYPE_TO_DB_TYPE: dict[str, str] = {"flashcards": "card"}


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title or "").strip().casefold()


def _src_type_to_db(lesson_type: str) -> str:
    return TYPE_TO_DB_TYPE.get(lesson_type, lesson_type)


def _src_external_key(lesson: SourceLesson) -> str | None:
    key = lesson.content.get("external_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def _db_external_key(content: Any) -> str | None:
    if isinstance(content, dict):
        key = content.get("external_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return None


def _identity_fallback(lesson_type: str, title: str) -> tuple[str, str]:
    return (_src_type_to_db(lesson_type), _normalize_title(title))


def _load_db_curriculum(db_session) -> dict[tuple[str, int], dict[str, Any]]:
    """Return a mapping `(level_code, module_number) -> module_payload`.

    `db_session` may be either a Flask-SQLAlchemy `db` object (has a `.session`
    attribute) or a session-like object that exposes `.query()` directly.
    """
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

    session = getattr(db_session, "session", db_session)

    module_rows = (
        session.query(
            Module.id,
            Module.number,
            Module.title,
            CEFRLevel.code,
        )
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .all()
    )
    if not module_rows:
        return {}

    module_payload: dict[tuple[str, int], dict[str, Any]] = {}
    module_ids: list[int] = []
    for row in module_rows:
        module_id, number, title, level_code = row
        if number is None:
            continue
        key = (level_code, int(number))
        module_payload[key] = {
            "module_id": module_id,
            "number": int(number),
            "title": title,
            "level": level_code,
            "lessons": [],
        }
        module_ids.append(module_id)

    if not module_ids:
        return module_payload

    lesson_rows = (
        session.query(Lessons.id, Lessons.module_id, Lessons.number,
                      Lessons.type, Lessons.title, Lessons.content)
        .filter(Lessons.module_id.in_(module_ids))
        .order_by(Lessons.module_id, Lessons.number, Lessons.id)
        .all()
    )

    lesson_ids = [row[0] for row in lesson_rows]
    progress_counts: dict[int, int] = {}
    if lesson_ids:
        from sqlalchemy import func as sa_func
        rows = (
            session.query(LessonProgress.lesson_id, sa_func.count(LessonProgress.id))
            .filter(LessonProgress.lesson_id.in_(lesson_ids))
            .group_by(LessonProgress.lesson_id)
            .all()
        )
        progress_counts = {lid: int(n) for lid, n in rows}

    by_module: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for lid, mid, number, ltype, title, content in lesson_rows:
        by_module[mid].append(
            {
                "id": lid,
                "module_id": mid,
                "number": int(number) if number is not None else None,
                "type": ltype or "",
                "title": title or "",
                "external_key": _db_external_key(content),
                "progress_rows": progress_counts.get(lid, 0),
            }
        )

    for payload in module_payload.values():
        payload["lessons"] = by_module.get(payload["module_id"], [])

    return module_payload


def _build_db_indexes(
    db_lessons: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[int, dict[str, Any]],
]:
    """Index DB lessons three ways for fast lookup.

    Returns `(by_external_key, by_fallback, by_number)`.
    """
    by_external_key: dict[str, dict[str, Any]] = {}
    by_fallback: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_number: dict[int, dict[str, Any]] = {}
    for entry in db_lessons:
        if entry["external_key"]:
            by_external_key[entry["external_key"]] = entry
        by_fallback[(entry["type"], _normalize_title(entry["title"]))].append(entry)
        if entry["number"] is not None and entry["number"] not in by_number:
            by_number[entry["number"]] = entry
    return by_external_key, by_fallback, by_number


def _diff_module(
    module: SourceModule,
    db_module: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the diff record for a single source module."""
    base = {
        "filename": module.filename,
        "level": module.level,
        "module_number": module.file_order,
        "module_title": module.title,
        "db_matched": db_module is not None,
        "db_module_id": db_module["module_id"] if db_module else None,
        "lesson_count_source": len(module.lessons),
        "lesson_count_db": len(db_module["lessons"]) if db_module else 0,
        "matched_by_external_key": [],
        "matched_by_fallback": [],
        "json_only": [],
        "db_only": [],
        "position_collisions": [],
        "ambiguous_fallback": [],
    }

    if db_module is None:
        # Whole module is JSON-only; every lesson would be created.
        for idx, lesson in enumerate(module.lessons, start=1):
            base["json_only"].append(
                {
                    "src_position": idx,
                    "type": lesson.type,
                    "title": lesson.title,
                    "external_key": _src_external_key(lesson),
                }
            )
        return base

    db_lessons = db_module["lessons"]
    by_ext, by_fallback, by_number = _build_db_indexes(db_lessons)
    matched_db_ids: set[int] = set()

    # Source-side identity match first.
    for idx, lesson in enumerate(module.lessons, start=1):
        ext_key = _src_external_key(lesson)
        if ext_key and ext_key in by_ext:
            db_entry = by_ext[ext_key]
            matched_db_ids.add(db_entry["id"])
            base["matched_by_external_key"].append(
                {
                    "src_position": idx,
                    "src_number": lesson.number,
                    "src_title": lesson.title,
                    "src_type": lesson.type,
                    "external_key": ext_key,
                    "db_lesson_id": db_entry["id"],
                    "db_number": db_entry["number"],
                    "db_title": db_entry["title"],
                    "db_type": db_entry["type"],
                    "progress_rows": db_entry["progress_rows"],
                    "position_changed": db_entry["number"] != idx,
                }
            )
            continue
        # Fallback: type + normalized title in this module.
        fkey = _identity_fallback(lesson.type, lesson.title)
        candidates = [c for c in by_fallback.get(fkey, []) if c["id"] not in matched_db_ids]
        if len(candidates) == 1:
            db_entry = candidates[0]
            matched_db_ids.add(db_entry["id"])
            base["matched_by_fallback"].append(
                {
                    "src_position": idx,
                    "src_number": lesson.number,
                    "src_title": lesson.title,
                    "src_type": lesson.type,
                    "db_lesson_id": db_entry["id"],
                    "db_number": db_entry["number"],
                    "db_title": db_entry["title"],
                    "db_type": db_entry["type"],
                    "progress_rows": db_entry["progress_rows"],
                    "position_changed": db_entry["number"] != idx,
                    "reason": "external_key missing on source — matched by (type, title)",
                }
            )
            continue
        if len(candidates) > 1:
            base["ambiguous_fallback"].append(
                {
                    "src_position": idx,
                    "src_title": lesson.title,
                    "src_type": lesson.type,
                    "candidate_db_ids": [c["id"] for c in candidates],
                }
            )
            # Claim every candidate so it does not also surface as db_only.
            for c in candidates:
                matched_db_ids.add(c["id"])
            continue
        # JSON-only: source lesson not present in DB.
        base["json_only"].append(
            {
                "src_position": idx,
                "type": lesson.type,
                "title": lesson.title,
                "external_key": ext_key,
            }
        )

    # DB-only: existing DB lessons not matched by any source lesson.
    for entry in db_lessons:
        if entry["id"] in matched_db_ids:
            continue
        base["db_only"].append(
            {
                "db_lesson_id": entry["id"],
                "db_number": entry["number"],
                "type": entry["type"],
                "title": entry["title"],
                "external_key": entry["external_key"],
                "progress_rows": entry["progress_rows"],
            }
        )

    # Position collisions: importer looks up by `(module_id, number)`. If a
    # source lesson at position N has external_key X, and the DB already has a
    # DIFFERENT lesson at number=N, importing this JSON would overwrite that
    # lesson's content even though they are logically different.
    for idx, lesson in enumerate(module.lessons, start=1):
        existing_at_pos = by_number.get(idx)
        if existing_at_pos is None:
            continue
        ext_key = _src_external_key(lesson)
        # Determine whether the lesson at this position will be overwritten by
        # something with a different identity.
        if ext_key and existing_at_pos["external_key"]:
            if ext_key == existing_at_pos["external_key"]:
                continue  # Same identity — safe in-place update.
            base["position_collisions"].append(
                {
                    "src_position": idx,
                    "src_external_key": ext_key,
                    "src_title": lesson.title,
                    "src_type": lesson.type,
                    "db_lesson_id_at_position": existing_at_pos["id"],
                    "db_external_key_at_position": existing_at_pos["external_key"],
                    "db_title_at_position": existing_at_pos["title"],
                    "db_type_at_position": existing_at_pos["type"],
                    "progress_rows": existing_at_pos["progress_rows"],
                    "reason": "different external_key at same (module_id, number)",
                }
            )
            continue
        # Fallback signature comparison (legacy DB lessons with no ext_key).
        src_sig = _identity_fallback(lesson.type, lesson.title)
        db_sig = (existing_at_pos["type"], _normalize_title(existing_at_pos["title"]))
        if src_sig != db_sig:
            base["position_collisions"].append(
                {
                    "src_position": idx,
                    "src_external_key": ext_key,
                    "src_title": lesson.title,
                    "src_type": lesson.type,
                    "db_lesson_id_at_position": existing_at_pos["id"],
                    "db_external_key_at_position": existing_at_pos["external_key"],
                    "db_title_at_position": existing_at_pos["title"],
                    "db_type_at_position": existing_at_pos["type"],
                    "progress_rows": existing_at_pos["progress_rows"],
                    "reason": (
                        "type/title mismatch at same (module_id, number); "
                        "DB lesson has no external_key to disambiguate"
                    ),
                }
            )

    return base


def build_diff(
    source_dir: Path,
    db_session,
) -> dict[str, Any]:
    """Top-level entry point. Returns the full diff payload."""
    source_modules = load_source_modules(source_dir)
    db_curriculum = _load_db_curriculum(db_session) if db_session is not None else {}

    diffs: list[dict[str, Any]] = []
    matched_db_module_keys: set[tuple[str, int]] = set()
    for module in source_modules:
        key = (module.level, module.file_order)
        db_module = db_curriculum.get(key)
        if db_module is not None:
            matched_db_module_keys.add(key)
        diffs.append(_diff_module(module, db_module))

    db_only_modules: list[dict[str, Any]] = []
    for key, payload in db_curriculum.items():
        if key in matched_db_module_keys:
            continue
        db_only_modules.append(
            {
                "level": key[0],
                "module_number": key[1],
                "db_module_id": payload["module_id"],
                "db_title": payload["title"],
                "lesson_count": len(payload["lessons"]),
            }
        )

    totals = _compute_totals(diffs, db_only_modules)
    return {
        "source_dir": str(source_dir),
        "db_available": db_session is not None,
        "modules": diffs,
        "db_only_modules": db_only_modules,
        "totals": totals,
    }


def _compute_totals(
    diffs: list[dict[str, Any]],
    db_only_modules: list[dict[str, Any]],
) -> dict[str, Any]:
    matched_ext = sum(len(d["matched_by_external_key"]) for d in diffs)
    matched_fallback = sum(len(d["matched_by_fallback"]) for d in diffs)
    json_only = sum(len(d["json_only"]) for d in diffs)
    db_only_lessons = sum(len(d["db_only"]) for d in diffs)
    position_collisions = sum(len(d["position_collisions"]) for d in diffs)
    ambiguous = sum(len(d["ambiguous_fallback"]) for d in diffs)
    collisions_with_progress = 0
    for d in diffs:
        for collision in d["position_collisions"]:
            if collision.get("progress_rows", 0) > 0:
                collisions_with_progress += 1
    return {
        "modules_in_source": len(diffs),
        "modules_db_only": len(db_only_modules),
        "modules_source_only": sum(1 for d in diffs if not d["db_matched"]),
        "lessons_matched_by_external_key": matched_ext,
        "lessons_matched_by_fallback": matched_fallback,
        "lessons_json_only": json_only,
        "lessons_db_only": db_only_lessons,
        "position_collisions": position_collisions,
        "position_collisions_with_progress": collisions_with_progress,
        "ambiguous_fallback_matches": ambiguous,
    }


def has_blocking_issues(diff: dict[str, Any]) -> bool:
    """Return True when the diff contains anything that should block import."""
    totals = diff["totals"]
    if totals["position_collisions"] > 0:
        return True
    if totals["lessons_db_only"] > 0:
        return True
    if totals["modules_db_only"] > 0:
        return True
    if totals["ambiguous_fallback_matches"] > 0:
        return True
    return False


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join("" if v is None else str(v) for v in row) + " |\n"
    return out


def format_markdown(diff: dict[str, Any]) -> str:
    totals = diff["totals"]
    out: list[str] = []
    out.append("# module_completed/fixed JSON ↔ DB diff\n\n")
    out.append(f"_Source directory_: `{diff['source_dir']}`\n")
    out.append(f"_DB available_: {'yes' if diff['db_available'] else 'no'}\n\n")

    out.append("## Summary\n\n")
    rows = [
        ["modules in source", totals["modules_in_source"]],
        ["modules with DB counterpart", totals["modules_in_source"] - totals["modules_source_only"]],
        ["modules in source but not DB", totals["modules_source_only"]],
        ["modules in DB but not source", totals["modules_db_only"]],
        ["lessons matched by `external_key`", totals["lessons_matched_by_external_key"]],
        ["lessons matched by `(type, title)` fallback", totals["lessons_matched_by_fallback"]],
        ["lessons present in JSON only (would be inserted)", totals["lessons_json_only"]],
        ["lessons present in DB only", totals["lessons_db_only"]],
        ["position collisions (silent-overwrite risk)", totals["position_collisions"]],
        ["position collisions with user progress", totals["position_collisions_with_progress"]],
        ["ambiguous fallback matches", totals["ambiguous_fallback_matches"]],
    ]
    out.append(_md_table(["metric", "count"], rows))
    out.append("\n")

    if not diff["db_available"]:
        out.append(
            "> **DB was not available when this report was generated.** All "
            "lessons appear as `json_only`. Re-run with the Flask app pointed at "
            "a populated database to get the real diff.\n\n"
        )

    out.append("## Per-module diff\n\n")
    for module in diff["modules"]:
        status_bits: list[str] = []
        if module["position_collisions"]:
            status_bits.append(f"⚠ {len(module['position_collisions'])} collision(s)")
        if module["db_only"]:
            status_bits.append(f"{len(module['db_only'])} DB-only")
        if module["json_only"]:
            status_bits.append(f"{len(module['json_only'])} JSON-only")
        if module["ambiguous_fallback"]:
            status_bits.append(f"{len(module['ambiguous_fallback'])} ambiguous")
        status = "; ".join(status_bits) or "clean"
        out.append(
            f"### `{module['filename']}` — {module['level']} module {module['module_number']}\n"
        )
        out.append(
            f"- DB matched: {'yes' if module['db_matched'] else 'no'}; "
            f"source lessons: {module['lesson_count_source']}; "
            f"DB lessons: {module['lesson_count_db']}; "
            f"status: {status}\n"
        )
        if module["position_collisions"]:
            out.append("\n**Position collisions** (importer would overwrite "
                       "an existing DB lesson's content):\n\n")
            rows = []
            for c in module["position_collisions"]:
                rows.append(
                    [
                        c["src_position"],
                        c.get("src_external_key") or "—",
                        f"{c['src_type']} / {c['src_title']}",
                        c["db_lesson_id_at_position"],
                        c.get("db_external_key_at_position") or "—",
                        f"{c['db_type_at_position']} / {c['db_title_at_position']}",
                        c["progress_rows"],
                        c["reason"],
                    ]
                )
            out.append(
                _md_table(
                    [
                        "pos",
                        "src external_key",
                        "src (type/title)",
                        "db_id",
                        "db external_key",
                        "db (type/title)",
                        "progress",
                        "reason",
                    ],
                    rows,
                )
            )
        if module["db_only"]:
            out.append("\n**DB-only lessons** (would not be touched, but no longer in source):\n\n")
            rows = []
            for entry in module["db_only"]:
                rows.append(
                    [
                        entry["db_lesson_id"],
                        entry["db_number"],
                        entry["type"],
                        entry["title"],
                        entry["external_key"] or "—",
                        entry["progress_rows"],
                    ]
                )
            out.append(
                _md_table(
                    ["db_id", "db number", "type", "title", "external_key", "progress"],
                    rows,
                )
            )
        if module["json_only"]:
            out.append("\n**JSON-only lessons** (would be created on import):\n\n")
            rows = []
            for entry in module["json_only"]:
                rows.append(
                    [
                        entry["src_position"],
                        entry["type"],
                        entry["title"],
                        entry["external_key"] or "—",
                    ]
                )
            out.append(_md_table(["pos", "type", "title", "external_key"], rows))
        if module["ambiguous_fallback"]:
            out.append("\n**Ambiguous fallback matches** (multiple DB lessons "
                       "share the same `(type, title)`):\n\n")
            rows = []
            for entry in module["ambiguous_fallback"]:
                rows.append(
                    [
                        entry["src_position"],
                        entry["src_type"],
                        entry["src_title"],
                        ", ".join(str(i) for i in entry["candidate_db_ids"]),
                    ]
                )
            out.append(_md_table(["pos", "type", "title", "db_ids"], rows))
        out.append("\n")

    if diff["db_only_modules"]:
        out.append("## DB modules with no source file\n\n")
        rows = []
        for entry in diff["db_only_modules"]:
            rows.append(
                [
                    entry["level"],
                    entry["module_number"],
                    entry["db_module_id"],
                    entry["db_title"],
                    entry["lesson_count"],
                ]
            )
        out.append(
            _md_table(["level", "module_number", "db_module_id", "title", "lessons"], rows)
        )
        out.append("\n")

    out.append("## Import behavior contract\n\n")
    out.append(
        "1. **Current importer keys lessons by `(module_id, number)`.**\n"
        "   `CurriculumImportService.import_curriculum_data` resolves the\n"
        "   target row via\n"
        "   `Lessons.query.filter_by(module_id=module.id, number=number)` and\n"
        "   does not consult `content.external_key`. Source JSON still carries\n"
        "   `external_key` and this diff tool uses it for identity reporting,\n"
        "   but operators must treat any non-trivial position change as a\n"
        "   potential silent overwrite until the importer is upgraded to\n"
        "   prefer `external_key` (tracked separately).\n"
        "2. **Position collisions block import.** A collision means the source\n"
        "   lesson at position N has a different identity than the DB row\n"
        "   currently at `(module_id, number=N)`. Because the importer keys by\n"
        "   number, applying such a file would copy the source content onto\n"
        "   the wrong DB row; resolve collisions before applying.\n"
        "3. **Position changes also need manual review.** When `position_changed`\n"
        "   is true for a `matched_by_external_key` (or `matched_by_fallback`)\n"
        "   row, the importer will write the source content to the *new*\n"
        "   `(module_id, number)` slot — not to the row whose identity matched.\n"
        "   Reconcile the DB ordering (e.g. via `sync_source_module_with_db.py`\n"
        "   against a fresh DB pull) before importing.\n"
        "4. **DB-only lessons are never deleted by the importer.** They are\n"
        "   listed here so that an explicit decision can be made: either keep\n"
        "   them (legacy content, still useful) or remove them manually.\n"
        "5. **User progress (`lesson_progress`) follows the DB lesson id.** A\n"
        "   silent overwrite from a number-based collision does not move\n"
        "   progress rows but does change the lesson content under them. The\n"
        "   `progress` column counts rows at risk if a collision is applied.\n"
        "6. **`number` and `order` are presentation/ordering only on the JSON\n"
        "   side.** `sync_source_module_with_db.py` renumbers them 1..N from\n"
        "   the array position. Because the importer currently keys by number,\n"
        "   that renumbering can change which DB row receives the update — do\n"
        "   not rely on it for identity-preserving updates.\n\n"
    )

    out.append("## Recommended command sequence\n\n")
    out.append(
        "Staging dry-run:\n\n"
        "```bash\n"
        "python scripts/validate_module_completed_json.py --strict\n"
        "python scripts/diff_module_json_against_db.py --strict\n"
        "```\n\n"
        "Staging apply (after both reports are clean):\n\n"
        "```bash\n"
        "# admin curriculum import endpoint upserts one module file at a time\n"
        "for f in module_completed/fixed/module_*.json; do\n"
        "    curl -sS -X POST -H 'Content-Type: application/json' \\\n"
        "        --data-binary @\"$f\" \\\n"
        "        \"$STAGING_URL/admin/curriculum/import\"\n"
        "done\n"
        "python scripts/diff_module_json_against_db.py --strict \\\n"
        "    --output reports/module_completed_json_db_diff.staging.md\n"
        "```\n\n"
        "Production apply: identical sequence against `$PROD_URL` after the\n"
        "`reports/module_completed_audio_manifest.md` assets have been copied.\n"
    )

    return "".join(out)


def format_json(diff: dict[str, Any]) -> str:
    return json.dumps(diff, indent=2, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _try_get_db_session():
    # `create_app` takes a config *object*, not a name: passing "development" made
    # `app.config.from_object` do `import_string("development")` and blow up. And the
    # app binds `app.utils.db.db`, not the root `extensions.db` — importing the latter
    # yielded a SQLAlchemy instance the app was never registered with. See CNT-013.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
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
    parser = argparse.ArgumentParser(
        description="Diff source JSON modules against curriculum lessons in DB."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--no-db", action="store_true",
        help="Skip DB lookup; useful when only the source-side audit is wanted."
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 when the report contains blocking issues "
             "(position collisions, ambiguous matches, db-only lessons/modules).",
    )
    args = parser.parse_args(argv)

    if args.no_db:
        diff = build_diff(args.source_dir, None)
    else:
        app, db = _try_get_db_session()
        if app is None or db is None:
            print(
                "ERROR: could not connect to DB. Use --no-db to run a "
                "source-only diff (every source lesson will be reported as "
                "json_only).",
                file=sys.stderr,
            )
            return 2
        with app.app_context():
            diff = build_diff(args.source_dir, db)

    if args.format == "markdown":
        text = format_markdown(diff)
        default_out = DEFAULT_REPORT_PATH
    else:
        text = format_json(diff)
        default_out = DEFAULT_REPORT_PATH.with_suffix(".json")

    out_path = args.output or default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")

    if args.strict and has_blocking_issues(diff):
        print(
            "ERROR: blocking issues detected — see "
            f"{out_path} (--strict).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
