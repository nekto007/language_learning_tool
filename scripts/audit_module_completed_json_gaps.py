"""Audit `module_completed/fixed/*.json` against the canonical target sequence.

Compares every source module against the A1/M1 canonical reference and the
canonical lesson sequence from
`docs/plans/2026-05-18-module-completed-json-source-rollout.md`. Produces a
machine-readable JSON report and a human-readable Markdown report containing:

* a current-state survey (file count, lesson-count buckets, lesson-type
  Counter, already-canonical modules, needs-work modules)
* per-module canonical-coverage heatmap (which canonical lesson types are
  present/missing)
* per-file action list (missing types, duplicates, invalid id/number/order,
  missing content fields, missing audio refs, progression flags)
* coarse progression-gap signals: vocabulary size, reading text length,
  audio length, hint density, reused A1-style scripts
* optional DB comparison: DB-only lessons absent from source JSON

Usage:
    python scripts/audit_module_completed_json_gaps.py \
        [--source-dir DIR] [--audio-dir DIR] [--format markdown|json] \
        [--output PATH] [--no-db]

By default the script runs without DB access. Pass `--no-db` to force-skip DB
audit; if no flag is given the script tries to load the Flask app and falls
back to source-only audit on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_AUDIO_DIR = PROJECT_ROOT / "app" / "static" / "audio"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "module_completed_json_gap_report.md"

# Canonical lesson sequence (see plan, "Target lesson sequence").
# `flashcards` is the JSON alias for DB `card`.
CANONICAL_SEQUENCE: tuple[str, ...] = (
    "vocabulary",
    "flashcards",
    "collocation_matching",
    "grammar",
    "sentence_completion",
    "sentence_correction",
    "quiz",
    "reading",
    "idiom",
    "listening_quiz",
    "audio_fill_blank",
    "dictation",
    "dialogue_completion_quiz",
    "ordering_quiz",
    "shadow_reading",
    "flashcards",
    "translation_quiz",
    "translation",
    "listening_immersion",
    "writing_prompt",
    "final_test",
)

# Lesson types that must appear in every module (no level-specific exception).
REQUIRED_CANONICAL_TYPES: tuple[str, ...] = (
    "vocabulary",
    "flashcards",
    "collocation_matching",
    "grammar",
    "sentence_completion",
    "sentence_correction",
    "reading",
    "listening_quiz",
    "audio_fill_blank",
    "dictation",
    "dialogue_completion_quiz",
    "ordering_quiz",
    "shadow_reading",
    "translation_quiz",
    "translation",
    "listening_immersion",
    "writing_prompt",
    "final_test",
)

# Types that may be omitted; flagged as info, not error.
CONDITIONAL_CANONICAL_TYPES: tuple[str, ...] = ("quiz", "idiom")

# Filenames exempt from specific REQUIRED_CANONICAL_TYPES. A1/M1 is the
# pre-rollout reference and intentionally stays at 18 lessons without
# sentence_correction (see plan: "A1/M1 may remain at 18 lessons if some
# intermediate slots are intentionally not used").
MODULE_TYPE_EXEMPTIONS: dict[str, frozenset[str]] = {
    "module_A1_1_greetings.json": frozenset({"sentence_correction"}),
}

# Required `flashcards` count when canonical (one early in the module, one
# review session near the end).
REQUIRED_FLASHCARDS_COUNT: int = 2

# Required content-field shape per lesson type. Each entry is a sequence of
# field-name groups; the lesson must contain at least one field from each
# group. Empty/null values count as missing.
CONTENT_FIELD_RULES: dict[str, tuple[tuple[str, ...], ...]] = {
    "vocabulary": (("vocabulary", "words", "items", "cards"),),
    "flashcards": (("cards", "items"),),
    "grammar": (("rule", "sections", "explanation", "description", "grammar_explanation", "tldr"),),
    "reading": (("text",), ("exercises", "questions")),
    "listening_quiz": (("audio_url", "items", "questions", "exercises"),),
    "listening_immersion": (("audio_url", "audio"), ("text", "transcript")),
    "audio_fill_blank": (("items",),),
    "dictation": (
        ("audio_url", "audio"),
        ("transcript", "audio_text", "gap_text"),
    ),
    "shadow_reading": (("audio_url", "audio"), ("text",)),
    "translation": (("items",),),
    "writing_prompt": (
        ("prompt", "prompt_ru"),
        ("checklist", "min_checklist"),
    ),
    "collocation_matching": (("pairs",),),
    "sentence_completion": (("items",),),
    "sentence_correction": (("items",),),
    "dialogue_completion_quiz": (("items", "questions", "exercises"),),
    "ordering_quiz": (("items", "questions", "exercises"),),
    "translation_quiz": (("items", "questions", "exercises"),),
    "quiz": (("items", "questions", "exercises"),),
    "idiom": (("items",),),
    "final_test": (("questions", "exercises", "sections", "test_sections"),),
}

# Lesson types whose `content` should reference at least one audio asset.
AUDIO_REQUIRING_TYPES: tuple[str, ...] = (
    "listening_immersion",
    "listening_quiz",
    "audio_fill_blank",
    "dictation",
    "shadow_reading",
)

# Audio URL field names that we look at on the content payload or on items.
AUDIO_FIELDS: tuple[str, ...] = ("audio_url", "audio", "audio_clip_url", "url")

# Progression bands: minimum expected reading text length (words) and
# vocabulary-item count per CEFR level. These are coarse; the audit flags
# modules sitting well below the band.
PROGRESSION_BANDS: dict[str, dict[str, int]] = {
    "A1": {"reading_words_min": 60, "vocab_items_min": 8, "listening_words_min": 60},
    "A2": {"reading_words_min": 110, "vocab_items_min": 10, "listening_words_min": 100},
    "B1": {"reading_words_min": 180, "vocab_items_min": 10, "listening_words_min": 160},
    "B2": {"reading_words_min": 260, "vocab_items_min": 12, "listening_words_min": 220},
    "C1": {"reading_words_min": 330, "vocab_items_min": 12, "listening_words_min": 300},
    "C2": {"reading_words_min": 360, "vocab_items_min": 12, "listening_words_min": 320},
}

# Filename pattern: module_<level>_<order>_<slug>.json
_FILENAME_RE = re.compile(
    r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
)

# Static audio root prefix used by JSON `audio_url` values.
_STATIC_AUDIO_PREFIX = "/static/audio/"


@dataclass
class SourceLesson:
    type: str
    title: str
    id_: Any
    number: Any
    order: Any
    raw: dict[str, Any]

    @property
    def content(self) -> dict[str, Any]:
        c = self.raw.get("content")
        return c if isinstance(c, dict) else {}


@dataclass
class SourceModule:
    filename: str
    path: Path
    level: str
    file_order: int
    title: str
    title_en: str
    module_number: Any
    lessons: list[SourceLesson] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def lesson_types(self) -> list[str]:
        return [l.type for l in self.lessons]


@dataclass
class ModuleAuditResult:
    module: SourceModule
    missing_required_types: list[str]
    missing_conditional_types: list[str]
    duplicate_types: dict[str, int]
    invalid_indices: list[str]
    missing_content_fields: list[dict[str, Any]]
    missing_audio_refs: list[dict[str, Any]]
    broken_audio_files: list[dict[str, Any]]
    progression_flags: list[str]
    canonical_coverage: dict[str, bool]
    canonical: bool

    def as_dict(self) -> dict[str, Any]:
        m = self.module
        return {
            "filename": m.filename,
            "level": m.level,
            "file_order": m.file_order,
            "title": m.title,
            "lesson_count": len(m.lessons),
            "parse_error": m.parse_error,
            "canonical": self.canonical,
            "missing_required_types": list(self.missing_required_types),
            "missing_conditional_types": list(self.missing_conditional_types),
            "duplicate_types": dict(self.duplicate_types),
            "invalid_indices": list(self.invalid_indices),
            "missing_content_fields": list(self.missing_content_fields),
            "missing_audio_refs": list(self.missing_audio_refs),
            "broken_audio_files": list(self.broken_audio_files),
            "progression_flags": list(self.progression_flags),
            "canonical_coverage": dict(self.canonical_coverage),
        }


def load_source_modules(source_dir: Path) -> list[SourceModule]:
    """Read every module JSON under `source_dir`. Files that fail to parse are
    returned with `parse_error` set so the audit can flag them."""
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
            modules.append(
                SourceModule(
                    filename=path.name,
                    path=path,
                    level=match.group("level"),
                    file_order=int(match.group("order")),
                    title="",
                    title_en="",
                    module_number=None,
                    lessons=[],
                    parse_error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        module_payload = data.get("module") if isinstance(data, dict) else None
        if not isinstance(module_payload, dict):
            modules.append(
                SourceModule(
                    filename=path.name,
                    path=path,
                    level=match.group("level"),
                    file_order=int(match.group("order")),
                    title="",
                    title_en="",
                    module_number=None,
                    lessons=[],
                    parse_error="missing 'module' key",
                )
            )
            continue
        lessons_raw = module_payload.get("lessons") or []
        lessons: list[SourceLesson] = []
        for entry in lessons_raw:
            if not isinstance(entry, dict):
                continue
            lessons.append(
                SourceLesson(
                    type=str(entry.get("type") or "").strip(),
                    title=str(entry.get("title") or "").strip(),
                    id_=entry.get("id"),
                    number=entry.get("number"),
                    order=entry.get("order"),
                    raw=entry,
                )
            )
        modules.append(
            SourceModule(
                filename=path.name,
                path=path,
                level=match.group("level"),
                file_order=int(match.group("order")),
                title=str(module_payload.get("title") or "").strip(),
                title_en=str(module_payload.get("title_en") or "").strip(),
                module_number=module_payload.get("number")
                if module_payload.get("number") is not None
                else module_payload.get("order"),
                lessons=lessons,
            )
        )
    return modules


def _word_count(text: Any) -> int:
    if isinstance(text, str):
        return len([w for w in re.split(r"\s+", text.strip()) if w])
    if isinstance(text, dict):
        # Reading lessons store `text: {title, lines: [{text, ...}]}`.
        total = 0
        title = text.get("title")
        total += _word_count(title) if title else 0
        lines = text.get("lines")
        if isinstance(lines, list):
            for line in lines:
                if isinstance(line, dict):
                    total += _word_count(line.get("text"))
                elif isinstance(line, str):
                    total += _word_count(line)
        return total
    if isinstance(text, list):
        return sum(_word_count(t) for t in text)
    return 0


def _vocabulary_item_count(content: dict[str, Any]) -> int:
    for key in ("vocabulary", "words", "items", "cards"):
        val = content.get(key)
        if isinstance(val, list):
            return len(val)
    return 0


def _content_field_groups_missing(
    lesson_type: str, content: dict[str, Any]
) -> list[tuple[str, ...]]:
    """Return the field groups that have no non-empty value on `content`."""
    rules = CONTENT_FIELD_RULES.get(lesson_type)
    if not rules:
        return []
    missing: list[tuple[str, ...]] = []
    for group in rules:
        present = False
        for name in group:
            val = content.get(name)
            if val in (None, "", [], {}):
                continue
            present = True
            break
        if not present:
            missing.append(group)
    return missing


def _iter_audio_refs(content: dict[str, Any]) -> Iterable[str]:
    for field_name in AUDIO_FIELDS:
        val = content.get(field_name)
        if isinstance(val, str) and val.strip():
            yield val
    items = content.get("items")
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            for field_name in AUDIO_FIELDS:
                val = it.get(field_name)
                if isinstance(val, str) and val.strip():
                    yield val
    for collection_key in ("questions", "exercises"):
        coll = content.get(collection_key)
        if isinstance(coll, list):
            for entry in coll:
                if not isinstance(entry, dict):
                    continue
                for field_name in AUDIO_FIELDS:
                    val = entry.get(field_name)
                    if isinstance(val, str) and val.strip():
                        yield val


def _resolve_audio_path(audio_ref: str, audio_dir: Path) -> Path | None:
    """Return a filesystem path for `audio_ref` if it points at a static file.

    Accepts:
    * `/static/audio/<name>.mp3` → audio_dir/<name>.mp3
    * `[sound:<name>.mp3]` Anki-style markers → audio_dir/<name>.mp3
    Returns None for unrecognised shapes (e.g. external URLs) so they are not
    flagged as broken.
    """
    if not audio_ref:
        return None
    ref = audio_ref.strip()
    if ref.startswith(_STATIC_AUDIO_PREFIX):
        name = ref[len(_STATIC_AUDIO_PREFIX):]
        return audio_dir / name
    m = re.match(r"^\[sound:(?P<name>[^\]]+)\]$", ref)
    if m:
        return audio_dir / m.group("name")
    return None


def _detect_invalid_indices(lessons: list[SourceLesson]) -> list[str]:
    """Flag id/number/order fields that aren't continuous 1..N or mismatch."""
    issues: list[str] = []
    for expected, lesson in enumerate(lessons, start=1):
        if lesson.id_ is not None:
            if isinstance(lesson.id_, int) and lesson.id_ != expected:
                issues.append(
                    f"lesson #{expected} '{lesson.title}': id={lesson.id_} (expected {expected})"
                )
            elif not isinstance(lesson.id_, int):
                issues.append(
                    f"lesson #{expected} '{lesson.title}': id is non-integer ({lesson.id_!r})"
                )
        if lesson.number is not None and isinstance(lesson.number, int) and lesson.number != expected:
            issues.append(
                f"lesson #{expected} '{lesson.title}': number={lesson.number} (expected {expected})"
            )
        if lesson.order is not None and isinstance(lesson.order, int) and lesson.order != expected:
            issues.append(
                f"lesson #{expected} '{lesson.title}': order={lesson.order} (expected {expected})"
            )
    return issues


