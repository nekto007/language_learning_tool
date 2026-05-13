"""Audit immersion-related content & data.

Reconciles canonical source modules under `module_completed/fixed/` against the
target DB, and reports:

* lessons by type and CEFR level
* modules present only in source / only in DB
* modules missing slot-critical types: dictation, writing_prompt, shadow_reading
* existing listening lessons (listening_immersion, listening_quiz) missing audio
* vocabulary enrichment coverage (ipa, frequency_band, synonyms, antonyms,
  etymology, word_collocations, cultural_notes)
* SRS source coverage on user_card_directions

Usage:
    python scripts/audit_immersion_data.py [--format markdown|json] [--output PATH]
                                           [--source-dir DIR] [--no-db]

When --no-db is passed (or DB access fails), the report still includes
source-only sections. This is intended so the script can run on a developer
laptop without a primed DB.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SLOT_CRITICAL_TYPES = ("dictation", "writing_prompt", "shadow_reading")
NEW_LESSON_TYPES = (
    "dictation",
    "audio_fill_blank",
    "translation",
    "sentence_correction",
    "writing_prompt",
    "sentence_completion",
    "collocation_matching",
    "shadow_reading",
    "pronunciation",
    "idiom",
)
EXISTING_LISTENING_TYPES = ("listening_immersion", "listening_quiz")
CEFR_LEVELS = ("A0", "A1", "A2", "B1", "B2", "C1", "C2")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "immersion_data_audit.md"

# Filename pattern: module_<level>_<order>_<slug>.json
_FILENAME_RE = re.compile(r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$")


@dataclass
class SourceLesson:
    type: str
    title: str
    order: int | None
    raw: dict[str, Any]


@dataclass
class SourceModule:
    filename: str
    level: str
    file_order: int
    module_id: str | None
    title: str
    title_en: str
    order: int | None
    lessons: list[SourceLesson] = field(default_factory=list)

    @property
    def lesson_types(self) -> list[str]:
        return [l.type for l in self.lessons]


def load_source_modules(source_dir: Path) -> list[SourceModule]:
    """Read every module JSON under `source_dir`. Skips files that fail to
    parse and prints a warning but does not raise."""
    modules: list[SourceModule] = []
    if not source_dir.exists():
        return modules
    for path in sorted(source_dir.glob("*.json")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN: failed to parse {path.name}: {exc}", file=sys.stderr)
            continue
        module_payload = data.get("module") if isinstance(data, dict) else None
        if not isinstance(module_payload, dict):
            continue
        lessons_raw = module_payload.get("lessons") or []
        lessons = []
        for entry in lessons_raw:
            if not isinstance(entry, dict):
                continue
            lessons.append(
                SourceLesson(
                    type=str(entry.get("type") or "").strip(),
                    title=str(entry.get("title") or "").strip(),
                    order=entry.get("order") if isinstance(entry.get("order"), int) else None,
                    raw=entry,
                )
            )
        modules.append(
            SourceModule(
                filename=path.name,
                level=match.group("level"),
                file_order=int(match.group("order")),
                module_id=str(module_payload.get("id")) if module_payload.get("id") else None,
                title=str(module_payload.get("title") or "").strip(),
                title_en=str(module_payload.get("title_en") or "").strip(),
                order=module_payload.get("order") if isinstance(module_payload.get("order"), int) else None,
                lessons=lessons,
            )
        )
    return modules


def audit_source(modules: list[SourceModule]) -> dict[str, Any]:
    """Aggregate source-only metrics."""
    by_level: dict[str, int] = Counter()
    lessons_per_level_type: dict[str, dict[str, int]] = defaultdict(Counter)
    lessons_total_type: Counter = Counter()
    missing_slot: dict[str, list[dict[str, Any]]] = {t: [] for t in SLOT_CRITICAL_TYPES}
    listening_missing_audio: dict[str, list[dict[str, Any]]] = {
        t: [] for t in EXISTING_LISTENING_TYPES
    }
    for module in modules:
        by_level[module.level] += 1
        present_types = set(module.lesson_types)
        for lesson in module.lessons:
            if not lesson.type:
                continue
            lessons_per_level_type[module.level][lesson.type] += 1
            lessons_total_type[lesson.type] += 1
        for slot_type in SLOT_CRITICAL_TYPES:
            if slot_type not in present_types:
                missing_slot[slot_type].append(
                    {
                        "filename": module.filename,
                        "level": module.level,
                        "file_order": module.file_order,
                        "title": module.title,
                    }
                )
        for lesson in module.lessons:
            if lesson.type not in EXISTING_LISTENING_TYPES:
                continue
            content = lesson.raw.get("content") if isinstance(lesson.raw.get("content"), dict) else lesson.raw
            audio_url = content.get("audio_url") if isinstance(content, dict) else None
            has_item_audio = False
            if isinstance(content, dict):
                items = content.get("items") or content.get("questions") or []
                if isinstance(items, list):
                    has_item_audio = any(
                        isinstance(it, dict) and (it.get("audio_url") or it.get("audio"))
                        for it in items
                    )
            if not audio_url and not has_item_audio:
                listening_missing_audio[lesson.type].append(
                    {
                        "filename": module.filename,
                        "level": module.level,
                        "file_order": module.file_order,
                        "title": module.title,
                    }
                )
    return {
        "modules_by_level": dict(by_level),
        "modules_total": sum(by_level.values()),
        "lessons_per_level_type": {k: dict(v) for k, v in lessons_per_level_type.items()},
        "lessons_total_by_type": dict(lessons_total_type),
        "missing_slot_critical": missing_slot,
        "listening_missing_audio": listening_missing_audio,
    }


def audit_db(db_session) -> dict[str, Any]:
    """Aggregate DB-side metrics. Requires Flask app context.

    Returns a structured dict. Any DB attribute failure raises — callers
    should catch and degrade to source-only audit.
    """
    from sqlalchemy import func

    from app.curriculum.models import (
        CEFRLevel,
        CulturalNote,
        Lessons,
        Module,
        WordCollocation,
    )
    from app.study.models import UserCardDirection
    from app.words.models import CollectionWords

    session = db_session.session

    # Modules with level
    rows = (
        session.query(Module.id, Module.number, Module.title, CEFRLevel.code)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .all()
    )
    db_modules = [
        {"id": r[0], "number": r[1], "title": r[2], "level": r[3]} for r in rows
    ]
    modules_by_level: Counter = Counter(m["level"] for m in db_modules)

    # Lessons per (level, type)
    rows = (
        session.query(CEFRLevel.code, Lessons.type, func.count(Lessons.id))
        .join(Module, Module.level_id == CEFRLevel.id)
        .join(Lessons, Lessons.module_id == Module.id)
        .group_by(CEFRLevel.code, Lessons.type)
        .all()
    )
    lessons_per_level_type: dict[str, dict[str, int]] = defaultdict(dict)
    lessons_total_by_type: Counter = Counter()
    for level_code, lesson_type, count in rows:
        lessons_per_level_type[level_code][lesson_type] = count
        lessons_total_by_type[lesson_type] += count

    # Slot-critical missing per module
    missing_slot: dict[str, list[dict[str, Any]]] = {t: [] for t in SLOT_CRITICAL_TYPES}
    module_lesson_types: dict[int, set[str]] = defaultdict(set)
    for module_id, lesson_type in (
        session.query(Lessons.module_id, Lessons.type).distinct().all()
    ):
        module_lesson_types[module_id].add(lesson_type)
    for m in db_modules:
        present = module_lesson_types.get(m["id"], set())
        for slot in SLOT_CRITICAL_TYPES:
            if slot not in present:
                missing_slot[slot].append(m)

    # Existing listening lessons missing audio
    listening_missing_audio: dict[str, list[dict[str, Any]]] = {
        t: [] for t in EXISTING_LISTENING_TYPES
    }
    for lesson in (
        session.query(Lessons.id, Lessons.module_id, Lessons.title, Lessons.type, Lessons.content)
        .filter(Lessons.type.in_(EXISTING_LISTENING_TYPES))
        .all()
    ):
        content = lesson[4] if isinstance(lesson[4], dict) else {}
        audio_url = content.get("audio_url")
        has_item_audio = False
        items = content.get("items") or content.get("questions") or []
        if isinstance(items, list):
            has_item_audio = any(
                isinstance(it, dict) and (it.get("audio_url") or it.get("audio"))
                for it in items
            )
        if not audio_url and not has_item_audio:
            listening_missing_audio[lesson[3]].append(
                {"id": lesson[0], "module_id": lesson[1], "title": lesson[2]}
            )

    # Vocabulary enrichment coverage
    total_words = session.query(func.count(CollectionWords.id)).scalar() or 0
    vocab_coverage = {
        "total_words": total_words,
        "ipa_transcription": session.query(func.count(CollectionWords.id))
        .filter(CollectionWords.ipa_transcription.isnot(None))
        .filter(func.length(func.coalesce(CollectionWords.ipa_transcription, "")) > 0)
        .scalar()
        or 0,
        "frequency_band": session.query(func.count(CollectionWords.id))
        .filter(CollectionWords.frequency_band.isnot(None))
        .scalar()
        or 0,
        "synonyms": session.query(func.count(CollectionWords.id))
        .filter(CollectionWords.synonyms.isnot(None))
        .scalar()
        or 0,
        "antonyms": session.query(func.count(CollectionWords.id))
        .filter(CollectionWords.antonyms.isnot(None))
        .scalar()
        or 0,
        "etymology": session.query(func.count(CollectionWords.id))
        .filter(CollectionWords.etymology.isnot(None))
        .filter(func.length(func.coalesce(CollectionWords.etymology, "")) > 0)
        .scalar()
        or 0,
        "word_collocations_rows": session.query(func.count(WordCollocation.id)).scalar()
        or 0,
        "cultural_notes_rows": session.query(func.count(CulturalNote.id)).scalar() or 0,
    }

    # SRS source coverage
    total_card_dirs = session.query(func.count(UserCardDirection.id)).scalar() or 0
    source_breakdown_rows = (
        session.query(UserCardDirection.source, func.count(UserCardDirection.id))
        .group_by(UserCardDirection.source)
        .all()
    )
    srs_source = {
        "total_card_directions": total_card_dirs,
        "with_source": sum(
            count for src, count in source_breakdown_rows if src is not None and src != ""
        ),
        "without_source": sum(
            count for src, count in source_breakdown_rows if src is None or src == ""
        ),
        "breakdown": {str(src) if src is not None else "null": count for src, count in source_breakdown_rows},
    }

    return {
        "modules_by_level": dict(modules_by_level),
        "modules_total": sum(modules_by_level.values()),
        "db_modules": db_modules,
        "lessons_per_level_type": {k: dict(v) for k, v in lessons_per_level_type.items()},
        "lessons_total_by_type": dict(lessons_total_by_type),
        "missing_slot_critical": missing_slot,
        "listening_missing_audio": listening_missing_audio,
        "vocab_coverage": vocab_coverage,
        "srs_source": srs_source,
    }


def reconcile_source_vs_db(
    source_modules: list[SourceModule], db_modules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Match source files with DB modules by (level, file_order) and (level, title).

    A heuristic match is used because source `module.number` is often None.
    `file_order` from the filename is the most reliable canonical ordinal."""
    db_by_level_order: dict[tuple[str, int], dict[str, Any]] = {}
    db_by_level_title: dict[tuple[str, str], dict[str, Any]] = {}
    for m in db_modules:
        if m.get("number") is not None:
            db_by_level_order[(m["level"], int(m["number"]))] = m
        if m.get("title"):
            db_by_level_title[(m["level"], m["title"].strip())] = m

    matched: list[dict[str, Any]] = []
    only_in_source: list[dict[str, Any]] = []
    matched_db_ids: set[int] = set()
    for s in source_modules:
        match = db_by_level_order.get((s.level, s.file_order))
        if match is None:
            match = db_by_level_title.get((s.level, s.title))
        if match is None:
            only_in_source.append(
                {
                    "filename": s.filename,
                    "level": s.level,
                    "file_order": s.file_order,
                    "title": s.title,
                }
            )
        else:
            matched_db_ids.add(match["id"])
            matched.append(
                {
                    "filename": s.filename,
                    "level": s.level,
                    "file_order": s.file_order,
                    "source_title": s.title,
                    "db_id": match["id"],
                    "db_title": match.get("title"),
                    "db_number": match.get("number"),
                }
            )
    only_in_db = [m for m in db_modules if m["id"] not in matched_db_ids]
    return {
        "matched_count": len(matched),
        "matched": matched,
        "only_in_source": only_in_source,
        "only_in_db": only_in_db,
    }


