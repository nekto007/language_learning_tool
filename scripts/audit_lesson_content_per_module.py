"""Audit lesson content across all modules.

For every (level, module, lesson) in the DB, checks:
  - has_new_schema: content uses new schema fields for this lesson type
  - has_audio_url: content.audio_url is set (for audio-driven types)
  - audio_on_disk: audio file physically exists on disk
  - transform_prompt_ok: final_test transformation prompts use correct phrasing
  - pairs_keys_ok: matching pairs use consistent key shape

Outputs:
  - Per-lesson gap detail table
  - Per-module heatmap (rows = modules, columns = lesson types)

Usage:
    python scripts/audit_lesson_content_per_module.py [--no-db] [--output PATH] [--format markdown|json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_ROOT = PROJECT_ROOT / "app" / "static" / "audio"
STATIC_ROOT = AUDIO_ROOT.parent  # app/static/

DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "module_content_audit_baseline.md"

AUDIO_DRIVEN_TYPES = frozenset({
    "dictation",
    "audio_fill_blank",
    "shadow_reading",
    "listening_immersion",
    "listening_quiz",
    "pronunciation",
})

BAD_TRANSFORM_PROMPTS = frozenset({
    "Сделайте вопрос",
    "Make a question",
    "сделайте вопрос",
    "make a question",
})


@dataclass
class LessonAuditRow:
    lesson_id: int
    module_id: int
    module_title: str
    level_code: str
    module_number: int
    lesson_number: int
    lesson_title: str
    lesson_type: str
    has_new_schema: bool | None    # None = check not applicable
    has_audio_url: bool | None
    audio_on_disk: bool | None
    transform_prompt_ok: bool | None
    pairs_keys_ok: bool | None

    @property
    def gap_count(self) -> int:
        return sum(
            1 for c in (
                self.has_new_schema,
                self.has_audio_url,
                self.audio_on_disk,
                self.transform_prompt_ok,
                self.pairs_keys_ok,
            )
            if c is False
        )

    @property
    def is_ok(self) -> bool:
        return self.gap_count == 0


def _check_new_schema(lesson_type: str, content: dict) -> bool | None:
    """True = new schema in use, False = legacy shape, None = not applicable."""
    if lesson_type == "translation":
        return bool(content.get("items") or content.get("mode"))
    if lesson_type == "writing_prompt":
        return bool(content.get("mode") or content.get("min_sentences") or content.get("prompt_ru"))
    if lesson_type == "sentence_correction":
        return bool(content.get("mode") or content.get("items"))
    if lesson_type == "audio_fill_blank":
        return bool(content.get("items"))
    if lesson_type == "dictation":
        return bool(content.get("transcript"))
    if lesson_type == "shadow_reading":
        return bool(content.get("text") or content.get("transcript"))
    if lesson_type == "final_test":
        return (
            content.get("passing_score_percent") is not None
            or "test_sections" in content
        )
    if lesson_type == "matching":
        return bool(content.get("pairs"))
    if lesson_type in ("sentence_completion", "collocation_matching", "idiom", "pronunciation"):
        return bool(content.get("items"))
    return None


def _check_audio_url(lesson_type: str, content: dict) -> bool | None:
    if lesson_type not in AUDIO_DRIVEN_TYPES:
        return None
    if content.get("audio_url"):
        return True
    if lesson_type in ("audio_fill_blank", "listening_quiz"):
        items = content.get("items") or content.get("questions") or []
        if isinstance(items, list):
            return any(
                isinstance(it, dict)
                and (it.get("audio_url") or it.get("audio_clip_url") or it.get("audio"))
                for it in items
            )
    return False


def _resolve_audio_path(audio_url: str) -> Path | None:
    """Convert /static/audio/... URL to an absolute filesystem Path."""
    if not audio_url:
        return None
    clean = audio_url.lstrip("/")
    if clean.startswith("app/static/"):
        clean = clean[len("app/static/"):]
    elif clean.startswith("static/"):
        clean = clean[len("static/"):]
    else:
        # Not a recognisable URL — may be a bare filename or already absolute
        return None
    return STATIC_ROOT / clean


def _check_audio_on_disk(lesson_type: str, content: dict) -> bool | None:
    if lesson_type not in AUDIO_DRIVEN_TYPES:
        return None
    audio_url = content.get("audio_url") or ""
    if audio_url:
        path = _resolve_audio_path(audio_url)
        if path is None:
            return None
        return path.exists()
    if lesson_type in ("audio_fill_blank", "listening_quiz"):
        items = content.get("items") or content.get("questions") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                url = it.get("audio_url") or it.get("audio_clip_url") or it.get("audio") or ""
                if url:
                    path = _resolve_audio_path(url)
                    if path is not None:
                        return path.exists()
    return None


def _check_transform_prompt(lesson_type: str, content: dict) -> bool | None:
    if lesson_type != "final_test":
        return None
    sections = content.get("test_sections") or content.get("sections") or []
    top_exercises = content.get("exercises") or content.get("questions") or []
    all_exercises: list[dict] = list(top_exercises)
    for section in sections:
        if isinstance(section, dict):
            all_exercises.extend(
                section.get("exercises") or section.get("questions") or []
            )
    for ex in all_exercises:
        if not isinstance(ex, dict):
            continue
        if "transform" not in (ex.get("type") or "").lower():
            continue
        prompt = (
            ex.get("question") or ex.get("prompt") or ex.get("instruction") or ""
        )
        if any(bad in prompt for bad in BAD_TRANSFORM_PROMPTS):
            return False
    return True


def _check_pairs_keys(lesson_type: str, content: dict) -> bool | None:
    if lesson_type not in ("matching", "final_test"):
        return None
    pairs: list[Any] = []
    if lesson_type == "matching":
        pairs = content.get("pairs") or []
    else:
        sections = content.get("test_sections") or content.get("sections") or []
        all_exercises: list[dict] = list(content.get("exercises") or content.get("questions") or [])
        for section in sections:
            if isinstance(section, dict):
                all_exercises.extend(section.get("exercises") or section.get("questions") or [])
        for ex in all_exercises:
            if not isinstance(ex, dict):
                continue
            if "match" in (ex.get("type") or "").lower():
                pairs.extend(ex.get("pairs") or [])
    if not pairs:
        return None
    for pair in pairs:
        if not isinstance(pair, dict):
            return False
        has_en_ru = "english" in pair or "russian" in pair
        has_lr = "left" in pair or "right" in pair
        if not has_en_ru and not has_lr:
            return False
    return True


def audit_lesson(
    lesson_id: int,
    module_id: int,
    module_title: str,
    level_code: str,
    module_number: int,
    lesson_number: int,
    lesson_title: str,
    lesson_type: str,
    content: dict,
) -> LessonAuditRow:
    return LessonAuditRow(
        lesson_id=lesson_id,
        module_id=module_id,
        module_title=module_title,
        level_code=level_code,
        module_number=module_number,
        lesson_number=lesson_number,
        lesson_title=lesson_title,
        lesson_type=lesson_type,
        has_new_schema=_check_new_schema(lesson_type, content),
        has_audio_url=_check_audio_url(lesson_type, content),
        audio_on_disk=_check_audio_on_disk(lesson_type, content),
        transform_prompt_ok=_check_transform_prompt(lesson_type, content),
        pairs_keys_ok=_check_pairs_keys(lesson_type, content),
    )


def audit_db(db_session) -> list[LessonAuditRow]:
    """Query all lessons from DB and return audit rows. Requires Flask app context."""
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session
    rows = (
        session.query(
            Lessons.id,
            Lessons.module_id,
            Module.title,
            CEFRLevel.code,
            Module.number,
            Lessons.number,
            Lessons.title,
            Lessons.type,
            Lessons.content,
        )
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
        .all()
    )
    result = []
    for row in rows:
        (
            lesson_id, module_id, module_title, level_code,
            module_number, lesson_number, lesson_title, lesson_type, content,
        ) = row
        if not isinstance(content, dict):
            content = {}
        result.append(
            audit_lesson(
                lesson_id=lesson_id,
                module_id=module_id,
                module_title=module_title or "",
                level_code=level_code or "",
                module_number=module_number or 0,
                lesson_number=lesson_number or 0,
                lesson_title=lesson_title or "",
                lesson_type=lesson_type or "",
                content=content,
            )
        )
    return result


def build_heatmap(rows: list[LessonAuditRow]) -> dict[str, Any]:
    """Aggregate audit rows into a per-module × per-type heatmap."""
    all_types: set[str] = set()
    module_type_rows: dict[tuple, dict[str, list[LessonAuditRow]]] = {}
    for row in rows:
        key = (row.level_code, row.module_number, row.module_title)
        all_types.add(row.lesson_type)
        bucket = module_type_rows.setdefault(key, {})
        bucket.setdefault(row.lesson_type, []).append(row)

    sorted_types = sorted(all_types)
    sorted_modules = sorted(module_type_rows.keys())

    heatmap_rows = []
    for level_code, mod_number, mod_title in sorted_modules:
        key = (level_code, mod_number, mod_title)
        cells: dict[str, str] = {}
        for lt in sorted_types:
            lessons = module_type_rows[key].get(lt, [])
            if not lessons:
                cells[lt] = "-"
            else:
                total_gaps = sum(r.gap_count for r in lessons)
                cells[lt] = "OK" if total_gaps == 0 else f"{total_gaps} gap{'s' if total_gaps != 1 else ''}"
        heatmap_rows.append(
            {
                "level": level_code,
                "module_number": mod_number,
                "module_title": mod_title,
                "cells": cells,
            }
        )
    return {"lesson_types": sorted_types, "modules": heatmap_rows}


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join(str(v) for v in row) + " |\n"
    return out


def format_markdown(rows: list[LessonAuditRow]) -> str:
    lines: list[str] = []
    lines.append("# Module Content Audit — Baseline\n\n")

    total = len(rows)
    with_gaps = sum(1 for r in rows if not r.is_ok)
    pct = f"{with_gaps * 100 // total}" if total else "0"
    lines.append(f"Total lessons audited: **{total}**  \n")
    lines.append(f"Lessons with gaps: **{with_gaps}** ({pct}%)  \n\n")

    gaps_by_type: Counter = Counter()
    total_by_type: Counter = Counter()
    for r in rows:
        total_by_type[r.lesson_type] += 1
        if not r.is_ok:
            gaps_by_type[r.lesson_type] += 1

    lines.append("## Gap Summary by Lesson Type\n\n")
    summary_rows = []
    for lt in sorted(total_by_type.keys()):
        t = total_by_type[lt]
        g = gaps_by_type[lt]
        pct_t = f"{g * 100 // t}%" if t else "0%"
        summary_rows.append([lt, t, g, pct_t])
    lines.append(_md_table(["lesson_type", "total", "with_gaps", "gap_%"], summary_rows))

    heatmap = build_heatmap(rows)
    lesson_types = heatmap["lesson_types"]
    lines.append("\n## Per-Module Heatmap\n\n")
    lines.append(
        "Cell: `OK` = no gaps, `N gap(s)` = gap items found, `-` = type absent in module.  \n\n"
    )

    CHUNK = 20
    for chunk_start in range(0, max(1, len(lesson_types)), CHUNK):
        chunk_types = lesson_types[chunk_start: chunk_start + CHUNK]
        if not chunk_types:
            break
        headers = ["level", "mod#", "title", *chunk_types]
        table_rows = []
        for mod_row in heatmap["modules"]:
            cells = [mod_row["cells"].get(lt, "-") for lt in chunk_types]
            table_rows.append(
                [mod_row["level"], mod_row["module_number"], mod_row["module_title"][:40], *cells]
            )
        lines.append(_md_table(headers, table_rows))

    gap_rows = [r for r in rows if not r.is_ok]
    if gap_rows:
        lines.append("\n## Lessons with Gaps (detail)\n\n")
        detail_rows = []
        for r in gap_rows[:500]:
            gap_labels = []
            if r.has_new_schema is False:
                gap_labels.append("new_schema")
            if r.has_audio_url is False:
                gap_labels.append("audio_url")
            if r.audio_on_disk is False:
                gap_labels.append("audio_on_disk")
            if r.transform_prompt_ok is False:
                gap_labels.append("transform_prompt")
            if r.pairs_keys_ok is False:
                gap_labels.append("pairs_keys")
            detail_rows.append(
                [
                    r.level_code,
                    r.module_number,
                    r.module_title[:30],
                    r.lesson_number,
                    r.lesson_type,
                    r.lesson_title[:40],
                    "; ".join(gap_labels),
                ]
            )
        lines.append(
            _md_table(
                ["level", "mod#", "module", "les#", "type", "lesson", "gaps"],
                detail_rows,
            )
        )
        if len(gap_rows) > 500:
            lines.append(f"\n_…{len(gap_rows) - 500} more gap rows omitted_\n")

    return "".join(lines)


def format_json(rows: list[LessonAuditRow]) -> str:
    return json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False)


def build_audit(db_session=None) -> list[LessonAuditRow]:
    if db_session is None:
        return []
    return audit_db(db_session)


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
    parser = argparse.ArgumentParser(description="Audit lesson content per module.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: reports/module_content_audit_baseline.md)",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB query; produces an empty (but valid) report.",
    )
    args = parser.parse_args(argv)

    rows: list[LessonAuditRow] = []
    if not args.no_db:
        app, db = _try_get_db()
        if app is not None and db is not None:
            with app.app_context():
                rows = build_audit(db_session=db)
        else:
            print("WARN: DB unavailable; producing empty audit.", file=sys.stderr)

    if args.format == "markdown":
        text = format_markdown(rows)
        default_out = DEFAULT_REPORT_PATH
    else:
        text = format_json(rows)
        default_out = DEFAULT_REPORT_PATH.with_suffix(".json")

    out_path = args.output or default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