def _detect_progression_flags(module: SourceModule) -> list[str]:
    """Return coarse progression signals for this module."""
    flags: list[str] = []
    bands = PROGRESSION_BANDS.get(module.level)
    if not bands:
        return flags
    for lesson in module.lessons:
        c = lesson.content
        if lesson.type == "vocabulary":
            n = _vocabulary_item_count(c)
            if n and n < bands["vocab_items_min"]:
                flags.append(
                    f"vocabulary lesson has {n} items (< {bands['vocab_items_min']} expected for {module.level})"
                )
        if lesson.type == "reading":
            words = _word_count(c.get("text"))
            if words and words < bands["reading_words_min"]:
                flags.append(
                    f"reading text is {words} words (< {bands['reading_words_min']} expected for {module.level})"
                )
        if lesson.type == "shadow_reading":
            words = _word_count(c.get("text"))
            min_words = bands["reading_words_min"] // 3
            if (
                module.level in ("B1", "B2", "C1", "C2")
                and words
                and words < min_words
            ):
                flags.append(
                    f"shadow_reading text is {words} words (< {min_words} expected for {module.level})"
                )
        if lesson.type == "listening_immersion":
            transcript = c.get("text") or c.get("transcript")
            words = _word_count(transcript)
            min_words = bands.get("listening_words_min", 0)
            if min_words and words and words < min_words:
                flags.append(
                    f"listening_immersion transcript is {words} words (< {min_words} expected for {module.level})"
                )
    return flags