def build_audit(source_dir: Path, db_session=None) -> dict[str, Any]:
    source_modules = load_source_modules(source_dir)
    source_summary = audit_source(source_modules)
    audit: dict[str, Any] = {
        "source_dir": str(source_dir),
        "source": source_summary,
        "new_lesson_types": list(NEW_LESSON_TYPES),
        "slot_critical_types": list(SLOT_CRITICAL_TYPES),
    }
    if db_session is not None:
        try:
            db_summary = audit_db(db_session)
            audit["db"] = db_summary
            audit["reconciliation"] = reconcile_source_vs_db(
                source_modules, db_summary.get("db_modules", [])
            )
        except Exception as exc:  # noqa: BLE001 — surface DB issues in report
            audit["db_error"] = f"{type(exc).__name__}: {exc}"
    return audit


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join(str(v) for v in row) + " |\n"
    return out


def format_markdown(audit: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("# Immersion Data Audit\n")
    out.append(f"_Source directory_: `{audit['source_dir']}`\n")

    src = audit["source"]
    out.append("## Source Modules (module_completed/fixed)\n")
    out.append(f"- Total source modules: **{src['modules_total']}**\n")
    out.append("- By CEFR level: " + ", ".join(f"{k}={v}" for k, v in sorted(src["modules_by_level"].items())) + "\n")

    out.append("\n## Lessons per CEFR Level × Type (source)\n")
    levels = sorted(src["lessons_per_level_type"].keys())
    types = sorted({t for lt in src["lessons_per_level_type"].values() for t in lt})
    rows = []
    for level in levels:
        row: list[Any] = [level]
        for t in types:
            row.append(src["lessons_per_level_type"].get(level, {}).get(t, 0))
        rows.append(row)
    out.append(_md_table(["level", *types], rows))

    out.append("\n## Source Lessons Total per Type\n")
    out.append(
        _md_table(
            ["lesson_type", "count"],
            sorted(src["lessons_total_by_type"].items(), key=lambda kv: kv[0]),
        )
    )

    out.append("\n## Source Modules Missing Slot-Critical Lesson Types\n")
    for slot in SLOT_CRITICAL_TYPES:
        missing = src["missing_slot_critical"][slot]
        out.append(f"### `{slot}` — missing in {len(missing)} module(s)\n")
        if missing:
            out.append(
                _md_table(
                    ["level", "file_order", "filename", "title"],
                    [[m["level"], m["file_order"], m["filename"], m["title"]] for m in missing],
                )
            )

    out.append("\n## Existing Listening Lessons Missing Audio (source)\n")
    for ltype in EXISTING_LISTENING_TYPES:
        rows = src["listening_missing_audio"][ltype]
        out.append(f"### `{ltype}` — {len(rows)} missing audio\n")
        if rows:
            out.append(
                _md_table(
                    ["level", "file_order", "filename", "title"],
                    [[r["level"], r["file_order"], r["filename"], r["title"]] for r in rows[:25]],
                )
            )
            if len(rows) > 25:
                out.append(f"_…and {len(rows) - 25} more_\n")

    if "db_error" in audit:
        out.append("\n## DB Audit\n")
        out.append(f"_DB audit skipped: {audit['db_error']}_\n")
    elif "db" in audit:
        db = audit["db"]
        out.append("\n## DB Modules\n")
        out.append(f"- Total DB modules: **{db['modules_total']}**\n")
        out.append(
            "- By CEFR level: "
            + ", ".join(f"{k}={v}" for k, v in sorted(db["modules_by_level"].items()))
            + "\n"
        )

        out.append("\n## DB Lessons per Level × Type\n")
        levels = sorted(db["lessons_per_level_type"].keys())
        types = sorted({t for lt in db["lessons_per_level_type"].values() for t in lt})
        rows = []
        for level in levels:
            row = [level]
            for t in types:
                row.append(db["lessons_per_level_type"].get(level, {}).get(t, 0))
            rows.append(row)
        out.append(_md_table(["level", *types], rows))

        out.append("\n## DB Lessons Total per Type (incl. zero for new types)\n")
        type_totals = dict(db["lessons_total_by_type"])
        rows = []
        for t in sorted(set(list(type_totals.keys()) + list(NEW_LESSON_TYPES))):
            rows.append([t, type_totals.get(t, 0)])
        out.append(_md_table(["lesson_type", "count"], rows))

        out.append("\n## DB Modules Missing Slot-Critical Lesson Types\n")
        for slot in SLOT_CRITICAL_TYPES:
            missing = db["missing_slot_critical"][slot]
            out.append(f"### `{slot}` — missing in {len(missing)} DB module(s)\n")
            if missing:
                out.append(
                    _md_table(
                        ["level", "number", "id", "title"],
                        [[m["level"], m["number"], m["id"], m["title"]] for m in missing[:80]],
                    )
                )
                if len(missing) > 80:
                    out.append(f"_…and {len(missing) - 80} more_\n")

        out.append("\n## DB Existing Listening Lessons Missing Audio\n")
        for ltype in EXISTING_LISTENING_TYPES:
            rows = db["listening_missing_audio"][ltype]
            out.append(f"### `{ltype}` — {len(rows)} DB lessons missing audio\n")
            if rows:
                out.append(
                    _md_table(
                        ["id", "module_id", "title"],
                        [[r["id"], r["module_id"], r["title"]] for r in rows[:25]],
                    )
                )

        vc = db["vocab_coverage"]
        total = vc["total_words"] or 1
        out.append("\n## Vocabulary Enrichment Coverage\n")
        out.append(f"- Total words: **{vc['total_words']}**\n")
        rows = []
        for k in (
            "ipa_transcription",
            "frequency_band",
            "synonyms",
            "antonyms",
            "etymology",
        ):
            filled = vc[k]
            rows.append([k, filled, f"{(filled / total) * 100:.2f}%"])
        rows.append(["word_collocations (rows)", vc["word_collocations_rows"], "—"])
        rows.append(["cultural_notes (rows)", vc["cultural_notes_rows"], "—"])
        out.append(_md_table(["field", "filled / rows", "coverage"], rows))

        srs = db["srs_source"]
        out.append("\n## SRS Card-Direction Source Tagging\n")
        out.append(
            f"- Total `user_card_directions`: **{srs['total_card_directions']}** "
            f"(with source: {srs['with_source']}, without: {srs['without_source']})\n"
        )
        if srs["breakdown"]:
            out.append(
                _md_table(
                    ["source", "count"],
                    sorted(srs["breakdown"].items(), key=lambda kv: -kv[1]),
                )
            )

        rec = audit.get("reconciliation", {})
        out.append("\n## Source ↔ DB Module Reconciliation\n")
        out.append(
            f"- Matched: **{rec.get('matched_count', 0)}** | "
            f"Only in source: **{len(rec.get('only_in_source', []))}** | "
            f"Only in DB: **{len(rec.get('only_in_db', []))}**\n"
        )
        if rec.get("only_in_source"):
            out.append("\n### Source modules missing from DB\n")
            out.append(
                _md_table(
                    ["level", "file_order", "filename", "title"],
                    [
                        [m["level"], m["file_order"], m["filename"], m["title"]]
                        for m in rec["only_in_source"]
                    ],
                )
            )
        if rec.get("only_in_db"):
            out.append("\n### DB modules with no matching source file\n")
            out.append(
                _md_table(
                    ["level", "number", "id", "title"],
                    [
                        [m["level"], m["number"], m["id"], m.get("title")]
                        for m in rec["only_in_db"]
                    ],
                )
            )
    return "".join(out)


def format_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=True)


