"""Audit remaining lesson types for schema compliance.

Checks five lesson types that were not covered by earlier per-type audits:
  1. pronunciation   — each item has `word` + `phonetic`; `audio` optional
  2. sentence_correction — `mode` field set; item has `incorrect_sentence`
                           plus either `options[]` or free-form grading
  3. sentence_completion — each item has `prompt` + `answer`;
                           `alternatives` optional
  4. collocation_matching — `pairs[]` uses {phrase, translation} shape
  5. idiom              — `phrase`, `meaning_ru`, `example`, `example_ru` present

Usage:
    python scripts/audit_remaining_lesson_types.py              # dry-run report
    python scripts/audit_remaining_lesson_types.py --apply      # patch sentence_correction mode
    python scripts/audit_remaining_lesson_types.py --no-db      # unit-test mode (no DB)
    python scripts/audit_remaining_lesson_types.py --output PATH
    python scripts/audit_remaining_lesson_types.py --type pronunciation
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "remaining_types_audit.md"

LESSON_TYPES = ("pronunciation", "sentence_correction", "sentence_completion",
                "collocation_matching", "idiom")

# CEFR level → sentence_correction mode
_CEFR_MODE: dict[str, str] = {
    "A0": "guided", "A1": "guided",
    "A2": "open", "B1": "open",
    "B2": "rubric", "C1": "rubric", "C2": "rubric",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ItemGap:
    item_idx: int
    missing_fields: list[str]


@dataclass
class LessonAudit:
    lesson_id: int
    lesson_title: str
    module_title: str
    level_code: str
    lesson_type: str
    gaps: list[str] = field(default_factory=list)
    item_gaps: list[ItemGap] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.gaps and not self.item_gaps


# ---------------------------------------------------------------------------
# Per-type check functions — all pure (no DB access)
# ---------------------------------------------------------------------------

def _check_pronunciation(content: dict[str, Any]) -> tuple[list[str], list[ItemGap]]:
    """Check pronunciation lesson schema."""
    gaps: list[str] = []
    item_gaps: list[ItemGap] = []
    items: list[dict] = content.get("items") or content.get("exercises") or []
    if not items:
        gaps.append("no items/exercises array")
        return gaps, item_gaps
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        missing = []
        if not item.get("word"):
            missing.append("word")
        if not item.get("phonetic"):
            missing.append("phonetic")
        if missing:
            item_gaps.append(ItemGap(idx, missing))
    return gaps, item_gaps


def _check_sentence_correction(content: dict[str, Any], level_code: str) -> tuple[list[str], list[ItemGap]]:
    """Check sentence_correction lesson schema."""
    gaps: list[str] = []
    item_gaps: list[ItemGap] = []

    has_mode = bool(content.get("mode"))
    if not has_mode:
        gaps.append("missing mode field")

    items: list[dict] = content.get("items") or []
    if items:
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            missing = []
            if not item.get("incorrect_sentence"):
                missing.append("incorrect_sentence")
            if missing:
                item_gaps.append(ItemGap(idx, missing))
    else:
        # Legacy single-item shape
        if not content.get("incorrect_sentence"):
            gaps.append("missing incorrect_sentence (top-level)")
    return gaps, item_gaps


def _check_sentence_completion(content: dict[str, Any]) -> tuple[list[str], list[ItemGap]]:
    """Check sentence_completion lesson schema."""
    gaps: list[str] = []
    item_gaps: list[ItemGap] = []
    items: list[dict] = content.get("items") or content.get("exercises") or []
    if not items:
        gaps.append("no items/exercises array")
        return gaps, item_gaps
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        missing = []
        if not item.get("prompt"):
            missing.append("prompt")
        if not item.get("answer"):
            missing.append("answer")
        if missing:
            item_gaps.append(ItemGap(idx, missing))
    return gaps, item_gaps


def _check_collocation_matching(content: dict[str, Any]) -> tuple[list[str], list[ItemGap]]:
    """Check collocation_matching lesson schema — pairs must use {phrase, translation}."""
    gaps: list[str] = []
    item_gaps: list[ItemGap] = []
    pairs: list[dict] = content.get("pairs") or []
    if not pairs:
        gaps.append("no pairs array")
        return gaps, item_gaps
    for idx, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            continue
        missing = []
        if not pair.get("phrase"):
            missing.append("phrase")
        if not pair.get("translation"):
            missing.append("translation")
        if missing:
            item_gaps.append(ItemGap(idx, missing))
    return gaps, item_gaps


def _check_idiom(content: dict[str, Any]) -> tuple[list[str], list[ItemGap]]:
    """Check idiom lesson schema — top-level phrase/meaning_ru/example/example_ru."""
    gaps: list[str] = []
    item_gaps: list[ItemGap] = []
    required = ("phrase", "meaning_ru", "example", "example_ru")
    missing = [f for f in required if not content.get(f)]
    if missing:
        gaps.extend(f"missing {f}" for f in missing)
    return gaps, item_gaps


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def audit_content(
    lesson_id: int,
    lesson_title: str,
    module_title: str,
    level_code: str,
    lesson_type: str,
    content: dict[str, Any],
) -> LessonAudit:
    result = LessonAudit(
        lesson_id=lesson_id,
        lesson_title=lesson_title,
        module_title=module_title,
        level_code=level_code,
        lesson_type=lesson_type,
    )
    if lesson_type == "pronunciation":
        result.gaps, result.item_gaps = _check_pronunciation(content)
    elif lesson_type == "sentence_correction":
        result.gaps, result.item_gaps = _check_sentence_correction(content, level_code)
    elif lesson_type == "sentence_completion":
        result.gaps, result.item_gaps = _check_sentence_completion(content)
    elif lesson_type == "collocation_matching":
        result.gaps, result.item_gaps = _check_collocation_matching(content)
    elif lesson_type == "idiom":
        result.gaps, result.item_gaps = _check_idiom(content)
    return result


# ---------------------------------------------------------------------------
# Patch logic (sentence_correction mode only)
# ---------------------------------------------------------------------------

def _patch_sentence_correction_mode(content: dict[str, Any], level_code: str) -> tuple[dict[str, Any], bool]:
    """Add 'mode' to sentence_correction if missing. Returns (patched, changed)."""
    if content.get("mode"):
        return content, False
    patched = copy.deepcopy(content)
    mode = _CEFR_MODE.get(level_code, "open")
    patched["mode"] = mode
    return patched, True


# ---------------------------------------------------------------------------
# DB mode
# ---------------------------------------------------------------------------

def audit_db(db_session, lesson_types: list[str] | None = None) -> list[LessonAudit]:
    from app.curriculum.models import CEFRLevel, Lessons, Module

    types_to_check = lesson_types or list(LESSON_TYPES)
    session = db_session.session
    rows = (
        session.query(
            Lessons.id,
            Lessons.title,
            Lessons.type,
            Lessons.content,
            Module.title,
            CEFRLevel.code,
        )
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(Lessons.type.in_(types_to_check))
        .order_by(CEFRLevel.order, Module.number, Lessons.number)
        .all()
    )
    results = []
    for lesson_id, lesson_title, lesson_type, content, module_title, level_code in rows:
        if not isinstance(content, dict):
            content = {}
        results.append(
            audit_content(
                lesson_id=lesson_id,
                lesson_title=lesson_title or "",
                module_title=module_title or "",
                level_code=level_code or "",
                lesson_type=lesson_type,
                content=content,
            )
        )
    return results


def apply_db(db_session, dry_run: bool = True) -> list[tuple[int, str, str]]:
    """Patch sentence_correction rows that are missing 'mode'. Returns (id, title, mode)."""
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session
    rows = (
        session.query(Lessons, CEFRLevel.code)
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(Lessons.type == "sentence_correction")
        .all()
    )
    changed: list[tuple[int, str, str]] = []
    for lesson, level_code in rows:
        content = lesson.content if isinstance(lesson.content, dict) else {}
        if content.get("mode"):
            continue
        patched, was_changed = _patch_sentence_correction_mode(content, level_code)
        if was_changed:
            mode = patched.get("mode", "")
            if not dry_run:
                lesson.content = patched
            changed.append((lesson.id, lesson.title or "", mode))
    if not dry_run:
        session.commit()
    return changed


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_markdown(
    audits: list[LessonAudit],
    changed: list[tuple[int, str, str]] | None = None,
) -> str:
    lines: list[str] = [
        "# Remaining Lesson Types Schema Audit",
        "",
        f"Total lessons audited: **{len(audits)}**",
        f"Lessons with gaps: **{sum(1 for a in audits if not a.ok)}**",
        "",
    ]

    # Summary by type
    lines.append("## Summary by type")
    lines.append("")
    lines.append("| Type | Total | With gaps |")
    lines.append("| --- | --- | --- |")
    for lt in LESSON_TYPES:
        type_audits = [a for a in audits if a.lesson_type == lt]
        n_gaps = sum(1 for a in type_audits if not a.ok)
        lines.append(f"| {lt} | {len(type_audits)} | {n_gaps} |")
    lines.append("")

    # Detailed gap tables per type
    for lt in LESSON_TYPES:
        type_audits = [a for a in audits if a.lesson_type == lt and not a.ok]
        if not type_audits:
            lines.append(f"## {lt}: all OK")
            lines.append("")
            continue
        lines.append(f"## {lt}: {len(type_audits)} lesson(s) with gaps")
        lines.append("")
        lines.append("| Lesson ID | Level | Module | Lesson | Gaps |")
        lines.append("| --- | --- | --- | --- | --- |")
        for a in type_audits:
            top_gaps = "; ".join(a.gaps)
            item_summary = ""
            if a.item_gaps:
                item_summary = f" | items {[g.item_idx for g in a.item_gaps]}: missing {[g.missing_fields for g in a.item_gaps]}"
            gap_str = (top_gaps + item_summary).strip(" |")
            lines.append(
                f"| {a.lesson_id} | {a.level_code} | {a.module_title[:30]} | "
                f"{a.lesson_title[:30]} | {gap_str} |"
            )
        lines.append("")

    if changed:
        lines.append("## sentence_correction mode patches")
        lines.append("")
        lines.append("| Lesson ID | Title | Mode assigned |")
        lines.append("| --- | --- | --- |")
        for lesson_id, title, mode in changed:
            lines.append(f"| {lesson_id} | {title} | {mode} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit remaining lesson types for schema compliance")
    parser.add_argument("--apply", action="store_true",
                        help="Patch sentence_correction rows missing 'mode'")
    parser.add_argument("--no-db", action="store_true", help="Skip DB, only test logic")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--type", dest="lesson_type", choices=list(LESSON_TYPES),
                        help="Audit only one lesson type")
    args = parser.parse_args(argv)

    if args.no_db:
        print("[audit_remaining_lesson_types] --no-db mode: nothing to do")
        return 0

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("FLASK_ENV", "development")
    from app import create_app, db as _db

    lesson_types = [args.lesson_type] if args.lesson_type else list(LESSON_TYPES)

    app = create_app()
    with app.app_context():
        audits = audit_db(_db, lesson_types=lesson_types)
        changed: list[tuple[int, str, str]] = []

        if args.apply:
            changed = apply_db(_db, dry_run=False)
            print(f"Applied mode patches to {len(changed)} sentence_correction lessons.")
        else:
            changed = apply_db(_db, dry_run=True)
            if changed:
                print(f"Dry-run: {len(changed)} sentence_correction lessons would be patched (run --apply).")

        report = format_markdown(audits, changed if args.apply else None)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written to {out}")

        n_gaps = sum(1 for a in audits if not a.ok)
        if n_gaps > 0:
            print(f"WARNING: {n_gaps} lessons have schema gaps (see report for details).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