def audit_module(module: SourceModule, audio_dir: Path | None) -> ModuleAuditResult:
    """Build a full per-module audit result."""
    if module.parse_error is not None:
        return ModuleAuditResult(
            module=module,
            missing_required_types=list(REQUIRED_CANONICAL_TYPES),
            missing_conditional_types=list(CONDITIONAL_CANONICAL_TYPES),
            duplicate_types={},
            invalid_indices=[f"parse error: {module.parse_error}"],
            missing_content_fields=[],
            missing_audio_refs=[],
            broken_audio_files=[],
            progression_flags=[],
            canonical_coverage={t: False for t in REQUIRED_CANONICAL_TYPES},
            canonical=False,
        )

    type_counts: Counter = Counter(module.lesson_types)

    exemptions = MODULE_TYPE_EXEMPTIONS.get(module.filename, frozenset())
    missing_required: list[str] = []
    for t in REQUIRED_CANONICAL_TYPES:
        if t in exemptions:
            continue
        expected = REQUIRED_FLASHCARDS_COUNT if t == "flashcards" else 1
        if type_counts.get(t, 0) < expected:
            missing_required.append(t)

    missing_conditional: list[str] = [
        t for t in CONDITIONAL_CANONICAL_TYPES if t not in type_counts
    ]

    # Duplicates: any required type appearing more than once (except `flashcards`
    # which is expected twice). Any conditional type counts a duplicate if >1.
    duplicates: dict[str, int] = {}
    for t, n in type_counts.items():
        if t == "flashcards":
            if n > REQUIRED_FLASHCARDS_COUNT:
                duplicates[t] = n
            continue
        if t in REQUIRED_CANONICAL_TYPES and n > 1:
            duplicates[t] = n
        elif t in CONDITIONAL_CANONICAL_TYPES and n > 1:
            duplicates[t] = n

    invalid_indices = _detect_invalid_indices(module.lessons)

    missing_content_fields: list[dict[str, Any]] = []
    missing_audio_refs: list[dict[str, Any]] = []
    broken_audio_files: list[dict[str, Any]] = []

    for idx, lesson in enumerate(module.lessons, start=1):
        content = lesson.content
        groups = _content_field_groups_missing(lesson.type, content)
        if groups:
            missing_content_fields.append(
                {
                    "index": idx,
                    "type": lesson.type,
                    "title": lesson.title,
                    "missing_field_groups": [list(g) for g in groups],
                }
            )
        if lesson.type in AUDIO_REQUIRING_TYPES:
            refs = list(_iter_audio_refs(content))
            if not refs:
                missing_audio_refs.append(
                    {"index": idx, "type": lesson.type, "title": lesson.title}
                )
            elif audio_dir is not None:
                for ref in refs:
                    resolved = _resolve_audio_path(ref, audio_dir)
                    if resolved is None:
                        continue
                    if not resolved.exists():
                        broken_audio_files.append(
                            {
                                "index": idx,
                                "type": lesson.type,
                                "title": lesson.title,
                                "ref": ref,
                                "expected_path": str(resolved),
                            }
                        )

    progression_flags = _detect_progression_flags(module)

    canonical_coverage: dict[str, bool] = {}
    for t in REQUIRED_CANONICAL_TYPES:
        if t in exemptions:
            canonical_coverage[t] = True
            continue
        if t == "flashcards":
            canonical_coverage[t] = (
                type_counts.get("flashcards", 0) >= REQUIRED_FLASHCARDS_COUNT
            )
        else:
            canonical_coverage[t] = type_counts.get(t, 0) >= 1

    canonical = (
        not missing_required
        and not invalid_indices
        and not missing_content_fields
        and not missing_audio_refs
        and not broken_audio_files
    )

    return ModuleAuditResult(
        module=module,
        missing_required_types=missing_required,
        missing_conditional_types=missing_conditional,
        duplicate_types=duplicates,
        invalid_indices=invalid_indices,
        missing_content_fields=missing_content_fields,
        missing_audio_refs=missing_audio_refs,
        broken_audio_files=broken_audio_files,
        progression_flags=progression_flags,
        canonical_coverage=canonical_coverage,
        canonical=canonical,
    )