def _try_get_db_session():
    """Try to import the Flask app and return (app, db). Returns (None, None) on failure."""
    try:
        from app import create_app
        from extensions import db
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot import Flask app: {exc}", file=sys.stderr)
        return None, None
    try:
        app = create_app(os.environ.get("FLASK_ENV", "development"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: create_app() failed: {exc}", file=sys.stderr)
        return None, None
    return app, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit immersion data state.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Path to source module JSON directory (default: module_completed/fixed)",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path. Defaults to reports/immersion_data_audit.md (or .json).",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB audit even if the app is importable.",
    )
    args = parser.parse_args(argv)

    db_session = None
    app = None
    if not args.no_db:
        app, db_session = _try_get_db_session()

    if app is not None and db_session is not None:
        with app.app_context():
            audit = build_audit(args.source_dir, db_session=db_session)
    else:
        audit = build_audit(args.source_dir, db_session=None)
        if not args.no_db and "db_error" not in audit:
            audit["db_error"] = "Flask app could not be initialized (see warnings)."

    if args.format == "markdown":
        text = format_markdown(audit)
        default_out = DEFAULT_REPORT_PATH
    else:
        text = format_json(audit)
        default_out = DEFAULT_REPORT_PATH.with_suffix(".json")

    out_path = args.output or default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())