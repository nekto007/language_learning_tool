"""Idempotent audio metadata importer for existing lessons.

Reads a JSON array from `content/immersion/` and patches only audio-related
fields in the existing `lessons.content` column. Non-audio lesson fields
(title, type, number, description, user progress) are never modified.

Each entry in the JSON must have:
    level           CEFR level code (A1, A2, B1, B2, C1)
    module_number   integer module order within the level
    lesson_type     target lesson type to match
    audio_url       new audio URL to write into content
    duration_seconds  integer seconds (written into content)

Optional per-entry fields:
    needs_audio_file  bool — informational, not written to DB
    exclusion_reason  str  — if non-null the entry is skipped with a note

The importer matches lessons by (level, module_number, lesson_type). If
multiple lessons of the same type exist in a module, the first (lowest
number) is patched. If no lesson is found the entry is reported as skipped.

Flags:
    --dry-run           plan only, no DB writes
    --level CODE        only entries for that CEFR level
    --module-id INT     only entries resolving to that DB module id
    --lesson-type TYPE  only entries of that lesson_type
    --report PATH       write markdown report to PATH
    --patch-fields F,F  comma-separated content fields to patch
                        (default: audio_url,duration_seconds)

Usage:
    python scripts/import_lesson_audio_metadata.py FILE [FILE ...] [options]

Task 31 — see docs/plans/2026-05-11-post-immersion-content-data-plan.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATCH_FIELDS = ("audio_url", "duration_seconds")

ALLOWED_LEVELS = ("A0", "A1", "A2", "B1", "B2", "C1", "C2")
REQUIRED_ENTRY_KEYS = ("level", "module_number", "lesson_type", "audio_url", "duration_seconds")


# ---------------------------------------------------------------------------
# Entry and plan data classes
# ---------------------------------------------------------------------------


@dataclass
class AudioEntry:
    level: str
    module_number: int
    lesson_type: str
    audio_url: str
    duration_seconds: int
    external_key: str = ""
    needs_audio_file: bool = False
    exclusion_reason: Optional[str] = None
    patch_fields: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class PatchChange:
    action: str  # 'patch' | 'noop' | 'skip_excluded' | 'skip_no_lesson' | 'skip_filtered' | 'skip_no_module'
    level: str
    module_number: int
    lesson_type: str
    lesson_id: Optional[int] = None
    db_module_id: Optional[int] = None
    reason: str = ""
    patched_fields: list = field(default_factory=list)
    external_key: str = ""


@dataclass
class PatchPlan:
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


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def parse_entry(
    raw: dict,
    patch_fields: tuple = DEFAULT_PATCH_FIELDS,
) -> tuple:
    """Return (AudioEntry, None) or (None, error_str)."""
    if not isinstance(raw, dict):
        return None, "entry is not an object"
    level = str(raw.get("level") or "").strip()
    if level not in ALLOWED_LEVELS:
        return None, f"invalid level: {level!r}"
    module_number = _coerce_int(raw.get("module_number"))
    if module_number is None or module_number <= 0:
        return None, f"invalid module_number: {raw.get('module_number')!r}"
    lesson_type = str(raw.get("lesson_type") or "").strip()
    if not lesson_type:
        return None, "empty lesson_type"
    audio_url = str(raw.get("audio_url") or "").strip()
    if not audio_url:
        return None, "empty audio_url"
    duration_seconds = _coerce_int(raw.get("duration_seconds"))
    if duration_seconds is None or duration_seconds <= 0:
        return None, f"invalid duration_seconds: {raw.get('duration_seconds')!r}"

    # Build the dict of fields that will actually be written to content
    patch_dict: dict = {}
    if "audio_url" in patch_fields:
        patch_dict["audio_url"] = audio_url
    if "duration_seconds" in patch_fields:
        patch_dict["duration_seconds"] = duration_seconds
    # Any extra patch fields that appear in the raw entry
    for f in patch_fields:
        if f not in ("audio_url", "duration_seconds") and f in raw:
            patch_dict[f] = raw[f]

    return (
        AudioEntry(
            level=level,
            module_number=module_number,
            lesson_type=lesson_type,
            audio_url=audio_url,
            duration_seconds=duration_seconds,
            external_key=str(raw.get("external_key") or ""),
            needs_audio_file=bool(raw.get("needs_audio_file", False)),
            exclusion_reason=raw.get("exclusion_reason") or None,
            patch_fields=patch_dict,
            raw=raw,
        ),
        None,
    )


def load_entries(paths: list, patch_fields: tuple = DEFAULT_PATCH_FIELDS) -> tuple:
    """Return (entries, errors)."""
    entries: list = []
    errors: list = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        if not isinstance(data, list):
            errors.append(f"{path}: top-level must be a JSON array")
            continue
        for idx, raw in enumerate(data):
            entry, err = parse_entry(raw, patch_fields=patch_fields)
            if err:
                errors.append(f"{path}[{idx}]: {err}")
            else:
                entries.append(entry)
    return entries, errors


# ---------------------------------------------------------------------------
# Repository abstraction (makes unit testing possible without DB)
# ---------------------------------------------------------------------------


class Repository:
    def get_module_id(self, level: str, module_number: int) -> Optional[int]:
        raise NotImplementedError

    def find_lesson_by_type(
        self, module_id: int, lesson_type: str
    ) -> Optional[Any]:
        """Return the first (lowest number) lesson of this type in the module, or None."""
        raise NotImplementedError

    def patch_lesson_content(self, lesson_id: int, patch: dict) -> None:
        """Merge patch keys into lesson.content; caller commits."""
        raise NotImplementedError


class DBRepository(Repository):
    def __init__(self, session):
        self._session = session

    def get_module_id(self, level: str, module_number: int) -> Optional[int]:
        from app.curriculum.models import Module, CEFRLevel

        row = (
            self._session.query(Module.id)
            .join(CEFRLevel, Module.level_id == CEFRLevel.id)
            .filter(CEFRLevel.code == level, Module.number == module_number)
            .first()
        )
        return row[0] if row else None

    def find_lesson_by_type(self, module_id: int, lesson_type: str) -> Optional[Any]:
        from app.curriculum.models import Lessons

        return (
            self._session.query(Lessons)
            .filter(Lessons.module_id == module_id, Lessons.type == lesson_type)
            .order_by(Lessons.number.asc())
            .first()
        )

    def patch_lesson_content(self, lesson_id: int, patch: dict) -> None:
        from app.curriculum.models import Lessons
        import copy

        lesson = self._session.query(Lessons).get(lesson_id)
        if lesson is None:
            return
        current = dict(lesson.content or {})
        current.update(patch)
        lesson.content = current
        self._session.flush()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def filter_entries(
    entries: list,
    *,
    level: Optional[str] = None,
    module_id: Optional[int] = None,
    lesson_type: Optional[str] = None,
    repo: Optional[Repository] = None,
) -> list:
    result = []
    for e in entries:
        if level and e.level != level:
            continue
        if lesson_type and e.lesson_type != lesson_type:
            continue
        if module_id is not None and repo is not None:
            db_mid = repo.get_module_id(e.level, e.module_number)
            if db_mid != module_id:
                continue
        result.append(e)
    return result


def plan_patch(entries: list, repo: Repository, patch_fields: tuple = DEFAULT_PATCH_FIELDS) -> PatchPlan:
    plan = PatchPlan()
    for entry in entries:
        if entry.exclusion_reason:
            plan.changes.append(
                PatchChange(
                    action="skip_excluded",
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason=entry.exclusion_reason,
                    external_key=entry.external_key,
                )
            )
            continue

        db_module_id = repo.get_module_id(entry.level, entry.module_number)
        if db_module_id is None:
            plan.changes.append(
                PatchChange(
                    action="skip_no_module",
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason="module not found in DB",
                    external_key=entry.external_key,
                )
            )
            continue

        lesson = repo.find_lesson_by_type(db_module_id, entry.lesson_type)
        if lesson is None:
            plan.changes.append(
                PatchChange(
                    action="skip_no_lesson",
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    db_module_id=db_module_id,
                    reason=f"no {entry.lesson_type} lesson in module",
                    external_key=entry.external_key,
                )
            )
            continue

        # Detect if this would be a real change
        current_content = dict(lesson.content or {})
        changed = [k for k, v in entry.patch_fields.items() if current_content.get(k) != v]

        if not changed:
            plan.changes.append(
                PatchChange(
                    action="noop",
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    lesson_id=lesson.id,
                    db_module_id=db_module_id,
                    external_key=entry.external_key,
                )
            )
        else:
            plan.changes.append(
                PatchChange(
                    action="patch",
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    lesson_id=lesson.id,
                    db_module_id=db_module_id,
                    patched_fields=changed,
                    external_key=entry.external_key,
                )
            )

    return plan


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_plan(plan: PatchPlan, entries: list, repo: Repository, *, dry_run: bool = False) -> None:
    entry_map = {(e.level, e.module_number, e.lesson_type): e for e in entries}
    for change in plan.changes:
        if change.action != "patch":
            continue
        key = (change.level, change.module_number, change.lesson_type)
        entry = entry_map.get(key)
        if entry is None or change.lesson_id is None:
            continue
        if not dry_run:
            repo.patch_lesson_content(change.lesson_id, entry.patch_fields)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_report(plan: PatchPlan, *, input_files: list = None) -> str:
    counts = plan.counts
    lines = ["# Audio Metadata Import Report", ""]
    if input_files:
        lines.append("**Input files:** " + ", ".join(str(p) for p in input_files))
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Action | Count |")
    lines.append(f"| --- | --- |")
    for action, count in sorted(counts.items()):
        lines.append(f"| {action} | {count} |")
    lines.append("")

    patch_rows = [c for c in plan.changes if c.action == "patch"]
    if patch_rows:
        lines.append("## Patched lessons")
        lines.append("")
        lines.append("| level | module | type | lesson_id | fields |")
        lines.append("| --- | --- | --- | --- | --- |")
        for ch in patch_rows:
            fields = ", ".join(ch.patched_fields)
            lines.append(f"| {ch.level} | {ch.module_number} | {ch.lesson_type} | {ch.lesson_id} | {fields} |")
        lines.append("")

    skip_rows = [c for c in plan.changes if c.action.startswith("skip_")]
    if skip_rows:
        lines.append("## Skipped entries")
        lines.append("")
        lines.append("| level | module | type | reason |")
        lines.append("| --- | --- | --- | --- |")
        for ch in skip_rows:
            lines.append(f"| {ch.level} | {ch.module_number} | {ch.lesson_type} | {ch.reason} |")
        lines.append("")

    if plan.errors:
        lines.append("## Errors")
        lines.append("")
        for err in plan.errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Patch audio metadata into existing curriculum lessons."
    )
    p.add_argument("files", nargs="+", metavar="FILE", help="JSON audio metadata files")
    p.add_argument("--dry-run", action="store_true", help="plan only, no DB writes")
    p.add_argument("--level", metavar="CODE", help="only entries for this CEFR level")
    p.add_argument("--module-id", type=int, metavar="INT", help="only entries for this DB module id")
    p.add_argument("--lesson-type", metavar="TYPE", help="only entries of this lesson type")
    p.add_argument("--report", metavar="PATH", help="write markdown report to this path")
    p.add_argument(
        "--patch-fields",
        metavar="FIELDS",
        default=",".join(DEFAULT_PATCH_FIELDS),
        help=f"comma-separated fields to patch (default: {','.join(DEFAULT_PATCH_FIELDS)})",
    )
    return p


def main(argv: list = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    patch_fields = tuple(f.strip() for f in args.patch_fields.split(",") if f.strip())

    entries, load_errors = load_entries(args.files, patch_fields=patch_fields)
    if load_errors:
        for err in load_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    entries = filter_entries(
        entries,
        level=args.level,
        lesson_type=args.lesson_type,
    )

    sys.path.insert(0, str(PROJECT_ROOT))
    from app import create_app
    from app.extensions import db as _db

    flask_app = create_app()
    with flask_app.app_context():
        repo = DBRepository(_db.session)

        if args.module_id is not None:
            entries = filter_entries(entries, module_id=args.module_id, repo=repo)

        plan = plan_patch(entries, repo, patch_fields=patch_fields)

        if not args.dry_run:
            apply_plan(plan, entries, repo, dry_run=False)
            _db.session.commit()

        report = format_report(plan, input_files=args.files)
        print(report)

        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
            print(f"Report written to {args.report}", file=sys.stderr)

        counts = plan.counts
        patched = counts.get("patch", 0)
        skipped = sum(v for k, v in counts.items() if k.startswith("skip_"))
        label = "DRY RUN — " if args.dry_run else ""
        print(
            f"\n{label}Done: {patched} patched, {counts.get('noop', 0)} no-op, {skipped} skipped",
            file=sys.stderr,
        )

    return 1 if plan.errors else 0


if __name__ == "__main__":
    sys.exit(main())