def build_audit(
    source_dir: Path,
    audio_dir: Path | None = None,
    db_session=None,
) -> dict[str, Any]:
    """Build the full audit report dictionary."""
    modules = load_source_modules(source_dir)
    results = [audit_module(m, audio_dir) for m in modules]

    lesson_count_buckets: Counter = Counter(len(m.lessons) for m in modules)
    lesson_type_counter: Counter = Counter()
    for m in modules:
        for l in m.lessons:
            if l.type:
                lesson_type_counter[l.type] += 1

    canonical_files = [r.module.filename for r in results if r.canonical]
    needs_work_files = [r.module.filename for r in results if not r.canonical]

    survey = {
        "source_dir": str(source_dir),
        "audio_dir": str(audio_dir) if audio_dir is not None else None,
        "total_files": len(modules),
        "lesson_count_buckets": dict(lesson_count_buckets),
        "lesson_type_counter": dict(lesson_type_counter),
        "canonical_files": canonical_files,
        "needs_work_files": needs_work_files,
    }

    audit: dict[str, Any] = {
        "survey": survey,
        "canonical_sequence": list(CANONICAL_SEQUENCE),
        "required_canonical_types": list(REQUIRED_CANONICAL_TYPES),
        "conditional_canonical_types": list(CONDITIONAL_CANONICAL_TYPES),
        "modules": [r.as_dict() for r in results],
    }

    if db_session is not None:
        try:
            audit["db"] = _audit_db(modules, db_session)
        except Exception as exc:  # noqa: BLE001 — surface DB errors in report
            audit["db_error"] = f"{type(exc).__name__}: {exc}"

    return audit


