"""Generic idempotent immersion lesson importer.

Reads lesson JSON (array) or JSONL files from `content/immersion/` and
applies them to the curriculum `lessons` table. The importer is
idempotent: a second run with the same input produces zero writes.

Identity model:
    * Target module is resolved by `(level, module_number)` against the
      DB `cefr_levels`/`modules` tables.
    * Lesson rows are matched by a stable `external_key` stored in
      `lessons.content['external_key']`. The key is never reused.

Default behaviour:
    * New lessons are created when no row with the entry's
      `external_key` exists.
    * Existing lessons whose `external_key` matches are updated, but
      only the fields owned by the import (title, type, content,
      optionally description and number). User progress, grades, and
      unrelated lessons in the same module are not touched.
    * Entries marked `environment=staging` are skipped unless
      `--include-staging` is passed.

Filters (CLI):
    `--level CODE`             only entries with that CEFR level
    `--module-id INT`          only entries that resolve to that DB module id
    `--lesson-type TYPE`       only entries of that lesson_type
    `--dry-run`                plan only, no writes
    `--include-staging`        do not auto-skip staging fixtures
    `--report PATH`            write markdown report

Validation (CLI):
    `--canonical-modules-dir`  override canonical source directory
    `--no-validate`            skip content-schema and audio validation
    `--no-source-check`        skip canonical-source presence check
    `--validate-only`          run validation + planning, never write to DB

Validation rules (run before any DB write):
    * `LessonContentValidator` checks the payload against its lesson_type schema.
    * Audio lesson types must carry a non-empty `content.audio_url`.
    * Each (level, module_number) must exist under `module_completed/fixed/`.
    * `external_key` and (level, module_number, lesson_number) must be unique
      inside the input set.

Usage:
    python scripts/import_immersion_lessons.py FILE [FILE ...] [options]

Tasks 10–11 — see `docs/plans/2026-05-11-post-immersion-content-data-plan.md`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "content" / "immersion"
DEFAULT_CANONICAL_MODULES_DIR = PROJECT_ROOT / "module_completed" / "fixed"

_CANONICAL_FILENAME_RE = re.compile(
    r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
)

AUDIO_REQUIRED_TYPES = (
    "dictation",
    "audio_fill_blank",
    "shadow_reading",
    "listening_immersion",
    "listening_quiz",
)

REQUIRED_KEYS = (
    "external_key",
    "level",
    "module_number",
    "lesson_type",
    "title",
    "content",
)
ALLOWED_LEVELS = ("A0", "A1", "A2", "B1", "B2", "C1", "C2")

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


@dataclass
class LessonEntry:
    external_key: str
    level: str
    module_number: int
    lesson_type: str
    title: str
    content: dict
    title_en: Optional[str] = None
    description: Optional[str] = None
    lesson_number: Optional[int] = None
    environment: Optional[str] = None
    tags: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    source_path: Optional[str] = None
    has_description: bool = False
    anchor_after: Optional[str] = None


@dataclass
class ImportChange:
    action: str  # 'create' | 'update' | 'noop' | 'skip_no_module' | 'skip_environment' | 'skip_filtered'
    external_key: str
    level: str
    module_number: int
    lesson_type: str
    lesson_id: Optional[int] = None
    db_module_id: Optional[int] = None
    reason: str = ""
    diff_fields: list = field(default_factory=list)
    shift_above: Optional[int] = None
    anchor_type: Optional[str] = None
    target_number: Optional[int] = None


@dataclass
class ImportPlan:
    changes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        c = {
            "create": 0,
            "update": 0,
            "noop": 0,
            "skip_no_module": 0,
            "skip_environment": 0,
            "skip_filtered": 0,
        }
        for change in self.changes:
            c[change.action] = c.get(change.action, 0) + 1
        return c


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def parse_entry(raw: dict, source_path: Optional[str] = None) -> tuple:
    """Validate raw dict and return (LessonEntry, None) or (None, error_message)."""
    if not isinstance(raw, dict):
        return None, "entry is not an object"
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        return None, f"missing keys: {','.join(missing)}"
    level = str(raw.get("level") or "").strip()
    if level not in ALLOWED_LEVELS:
        return None, f"invalid level: {level!r}"
    module_number = _coerce_int(raw.get("module_number"))
    if module_number is None or module_number <= 0:
        return None, f"invalid module_number: {raw.get('module_number')!r}"
    external_key = str(raw.get("external_key") or "").strip()
    if not external_key:
        return None, "empty external_key"
    lesson_type = str(raw.get("lesson_type") or "").strip()
    if not lesson_type:
        return None, "empty lesson_type"
    title = str(raw.get("title") or "").strip()
    if not title:
        return None, "empty title"
    content = raw.get("content")
    if not isinstance(content, dict):
        return None, "content must be an object"
    lesson_number = _coerce_int(raw.get("lesson_number"))
    if lesson_number is not None and lesson_number <= 0:
        return None, f"invalid lesson_number: {raw.get('lesson_number')!r}"
    description_present = "description" in raw
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        return None, "description must be a string"
    anchor_after = raw.get("anchor_after")
    if anchor_after is not None:
        if not isinstance(anchor_after, str) or not anchor_after.strip():
            return None, "anchor_after must be a non-empty string"
        anchor_after = anchor_after.strip()
    return (
        LessonEntry(
            external_key=external_key,
            level=level,
            module_number=module_number,
            lesson_type=lesson_type,
            title=title,
            content=content,
            title_en=raw.get("title_en"),
            description=description,
            lesson_number=lesson_number,
            environment=raw.get("environment"),
            tags=list(raw.get("tags") or []),
            raw=raw,
            source_path=source_path,
            has_description=description_present,
            anchor_after=anchor_after,
        ),
        None,
    )


def load_lessons(path: Path) -> list:
    """Read JSON array (``.json``) or JSONL (``.jsonl``).

    Raises ValueError on malformed input or unexpected top-level shape.
    """
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    is_jsonl = path.suffix.lower() == ".jsonl"
    if not is_jsonl:
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"{path}: top-level value must be a JSON array")
        return data
    out: list = []
    for i, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: JSONL line {i}: {exc}") from exc
    return out


def filter_entries(
    entries: Iterable,
    *,
    level: Optional[str] = None,
    lesson_type: Optional[str] = None,
    skip_staging: bool = True,
) -> tuple:
    """Apply pre-DB filters. Returns (kept, skipped_changes)."""
    kept: list = []
    skipped: list = []
    for entry in entries:
        if skip_staging and entry.environment == "staging":
            skipped.append(
                ImportChange(
                    action="skip_environment",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason="environment=staging",
                )
            )
            continue
        if level and entry.level != level:
            skipped.append(
                ImportChange(
                    action="skip_filtered",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason=f"level filter {level}",
                )
            )
            continue
        if lesson_type and entry.lesson_type != lesson_type:
            skipped.append(
                ImportChange(
                    action="skip_filtered",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason=f"lesson_type filter {lesson_type}",
                )
            )
            continue
        kept.append(entry)
    return kept, skipped


def _content_with_key(entry: LessonEntry) -> dict:
    payload = dict(entry.content)
    payload["external_key"] = entry.external_key
    return payload


def _content_equal(a: Any, b: Any) -> bool:
    return json.dumps(a or {}, sort_keys=True, ensure_ascii=False) == json.dumps(
        b or {}, sort_keys=True, ensure_ascii=False
    )


def diff_lesson_fields(existing, entry: LessonEntry) -> list:
    """Return list of fields that would change if `entry` were applied."""
    diff: list = []
    if (existing.title or "") != entry.title:
        diff.append("title")
    if entry.has_description:
        if (existing.description or "") != (entry.description or ""):
            diff.append("description")
    if (existing.type or "") != entry.lesson_type:
        diff.append("type")
    if not _content_equal(existing.content, _content_with_key(entry)):
        diff.append("content")
    if entry.lesson_number is not None and existing.number != entry.lesson_number:
        diff.append("number")
    return diff


def load_canonical_module_ids(source_dir: Path) -> set:
    """Return set of (level, module_number) tuples present in canonical source.

    Reads filenames under `module_completed/fixed/` and parses the
    ``module_<level>_<order>_<slug>.json`` pattern. Used to verify imported
    lessons reference a real canonical module before any DB writes happen.
    """
    found: set = set()
    if not source_dir or not source_dir.exists():
        return found
    for path in source_dir.glob("*.json"):
        match = _CANONICAL_FILENAME_RE.match(path.name)
        if match:
            found.add((match.group("level"), int(match.group("order"))))
    return found


def _validate_content_schema(lesson_type: str, content: Any) -> Optional[str]:
    """Run `LessonContentValidator` against an entry's content payload.

    Returns an error string when validation fails, or None on success.
    """
    try:
        from app.curriculum.validators import LessonContentValidator
        from marshmallow import ValidationError as MarshmallowValidationError
    except ImportError as exc:  # pragma: no cover — env without app dependencies
        return f"validator import failed: {exc}"
    if not isinstance(content, dict):
        return "content must be an object"
    try:
        LessonContentValidator.validate(lesson_type, dict(content))
    except ValueError as exc:
        return str(exc)
    except MarshmallowValidationError as exc:
        return f"content invalid: {exc.messages}"
    return None


def validate_entries(
    entries: list,
    *,
    canonical_module_ids: Optional[set] = None,
    check_content_schema: bool = True,
) -> list:
    """Run payload-level validation. Returns list of error strings.

    Checks performed:
    - duplicate `external_key` inside the input set
    - `lesson_type` recognized by `LessonContentValidator`
    - content payload conforms to its lesson_type schema (Marshmallow)
    - required audio fields present for audio lesson types
    - referenced module exists in canonical source (when provided)
    - `lesson_number` is unique inside each (level, module_number) batch
    """
    errors: list = []
    seen_keys: dict = {}
    seen_numbers: dict = {}

    for entry in entries:
        prefix = entry.external_key
        if prefix in seen_keys:
            errors.append(f"{prefix}: duplicate external_key in input")
            continue
        seen_keys[prefix] = entry

        if canonical_module_ids is not None:
            if (entry.level, entry.module_number) not in canonical_module_ids:
                errors.append(
                    f"{prefix}: module {entry.level}#{entry.module_number} not in canonical source directory"
                )

        if entry.lesson_type in AUDIO_REQUIRED_TYPES:
            audio_url = (
                entry.content.get("audio_url")
                if isinstance(entry.content, dict)
                else None
            )
            if not isinstance(audio_url, str) or not audio_url.strip():
                errors.append(
                    f"{prefix}: lesson_type {entry.lesson_type!r} requires non-empty content.audio_url"
                )

        if check_content_schema:
            content_err = _validate_content_schema(entry.lesson_type, entry.content)
            if content_err:
                errors.append(f"{prefix}: {content_err}")

        if entry.lesson_number is not None:
            number_key = (entry.level, entry.module_number, entry.lesson_number)
            if number_key in seen_numbers:
                errors.append(
                    f"{prefix}: duplicate lesson_number {entry.lesson_number} "
                    f"in {entry.level}#{entry.module_number} "
                    f"(also {seen_numbers[number_key]})"
                )
            else:
                seen_numbers[number_key] = prefix

    return errors


class Repository:
    """Interface for DB access used by `plan_import` / `apply_plan`.

    Concrete impls: `DBRepository` (SQLAlchemy) and `FakeRepository` (tests).
    """

    def get_module_id(self, level: str, module_number: int):
        raise NotImplementedError

    def find_lesson_by_external_key(self, external_key: str):
        raise NotImplementedError

    def next_lesson_number(self, module_id: int) -> int:
        raise NotImplementedError

    def lesson_number_taken(
        self,
        module_id: int,
        number: int,
        *,
        exclude_external_key: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    def create_lesson(
        self, *, module_id, number, lesson_type, title, description, content
    ) -> int:
        raise NotImplementedError

    def update_lesson(
        self,
        lesson_id,
        *,
        lesson_type=None,
        title=None,
        description=None,
        content=None,
        number=None,
    ):
        raise NotImplementedError

    def find_lesson_number_by_type(
        self, module_id: int, lesson_type: str
    ) -> Optional[int]:
        """Return the lowest lesson number in the module with the given type."""
        raise NotImplementedError

    def shift_module_lessons_above(self, module_id: int, threshold: int) -> int:
        """Shift every lesson in the module with number >= threshold by +1.

        Returns the number of rows shifted. Must execute as a single
        statement so the unique (module_id, number) index does not flag
        the intermediate states.
        """
        raise NotImplementedError


def plan_import(
    entries: list,
    repo: Repository,
    *,
    db_module_id: Optional[int] = None,
    anchor_after: Optional[str] = None,
) -> ImportPlan:
    """Determine what would change without writing anything.

    When ``anchor_after`` (or per-entry ``anchor_after``) is set, new
    lessons are placed directly after the anchor lesson of the given
    type in their module. If the slot is occupied, the plan records a
    ``shift_above`` instruction so ``apply_plan`` can bump existing
    lessons by +1 before inserting.
    """
    plan = ImportPlan()
    seen_keys: dict = {}
    for entry in entries:
        if entry.external_key in seen_keys:
            plan.errors.append(
                f"duplicate external_key in input: {entry.external_key}"
            )
            continue
        seen_keys[entry.external_key] = entry
        module_id = repo.get_module_id(entry.level, entry.module_number)
        if module_id is None:
            plan.changes.append(
                ImportChange(
                    action="skip_no_module",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    reason=f"no DB module for {entry.level} #{entry.module_number}",
                )
            )
            continue
        if db_module_id is not None and module_id != db_module_id:
            plan.changes.append(
                ImportChange(
                    action="skip_filtered",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    db_module_id=module_id,
                    reason=f"module id filter {db_module_id}",
                )
            )
            continue
        entry_anchor = entry.anchor_after or anchor_after
        existing = repo.find_lesson_by_external_key(entry.external_key)
        if existing is None:
            target_number = entry.lesson_number
            shift_above: Optional[int] = None
            if target_number is None and entry_anchor:
                anchor_number = repo.find_lesson_number_by_type(
                    module_id, entry_anchor
                )
                if anchor_number is None:
                    plan.errors.append(
                        f"{entry.external_key}: anchor lesson_type "
                        f"{entry_anchor!r} not found in module "
                        f"{entry.level}#{entry.module_number}"
                    )
                    continue
                target_number = anchor_number + 1
                if repo.lesson_number_taken(
                    module_id,
                    target_number,
                    exclude_external_key=entry.external_key,
                ):
                    shift_above = target_number
            if target_number is None:
                target_number = repo.next_lesson_number(module_id)
            elif shift_above is None and repo.lesson_number_taken(
                module_id,
                target_number,
                exclude_external_key=entry.external_key,
            ):
                plan.errors.append(
                    f"{entry.external_key}: lesson_number {target_number} already taken in module {entry.level}#{entry.module_number}"
                )
                continue
            plan.changes.append(
                ImportChange(
                    action="create",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    db_module_id=module_id,
                    diff_fields=["title", "type", "content"],
                    reason=f"new lesson #{target_number}"
                    + (
                        f" (anchor_after={entry_anchor}, shift_above={shift_above})"
                        if entry_anchor
                        else ""
                    ),
                    shift_above=shift_above,
                    anchor_type=entry_anchor,
                    target_number=target_number,
                )
            )
        else:
            existing_module_id = getattr(existing, "module_id", None)
            if existing_module_id is not None and existing_module_id != module_id:
                plan.errors.append(
                    f"{entry.external_key}: existing lesson belongs to module {existing_module_id}, entry targets {module_id}"
                )
                continue
            diff = diff_lesson_fields(existing, entry)
            if (
                entry.lesson_number is not None
                and existing.number != entry.lesson_number
                and repo.lesson_number_taken(
                    module_id,
                    entry.lesson_number,
                    exclude_external_key=entry.external_key,
                )
            ):
                plan.errors.append(
                    f"{entry.external_key}: cannot move to lesson_number {entry.lesson_number} (taken in module)"
                )
                continue
            plan.changes.append(
                ImportChange(
                    action="update" if diff else "noop",
                    external_key=entry.external_key,
                    level=entry.level,
                    module_number=entry.module_number,
                    lesson_type=entry.lesson_type,
                    lesson_id=existing.id,
                    db_module_id=module_id,
                    diff_fields=diff,
                )
            )
    return plan


def apply_plan(entries: list, plan: ImportPlan, repo: Repository) -> None:
    """Apply a planned set of changes via the repository."""
    by_key = {e.external_key: e for e in entries}
    for change in plan.changes:
        entry = by_key.get(change.external_key)
        if entry is None:
            continue
        if change.action == "create":
            if change.shift_above is not None:
                repo.shift_module_lessons_above(
                    change.db_module_id, change.shift_above
                )
            target_number = change.target_number or entry.lesson_number
            if target_number is None:
                target_number = repo.next_lesson_number(change.db_module_id)
            new_id = repo.create_lesson(
                module_id=change.db_module_id,
                number=target_number,
                lesson_type=entry.lesson_type,
                title=entry.title,
                description=entry.description,
                content=_content_with_key(entry),
            )
            change.lesson_id = new_id
        elif change.action == "update":
            updates = {}
            if "type" in change.diff_fields:
                updates["lesson_type"] = entry.lesson_type
            if "title" in change.diff_fields:
                updates["title"] = entry.title
            if "description" in change.diff_fields:
                updates["description"] = entry.description
            if "content" in change.diff_fields:
                updates["content"] = _content_with_key(entry)
            if "number" in change.diff_fields:
                updates["number"] = entry.lesson_number
            if updates:
                repo.update_lesson(change.lesson_id, **updates)


class DBRepository(Repository):
    """SQLAlchemy-backed repository against the live curriculum schema."""

    def __init__(self, session):
        self.session = session
        self._module_cache: dict = {}

    def get_module_id(self, level: str, module_number: int):
        key = (level, module_number)
        if key in self._module_cache:
            return self._module_cache[key]
        from app.curriculum.models import CEFRLevel, Module

        row = (
            self.session.query(Module.id)
            .join(CEFRLevel, CEFRLevel.id == Module.level_id)
            .filter(CEFRLevel.code == level, Module.number == module_number)
            .first()
        )
        result = row[0] if row else None
        self._module_cache[key] = result
        return result

    def find_lesson_by_external_key(self, external_key: str):
        from app.curriculum.models import Lessons

        # Use the PostgreSQL `->>` operator so the lookup works on both
        # JSON and JSONB columns. `astext` would require JSONB.
        return (
            self.session.query(Lessons)
            .filter(Lessons.content.op("->>")("external_key") == external_key)
            .first()
        )

    def next_lesson_number(self, module_id: int) -> int:
        from sqlalchemy import func

        from app.curriculum.models import Lessons

        result = (
            self.session.query(func.coalesce(func.max(Lessons.number), 0))
            .filter(Lessons.module_id == module_id)
            .scalar()
        )
        return int(result or 0) + 1

    def lesson_number_taken(
        self,
        module_id: int,
        number: int,
        *,
        exclude_external_key: Optional[str] = None,
    ) -> bool:
        from app.curriculum.models import Lessons

        row = (
            self.session.query(Lessons.id, Lessons.content)
            .filter(Lessons.module_id == module_id, Lessons.number == number)
            .first()
        )
        if row is None:
            return False
        if exclude_external_key is not None:
            content = row[1] if isinstance(row[1], dict) else {}
            if content.get("external_key") == exclude_external_key:
                return False
        return True

    def create_lesson(
        self, *, module_id, number, lesson_type, title, description, content
    ) -> int:
        from app.curriculum.models import Lessons

        lesson = Lessons(
            module_id=module_id,
            number=number,
            type=lesson_type,
            title=title,
            description=description,
            content=content,
            order=0,
        )
        self.session.add(lesson)
        self.session.flush()
        return lesson.id

    def update_lesson(
        self,
        lesson_id,
        *,
        lesson_type=None,
        title=None,
        description=None,
        content=None,
        number=None,
    ):
        from app.curriculum.models import Lessons

        lesson = (
            self.session.query(Lessons).filter(Lessons.id == lesson_id).first()
        )
        if lesson is None:
            return
        if lesson_type is not None:
            lesson.type = lesson_type
        if title is not None:
            lesson.title = title
        if description is not None:
            lesson.description = description
        if content is not None:
            lesson.content = content
        if number is not None:
            lesson.number = number
        self.session.flush()

    def find_lesson_number_by_type(
        self, module_id: int, lesson_type: str
    ) -> Optional[int]:
        from sqlalchemy import func

        from app.curriculum.models import Lessons

        row = (
            self.session.query(func.min(Lessons.number))
            .filter(Lessons.module_id == module_id, Lessons.type == lesson_type)
            .scalar()
        )
        return int(row) if row is not None else None

    def shift_module_lessons_above(self, module_id: int, threshold: int) -> int:
        from app.curriculum.models import Lessons

        # Postgres validates the unique (module_id, number) index per row,
        # so `n = n + 1` over consecutive numbers collides. Park rows in a
        # non-conflicting high range first, then bring them back +1.
        _PARK = 10000
        affected = (
            self.session.query(Lessons)
            .filter(
                Lessons.module_id == module_id,
                Lessons.number >= threshold,
            )
            .update(
                {Lessons.number: Lessons.number + _PARK},
                synchronize_session=False,
            )
        )
        if affected:
            self.session.query(Lessons).filter(
                Lessons.module_id == module_id,
                Lessons.number >= threshold + _PARK,
            ).update(
                {Lessons.number: Lessons.number - _PARK + 1},
                synchronize_session=False,
            )
        self.session.flush()
        return int(affected or 0)


def format_report(plan: ImportPlan, files: list, *, dry_run: bool) -> str:
    lines: list = []
    lines.append("# Immersion Lesson Import Report\n")
    lines.append(f"\n_Mode_: **{'dry-run' if dry_run else 'apply'}**\n")
    lines.append("\n## Source files\n")
    for f in files:
        lines.append(f"- `{f}`\n")
    counts = plan.counts
    lines.append("\n## Counts\n")
    for k in sorted(counts):
        lines.append(f"- {k}: **{counts[k]}**\n")
    if plan.errors:
        lines.append("\n## Errors\n")
        for e in plan.errors:
            lines.append(f"- {e}\n")
    lines.append("\n## Changes\n")
    if not plan.changes:
        lines.append("_(no changes)_\n")
    else:
        lines.append("| action | external_key | level | module | type | lesson_id | diff |\n")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |\n")
        for c in plan.changes:
            lines.append(
                f"| {c.action} | {c.external_key} | {c.level} | "
                f"{c.module_number} | {c.lesson_type} | "
                f"{c.lesson_id if c.lesson_id is not None else ''} | "
                f"{','.join(c.diff_fields)} |\n"
            )
    return "".join(lines)


def _resolve_input_paths(files: list, source_dir: Path) -> list:
    resolved: list = []
    for f in files:
        candidate = f
        if not candidate.exists() and not f.is_absolute() and source_dir:
            alt = source_dir / f.name
            if alt.exists():
                candidate = alt
        if not candidate.exists():
            raise FileNotFoundError(str(f))
        resolved.append(candidate)
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent immersion lesson importer."
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="JSON array or JSONL files to import.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan changes without writing anything.",
    )
    parser.add_argument("--level", default=None, help="Filter by CEFR level (e.g. A1).")
    parser.add_argument(
        "--module-id",
        type=int,
        default=None,
        help="Filter by resolved DB module id.",
    )
    parser.add_argument(
        "--lesson-type",
        default=None,
        help="Filter by lesson_type (e.g. dictation).",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Where to look up bare filenames (default: content/immersion).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Markdown report path. Printed to stdout when omitted.",
    )
    parser.add_argument(
        "--include-staging",
        action="store_true",
        help="Also import entries with environment=staging.",
    )
    parser.add_argument(
        "--canonical-modules-dir",
        type=Path,
        default=DEFAULT_CANONICAL_MODULES_DIR,
        help="Directory with canonical source modules (default: module_completed/fixed).",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip content-schema and audio validation.",
    )
    parser.add_argument(
        "--no-source-check",
        action="store_true",
        help="Skip the check that each entry's module exists in --canonical-modules-dir.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation and planning, never write to DB. Returns rc=2 on errors.",
    )
    parser.add_argument(
        "--anchor-after",
        default=None,
        help=(
            "Anchor lesson_type for positional inserts. New lessons are "
            "placed directly after the module's anchor lesson; lessons "
            "below are shifted by +1. Per-entry 'anchor_after' wins."
        ),
    )
    args = parser.parse_args(argv)

    try:
        resolved_paths = _resolve_input_paths(list(args.files), args.source_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: file not found: {exc}", file=sys.stderr)
        return 2

    raw_entries: list = []
    for path in resolved_paths:
        try:
            raw_entries.extend(
                [(path, raw) for raw in load_lessons(path)]
            )
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    parsed: list = []
    parse_errors: list = []
    for i, (path, raw) in enumerate(raw_entries):
        entry, err = parse_entry(raw, source_path=str(path))
        if entry is None:
            parse_errors.append(f"{path} entry #{i}: {err}")
        else:
            parsed.append(entry)
    if parse_errors:
        for err in parse_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 2

    kept, skipped = filter_entries(
        parsed,
        level=args.level,
        lesson_type=args.lesson_type,
        skip_staging=not args.include_staging,
    )

    if not args.no_validate:
        canonical_ids = (
            None if args.no_source_check else load_canonical_module_ids(args.canonical_modules_dir)
        )
        validation_errors = validate_entries(
            kept,
            canonical_module_ids=canonical_ids,
            check_content_schema=True,
        )
        if validation_errors:
            for err in validation_errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 2

    if args.validate_only:
        print(f"validate-only: {len(kept)} entries passed validation")
        return 0

    try:
        from app import create_app
        from app.utils.db import db as flask_db
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot import Flask app: {exc}", file=sys.stderr)
        return 2

    app = create_app()
    with app.app_context():
        repo = DBRepository(flask_db.session)
        plan = plan_import(
            kept,
            repo,
            db_module_id=args.module_id,
            anchor_after=args.anchor_after,
        )
        plan.changes = list(skipped) + plan.changes
        if plan.errors:
            for err in plan.errors:
                print(f"ERROR: {err}", file=sys.stderr)
            text = format_report(plan, resolved_paths, dry_run=True)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(text, encoding="utf-8")
            return 2

        if not args.dry_run:
            apply_plan(kept, plan, repo)
            flask_db.session.commit()

        text = format_report(plan, resolved_paths, dry_run=args.dry_run)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text, encoding="utf-8")
            print(f"wrote {args.report}")
        else:
            print(text)
        counts = plan.counts
        summary = (
            f"create={counts.get('create',0)} update={counts.get('update',0)} "
            f"noop={counts.get('noop',0)} "
            f"skip_no_module={counts.get('skip_no_module',0)} "
            f"skip_filtered={counts.get('skip_filtered',0)} "
            f"skip_environment={counts.get('skip_environment',0)} "
            f"dry_run={args.dry_run}"
        )
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
