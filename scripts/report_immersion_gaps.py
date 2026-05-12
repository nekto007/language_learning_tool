"""Report immersion content gaps.

Builds a focused gap-only report that consumes the audit primitives in
`scripts/audit_immersion_data.py` and surfaces:

* Missing slot-critical lesson types per source module
  (`dictation`, `writing_prompt`, `shadow_reading`).
* Source/DB module mismatches against `module_completed/fixed/` — modules
  present in source but missing in DB, and vice versa.
* Missing CEFR coverage per new lesson type (each CEFR level should hold
  at least one lesson of every new type).
* Audio metadata gaps in source listening lessons.
* Vocabulary enrichment gaps (IPA, frequency_band, synonyms, antonyms,
  etymology, collocations, cultural notes).
* SRS source tagging gaps on `user_card_directions`.

The script intentionally re-uses `build_audit` so it stays aligned with
the canonical audit. It is safe to run without a primed DB — DB-only
sections are skipped and called out in the report.

Usage:
    python scripts/report_immersion_gaps.py [--format markdown|json]
                                            [--output PATH]
                                            [--source-dir DIR]
                                            [--no-db]
                                            [--min-coverage-per-level N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_immersion_data import (  # noqa: E402
    CEFR_LEVELS,
    EXISTING_LISTENING_TYPES,
    NEW_LESSON_TYPES,
    SLOT_CRITICAL_TYPES,
    build_audit,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "immersion_gap_report.md"


def _cefr_levels_present(audit: dict[str, Any]) -> list[str]:
    """Return the CEFR levels that have at least one source module.

    Falls back to a fixed `(A1, A2, B1, B2, C1)` list when the audit
    has no source rows yet, since `module_completed/fixed/` is the
    canonical scope of this plan.
    """
    levels = sorted((audit.get("source", {}).get("modules_by_level") or {}).keys())
    return levels or ["A1", "A2", "B1", "B2", "C1"]


def build_gap_report(
    source_dir: Path,
    db_session=None,
    min_coverage_per_level: int = 1,
) -> dict[str, Any]:
    """Distill audit data into gap-only structure.

    `min_coverage_per_level` controls the threshold for the new-lesson-type
    coverage matrix (default 1 — each CEFR level should hold ≥1 lesson of
    every new type). Counts come from the DB when available, otherwise
    from source modules.
    """
    audit = build_audit(source_dir, db_session=db_session)
    source = audit.get("source", {})
    db = audit.get("db")
    db_error = audit.get("db_error")
    reconciliation = audit.get("reconciliation") or {}
    levels = _cefr_levels_present(audit)

    # 1) Slot-critical missing per module
    slot_gaps: dict[str, list[dict[str, Any]]] = {
        slot: source.get("missing_slot_critical", {}).get(slot, [])
        for slot in SLOT_CRITICAL_TYPES
    }
    slot_summary = {slot: len(rows) for slot, rows in slot_gaps.items()}

    # 2) Source/DB module reconciliation
    only_in_source = reconciliation.get("only_in_source", []) if db else []
    only_in_db = reconciliation.get("only_in_db", []) if db else []
    reconciliation_summary = {
        "matched": reconciliation.get("matched_count", 0) if db else 0,
        "only_in_source": len(only_in_source),
        "only_in_db": len(only_in_db),
        "available": db is not None and db_error is None,
    }

    # 3) CEFR coverage per new lesson type — DB-first, source fallback
    coverage_source = db if db else source
    lessons_per_level_type = coverage_source.get("lessons_per_level_type") or {}
    cefr_coverage: dict[str, dict[str, int]] = {}
    cefr_gaps: list[dict[str, Any]] = []
    for lesson_type in NEW_LESSON_TYPES:
        cefr_coverage[lesson_type] = {}
        for level in levels:
            count = lessons_per_level_type.get(level, {}).get(lesson_type, 0)
            cefr_coverage[lesson_type][level] = count
            if count < min_coverage_per_level:
                cefr_gaps.append(
                    {
                        "lesson_type": lesson_type,
                        "level": level,
                        "count": count,
                        "min_required": min_coverage_per_level,
                    }
                )

    # 4) Audio metadata gaps — source-side counts (always available);
    #    DB counts when present.
    audio_gaps: dict[str, dict[str, Any]] = {}
    for ltype in EXISTING_LISTENING_TYPES:
        src_rows = source.get("listening_missing_audio", {}).get(ltype, [])
        entry: dict[str, Any] = {
            "source_missing": len(src_rows),
            "source_rows": src_rows,
        }
        if db:
            db_rows = db.get("listening_missing_audio", {}).get(ltype, [])
            entry["db_missing"] = len(db_rows)
            entry["db_rows"] = db_rows
        audio_gaps[ltype] = entry

    # 5) Vocabulary enrichment gaps — DB only
    vocab_gaps: dict[str, Any] = {"available": False}
    if db:
        vc = db.get("vocab_coverage") or {}
        total = vc.get("total_words") or 0
        gap_rows = []
        for field_name in (
            "ipa_transcription",
            "frequency_band",
            "synonyms",
            "antonyms",
            "etymology",
        ):
            filled = vc.get(field_name) or 0
            missing = max(total - filled, 0)
            gap_rows.append(
                {
                    "field": field_name,
                    "filled": filled,
                    "missing": missing,
                    "coverage_pct": round((filled / total) * 100, 2) if total else 0.0,
                }
            )
        vocab_gaps = {
            "available": True,
            "total_words": total,
            "fields": gap_rows,
            "word_collocations_rows": vc.get("word_collocations_rows") or 0,
            "cultural_notes_rows": vc.get("cultural_notes_rows") or 0,
        }

    # 6) SRS source tagging gaps — DB only
    srs_gaps: dict[str, Any] = {"available": False}
    if db:
        srs = db.get("srs_source") or {}
        srs_gaps = {
            "available": True,
            "total_card_directions": srs.get("total_card_directions") or 0,
            "with_source": srs.get("with_source") or 0,
            "without_source": srs.get("without_source") or 0,
            "breakdown": srs.get("breakdown") or {},
        }

    return {
        "source_dir": audit["source_dir"],
        "db_available": db is not None and db_error is None,
        "db_error": db_error,
        "min_coverage_per_level": min_coverage_per_level,
        "levels_in_scope": levels,
        "slot_critical": {
            "summary": slot_summary,
            "missing": slot_gaps,
        },
        "reconciliation": {
            "summary": reconciliation_summary,
            "only_in_source": only_in_source,
            "only_in_db": only_in_db,
        },
        "cefr_coverage": {
            "matrix": cefr_coverage,
            "gaps": cefr_gaps,
        },
        "audio_metadata": audio_gaps,
        "vocabulary": vocab_gaps,
        "srs_source": srs_gaps,
    }


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join(str(v) for v in row) + " |\n"
    return out


def format_markdown(report: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("# Immersion Content Gap Report\n")
    out.append(f"_Source directory_: `{report['source_dir']}`\n")
    if report.get("db_error"):
        out.append(f"_DB unavailable_: `{report['db_error']}` — DB-only sections will be marked accordingly.\n")
    elif not report["db_available"]:
        out.append("_DB unavailable_: source-only run — DB-only sections will be marked accordingly.\n")

    # 1) Slot-critical
    out.append("\n## 1. Missing slot-critical lesson types per source module\n")
    summary = report["slot_critical"]["summary"]
    out.append(
        _md_table(
            ["slot", "modules_missing"],
            [[slot, summary.get(slot, 0)] for slot in SLOT_CRITICAL_TYPES],
        )
    )
    for slot in SLOT_CRITICAL_TYPES:
        rows = report["slot_critical"]["missing"].get(slot, [])
        out.append(f"\n### `{slot}` — missing in {len(rows)} module(s)\n")
        if rows:
            shown = rows[:50]
            out.append(
                _md_table(
                    ["level", "file_order", "filename", "title"],
                    [[r["level"], r["file_order"], r["filename"], r["title"]] for r in shown],
                )
            )
            if len(rows) > 50:
                out.append(f"_…and {len(rows) - 50} more_\n")

    # 2) Source vs DB reconciliation
    out.append("\n## 2. Source/DB module mismatch\n")
    rec = report["reconciliation"]
    s = rec["summary"]
    if not s["available"]:
        out.append("_Reconciliation skipped — DB unavailable._\n")
    else:
        out.append(
            f"- Matched: **{s['matched']}** | Only in source: **{s['only_in_source']}** | Only in DB: **{s['only_in_db']}**\n"
        )
        if rec["only_in_source"]:
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
        if rec["only_in_db"]:
            out.append("\n### DB modules with no matching source file\n")
            out.append(
                _md_table(
                    ["level", "number", "id", "title"],
                    [
                        [m["level"], m.get("number"), m["id"], m.get("title")]
                        for m in rec["only_in_db"]
                    ],
                )
            )

    # 3) CEFR coverage per new lesson type
    out.append("\n## 3. Missing CEFR coverage per new lesson type\n")
    out.append(
        f"_Threshold: ≥ {report['min_coverage_per_level']} lesson per CEFR level._\n"
    )
    matrix = report["cefr_coverage"]["matrix"]
    levels = report["levels_in_scope"]
    rows = []
    for lesson_type in NEW_LESSON_TYPES:
        row: list[Any] = [lesson_type]
        for level in levels:
            row.append(matrix.get(lesson_type, {}).get(level, 0))
        rows.append(row)
    out.append(_md_table(["lesson_type", *levels], rows))
    gaps = report["cefr_coverage"]["gaps"]
    out.append(f"\nGap rows (count < {report['min_coverage_per_level']}): **{len(gaps)}**\n")
    if gaps:
        out.append(
            _md_table(
                ["lesson_type", "level", "count", "min_required"],
                [[g["lesson_type"], g["level"], g["count"], g["min_required"]] for g in gaps],
            )
        )

    # 4) Audio metadata gaps
    out.append("\n## 4. Audio metadata gaps\n")
    for ltype in EXISTING_LISTENING_TYPES:
        entry = report["audio_metadata"][ltype]
        out.append(f"\n### `{ltype}`\n")
        out.append(f"- Source lessons missing audio: **{entry['source_missing']}**\n")
        if "db_missing" in entry:
            out.append(f"- DB lessons missing audio: **{entry['db_missing']}**\n")
        else:
            out.append("- DB lessons missing audio: _not measured (DB unavailable)_\n")
        rows = entry.get("source_rows", [])
        if rows:
            shown = rows[:25]
            out.append(
                _md_table(
                    ["level", "file_order", "filename", "title"],
                    [[r["level"], r["file_order"], r["filename"], r["title"]] for r in shown],
                )
            )
            if len(rows) > 25:
                out.append(f"_…and {len(rows) - 25} more_\n")

    # 5) Vocabulary enrichment gaps
    out.append("\n## 5. Vocabulary enrichment gaps\n")
    vocab = report["vocabulary"]
    if not vocab.get("available"):
        out.append("_Vocabulary gaps skipped — DB unavailable._\n")
    else:
        out.append(f"- Total words: **{vocab['total_words']}**\n")
        out.append(
            _md_table(
                ["field", "filled", "missing", "coverage_pct"],
                [
                    [f["field"], f["filled"], f["missing"], f["coverage_pct"]]
                    for f in vocab["fields"]
                ],
            )
        )
        out.append(
            f"- word_collocations rows: **{vocab['word_collocations_rows']}**\n"
        )
        out.append(f"- cultural_notes rows: **{vocab['cultural_notes_rows']}**\n")

    # 6) SRS source tagging gaps
    out.append("\n## 6. SRS source tagging gaps\n")
    srs = report["srs_source"]
    if not srs.get("available"):
        out.append("_SRS source gaps skipped — DB unavailable._\n")
    else:
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

    return "".join(out)


def format_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)


def _try_get_db_session():
    """Try to import the Flask app and return (app, db). (None, None) on failure."""
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
    parser = argparse.ArgumentParser(description="Report immersion content gaps.")
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
        help="Output file path. Defaults to reports/immersion_gap_report.md (or .json).",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB audit even if the app is importable.",
    )
    parser.add_argument(
        "--min-coverage-per-level",
        type=int,
        default=1,
        help="Minimum lessons required per (new_lesson_type, CEFR level). Default 1.",
    )
    args = parser.parse_args(argv)

    app = None
    db_session = None
    if not args.no_db:
        app, db_session = _try_get_db_session()

    if app is not None and db_session is not None:
        with app.app_context():
            report = build_gap_report(
                args.source_dir,
                db_session=db_session,
                min_coverage_per_level=args.min_coverage_per_level,
            )
    else:
        report = build_gap_report(
            args.source_dir,
            db_session=None,
            min_coverage_per_level=args.min_coverage_per_level,
        )

    if args.format == "markdown":
        text = format_markdown(report)
        default_out = DEFAULT_REPORT_PATH
    else:
        text = format_json(report)
        default_out = DEFAULT_REPORT_PATH.with_suffix(".json")

    out_path = args.output or default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