def _audit_db(modules: list[SourceModule], db_session) -> dict[str, Any]:
    """Compare source modules against DB curriculum lessons.

    For each (level, file_order), list DB lessons that don't appear in the
    matched source module (by lesson type and title). Returns:

    {
        "matched_modules": int,
        "db_only_lessons": [{level, file_order, db_lesson_type, db_title, db_id}],
        "source_only_modules": [{level, file_order, filename}],
        "db_only_modules":     [{level, number, db_id, db_title}],
    }
    """
    from sqlalchemy import func  # noqa: F401

    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session.session

    rows = (
        session.query(Module.id, Module.number, Module.title, CEFRLevel.code)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .all()
    )
    db_modules = [{"id": r[0], "number": r[1], "title": r[2], "level": r[3]} for r in rows]

    db_by_level_number: dict[tuple[str, int], dict[str, Any]] = {}
    for m in db_modules:
        if m["number"] is None:
            continue
        db_by_level_number[(m["level"], int(m["number"]))] = m

    matched_count = 0
    db_only_lessons: list[dict[str, Any]] = []
    source_only_modules: list[dict[str, Any]] = []
    matched_db_ids: set[int] = set()

    for module in modules:
        match = db_by_level_number.get((module.level, module.file_order))
        if match is None:
            source_only_modules.append(
                {
                    "level": module.level,
                    "file_order": module.file_order,
                    "filename": module.filename,
                }
            )
            continue
        matched_db_ids.add(match["id"])
        matched_count += 1

        # Look up DB lessons for this module.
        lesson_rows = (
            session.query(Lessons.id, Lessons.type, Lessons.title)
            .filter(Lessons.module_id == match["id"])
            .all()
        )
        # Normalise source lesson signatures (type, title).
        src_signatures = {(l.type, l.title.strip()) for l in module.lessons}
        # JSON `flashcards` maps to DB `card`.
        src_signatures.update({("card", title) for (t, title) in src_signatures if t == "flashcards"})

        for db_id, db_type, db_title in lesson_rows:
            sig = (db_type or "", (db_title or "").strip())
            if sig in src_signatures:
                continue
            db_only_lessons.append(
                {
                    "level": module.level,
                    "file_order": module.file_order,
                    "db_lesson_type": db_type,
                    "db_title": db_title,
                    "db_id": db_id,
                }
            )

    db_only_modules = [
        {
            "level": m["level"],
            "number": m["number"],
            "db_id": m["id"],
            "db_title": m["title"],
        }
        for m in db_modules
        if m["id"] not in matched_db_ids
    ]

    return {
        "matched_modules": matched_count,
        "db_only_lessons": db_only_lessons,
        "source_only_modules": source_only_modules,
        "db_only_modules": db_only_modules,
    }


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_(no rows)_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        out += "| " + " | ".join("" if v is None else str(v) for v in row) + " |\n"
    return out


def format_markdown(audit: dict[str, Any]) -> str:
    survey = audit["survey"]
    modules = audit["modules"]

    out: list[str] = []
    out.append("# module_completed/fixed JSON gap report\n\n")
    out.append(f"_Source directory_: `{survey['source_dir']}`\n")
    if survey.get("audio_dir"):
        out.append(f"_Audio directory_: `{survey['audio_dir']}`\n")
    out.append("\n")

    out.append("## Current-state survey\n\n")
    out.append(f"- Total source files: **{survey['total_files']}**\n")
    out.append("- Lesson count distribution:\n")
    for cnt, n in sorted(survey["lesson_count_buckets"].items()):
        out.append(f"  - {cnt} lessons: {n} file(s)\n")
    out.append(f"- Already-canonical files: **{len(survey['canonical_files'])}**\n")
    out.append(f"- Needs-work files: **{len(survey['needs_work_files'])}**\n\n")

    out.append("### Lesson type counter (all source files)\n\n")
    type_rows = sorted(survey["lesson_type_counter"].items(), key=lambda kv: (-kv[1], kv[0]))
    out.append(_md_table(["lesson_type", "count"], type_rows))
    out.append("\n")

    if survey["canonical_files"]:
        out.append("### Already-canonical files\n\n")
        for fn in survey["canonical_files"]:
            out.append(f"- `{fn}`\n")
        out.append("\n")

    out.append("## Per-module canonical coverage heatmap\n\n")
    headers = ["filename", "level", "lessons"] + list(REQUIRED_CANONICAL_TYPES) + ["status"]
    rows: list[list[Any]] = []
    for m in modules:
        row: list[Any] = [m["filename"], m["level"], m["lesson_count"]]
        coverage = m["canonical_coverage"]
        for t in REQUIRED_CANONICAL_TYPES:
            row.append("✓" if coverage.get(t) else "·")
        row.append("OK" if m["canonical"] else "WORK")
        rows.append(row)
    out.append(_md_table(headers, rows))
    out.append("\n")

    out.append("## Per-file action list\n\n")
    work_modules = [m for m in modules if not m["canonical"]]
    if not work_modules:
        out.append("_All source files match the canonical target._\n")
    for m in work_modules:
        out.append(f"### `{m['filename']}` ({m['level']}, {m['lesson_count']} lessons)\n")
        if m["parse_error"]:
            out.append(f"- **parse error**: {m['parse_error']}\n")
        if m["missing_required_types"]:
            out.append(
                "- missing required types: "
                + ", ".join(f"`{t}`" for t in m["missing_required_types"])
                + "\n"
            )
        if m["missing_conditional_types"]:
            out.append(
                "- missing conditional types: "
                + ", ".join(f"`{t}`" for t in m["missing_conditional_types"])
                + "\n"
            )
        if m["duplicate_types"]:
            dups = ", ".join(f"`{t}`×{n}" for t, n in m["duplicate_types"].items())
            out.append(f"- duplicate types: {dups}\n")
        if m["invalid_indices"]:
            out.append("- invalid id/number/order:\n")
            for issue in m["invalid_indices"][:10]:
                out.append(f"  - {issue}\n")
            if len(m["invalid_indices"]) > 10:
                out.append(f"  - _…and {len(m['invalid_indices']) - 10} more_\n")
        if m["missing_content_fields"]:
            out.append("- missing content fields:\n")
            for entry in m["missing_content_fields"][:10]:
                groups = "; ".join(
                    "/".join(g) for g in entry["missing_field_groups"]
                )
                out.append(
                    f"  - lesson #{entry['index']} `{entry['type']}` '{entry['title']}': {groups}\n"
                )
            if len(m["missing_content_fields"]) > 10:
                out.append(
                    f"  - _…and {len(m['missing_content_fields']) - 10} more_\n"
                )
        if m["missing_audio_refs"]:
            out.append("- missing audio refs:\n")
            for entry in m["missing_audio_refs"][:10]:
                out.append(
                    f"  - lesson #{entry['index']} `{entry['type']}` '{entry['title']}'\n"
                )
        if m["broken_audio_files"]:
            out.append("- broken audio refs (file not found):\n")
            for entry in m["broken_audio_files"][:10]:
                out.append(
                    f"  - lesson #{entry['index']} `{entry['type']}`: `{entry['ref']}`\n"
                )
            if len(m["broken_audio_files"]) > 10:
                out.append(
                    f"  - _…and {len(m['broken_audio_files']) - 10} more_\n"
                )
        if m["progression_flags"]:
            out.append("- progression flags:\n")
            for flag in m["progression_flags"]:
                out.append(f"  - {flag}\n")
        out.append("\n")

    if "db_error" in audit:
        out.append("## DB comparison\n\n")
        out.append(f"_DB audit skipped: {audit['db_error']}_\n")
    elif "db" in audit:
        db = audit["db"]
        out.append("## DB comparison\n\n")
        out.append(f"- Matched (level+file_order) modules: **{db['matched_modules']}**\n")
        out.append(f"- Source-only modules: **{len(db['source_only_modules'])}**\n")
        out.append(f"- DB-only modules: **{len(db['db_only_modules'])}**\n")
        out.append(f"- DB-only lessons absent from source: **{len(db['db_only_lessons'])}**\n\n")
        if db["db_only_lessons"]:
            out.append("### DB-only lessons absent from source JSON\n\n")
            rows = []
            for entry in db["db_only_lessons"][:200]:
                rows.append(
                    [
                        entry["level"],
                        entry["file_order"],
                        entry["db_lesson_type"],
                        entry["db_title"],
                        entry["db_id"],
                    ]
                )
            out.append(_md_table(["level", "file_order", "type", "title", "db_id"], rows))
            if len(db["db_only_lessons"]) > 200:
                out.append(f"_…and {len(db['db_only_lessons']) - 200} more_\n")
        if db["source_only_modules"]:
            out.append("\n### Source modules with no DB counterpart\n\n")
            rows = [
                [m["level"], m["file_order"], m["filename"]]
                for m in db["source_only_modules"]
            ]
            out.append(_md_table(["level", "file_order", "filename"], rows))
        if db["db_only_modules"]:
            out.append("\n### DB modules with no source file\n\n")
            rows = [
                [m["level"], m["number"], m["db_id"], m["db_title"]]
                for m in db["db_only_modules"]
            ]
            out.append(_md_table(["level", "number", "db_id", "title"], rows))

    return "".join(out)


def format_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=True)


def _try_get_db_session():
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
    parser = argparse.ArgumentParser(
        description="Audit module_completed/fixed JSON files against canonical target."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=DEFAULT_AUDIO_DIR,
        help="Static audio directory used to verify referenced audio files exist.",
    )
    parser.add_argument(
        "--no-audio-check",
        action="store_true",
        help="Skip filesystem existence checks for referenced audio.",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-db", action="store_true", help="Skip DB comparison.")
    args = parser.parse_args(argv)

    audio_dir = None if args.no_audio_check else args.audio_dir

    db_session = None
    app = None
    if not args.no_db:
        app, db_session = _try_get_db_session()

    if app is not None and db_session is not None:
        with app.app_context():
            audit = build_audit(args.source_dir, audio_dir=audio_dir, db_session=db_session)
    else:
        audit = build_audit(args.source_dir, audio_dir=audio_dir, db_session=None)
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
