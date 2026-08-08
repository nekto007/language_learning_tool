"""Validate `module_completed/fixed/*.json` and emit a portability report.

This is the gating validator for the source-of-truth rollout (plan
``docs/plans/2026-05-18-module-completed-json-source-rollout.md``, Task 6).
Where the gap audit (`audit_module_completed_json_gaps.py`) inventories what
is missing, this script checks that what IS present is correctly shaped,
references real assets, has no placeholder/stub copy, and obeys coarse
progression bands.

Validation axes
---------------

1. **JSON parse.** Every `module_*.json` must parse and contain a `module`
   object with a `lessons` array.
2. **Local index continuity.** `id`, `number`, and `order` must form
   contiguous 1..N sequences (no gaps, no duplicates, no integers out of
   range). Missing values are an error.
3. **Schema coverage.** Each lesson is loaded through the existing
   Marshmallow schemas in `app/curriculum/validators.py` (via
   `LessonContentValidator`). Lesson types unknown to the validator are
   reported separately as `info` so source-only types like `flashcards`
   alias (handled by `card`) still surface.
4. **Audio references.** Every audio reference encountered is checked
   against `app/static/audio/`. Missing files are blocking errors. Audio
   references that don't point at `/static/audio/...` (external URLs) are
   recorded as `info`.
5. **Progression bands.** Coarse text-length / audio-presence checks per
   CEFR level. Numbers below the band become non-blocking `warnings`.
6. **Placeholder/stub detection.** A small fixed dictionary catches "TODO",
   "FIXME", "Lorem ipsum", "placeholder", "Сделайте вопрос", and other
   known stub phrasings. Empty prompts, empty answers, blank checklists,
   and matching pairs missing a side count as blocking errors.
7. **Final-test coverage.** Final-test sections must use the modern prompt
   phrasing (no `Сделайте вопрос`). Matching-pair shape is validated when
   a matching question is present. A warning is emitted when no matching
   exercise exists at all, since complete final-test coverage (including
   matching pairs) is a goal that may be deferred for some modules.

The script also emits an audio manifest — a list of every static audio file
that the source JSON references — so production transfer can copy the right
assets without manually grepping audio_url values.

Usage::

    python scripts/validate_module_completed_json.py \\
        [--source-dir DIR] [--audio-dir DIR] \\
        [--validation-output PATH] [--manifest-output PATH] \\
        [--strict] [--no-audio-check]

The script exits with status 0 unless `--strict` is given and any module has
blocking errors, in which case it exits 1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Same blind spot as CNT-011: run as `python scripts/validate_module_completed_json.py`
# the interpreter puts scripts/ on sys.path[0], `import app` fails, and every lesson
# silently degrades to `schema-skipped` while the run still looks healthy.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCE_DIR = PROJECT_ROOT / "module_completed" / "fixed"
DEFAULT_AUDIO_DIR = PROJECT_ROOT / "app" / "static" / "audio"
DEFAULT_VALIDATION_REPORT = PROJECT_ROOT / "reports" / "module_completed_json_validation.md"
DEFAULT_MANIFEST_REPORT = PROJECT_ROOT / "reports" / "module_completed_audio_manifest.md"

# Filename pattern: module_<level>_<order>_<slug>.json
_FILENAME_RE = re.compile(
    r"^module_(?P<level>[A-C][0-9])_(?P<order>\d+)_(?P<slug>.+)\.json$"
)

# Audio field names — same shape as the gap audit. Note that on quiz items
# the audio reference may live alongside `question`/`options`, so we walk
# all dicts we find inside `items`/`questions`/`exercises`.
AUDIO_FIELDS: tuple[str, ...] = ("audio_url", "audio", "audio_clip_url", "url")

# Keys that mean "audio" at any depth. `url` is deliberately absent: it is a
# generic key and only carries audio at the top level of a lesson payload.
NESTED_AUDIO_FIELDS: tuple[str, ...] = ("audio_url", "audio", "audio_clip_url")

# Lesson types that must reference at least one audio asset somewhere in
# their content payload. Mirrors gap-audit logic.
AUDIO_REQUIRING_TYPES: tuple[str, ...] = (
    "listening_immersion",
    "listening_quiz",
    "audio_fill_blank",
    "dictation",
    "shadow_reading",
)

# Lesson types whose content is loaded through `LessonContentValidator`. The
# `flashcards` source-side alias maps to DB `card` — we run it through
# `CardContentSchema` directly. Anything not listed is reported as `info`
# (unknown lesson type) but not blocking, so we don't break on legitimately
# new types added after the contract doc.
SCHEMA_LESSON_TYPES: tuple[str, ...] = (
    "vocabulary",
    "flashcards",
    "grammar",
    "quiz",
    "ordering_quiz",
    "translation_quiz",
    "listening_quiz",
    "dialogue_completion_quiz",
    "matching",
    "text",
    "reading",
    "listening_immersion",
    "card",
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
    "final_test",
)

# Map source-side alias → DB-side schema key (used to look up the right
# Marshmallow schema in LessonContentValidator.SCHEMAS).
SCHEMA_TYPE_ALIASES: dict[str, str] = {
    "flashcards": "card",
}

# Progression bands. Audio-presence is taken care of by the audio-ref check;
# these numbers cover transcript / reading text length per CEFR level. They
# are intentionally coarse — modules sitting below the band become
# `warnings`, not errors.
PROGRESSION_BANDS: dict[str, dict[str, int]] = {
    "A0": {"reading_words_min": 40, "listening_words_min": 40, "vocab_items_min": 6},
    "A1": {"reading_words_min": 60, "listening_words_min": 60, "vocab_items_min": 8},
    "A2": {"reading_words_min": 110, "listening_words_min": 100, "vocab_items_min": 10},
    "B1": {"reading_words_min": 180, "listening_words_min": 160, "vocab_items_min": 10},
    "B2": {"reading_words_min": 260, "listening_words_min": 220, "vocab_items_min": 12},
    "C1": {"reading_words_min": 330, "listening_words_min": 300, "vocab_items_min": 12},
    "C2": {"reading_words_min": 360, "listening_words_min": 320, "vocab_items_min": 12},
}

# Known placeholder / stub markers. Matched case-insensitively against the
# stringified content payload. Any hit produces a blocking error so we don't
# ship template scaffolding to production.
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "lorem ipsum",
    "placeholder",
    "todo:",
    "tbd",
    "fixme",
    "xxx ",
    "сделайте вопрос",
    "вставьте текст",
    "вставьте перевод",
    "вставьте слово",
)

# Final-test stub markers — phrasing that the Task 4 quality pass replaced
# but that we want to actively refuse from now on.
FINAL_TEST_STUB_MARKERS: tuple[str, ...] = (
    "сделайте вопрос",
    "сделать вопрос",
    "сделайте отрицание",
)

# Static audio root prefix used by JSON `audio_url` / `audio_clip_url`.
_STATIC_AUDIO_PREFIX = "/static/audio/"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single validation finding for a lesson or module.

    severity:
        * "error"   → blocking, fails strict mode
        * "warning" → progression-style soft alert
        * "info"    → record-only (external URL, unknown type, etc.)
    """

    severity: str
    code: str
    message: str
    lesson_index: int | None = None
    lesson_type: str | None = None
    field_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "lesson_index": self.lesson_index,
            "lesson_type": self.lesson_type,
            "field_path": self.field_path,
        }


@dataclass
class ModuleValidation:
    filename: str
    path: Path
    level: str
    file_order: int
    lesson_count: int
    findings: list[Finding] = field(default_factory=list)
    audio_refs: list[dict[str, Any]] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "info"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "level": self.level,
            "file_order": self.file_order,
            "lesson_count": self.lesson_count,
            "parse_error": self.parse_error,
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
            "infos": [f.as_dict() for f in self.infos],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_count(text: Any) -> int:
    if isinstance(text, str):
        return len([w for w in re.split(r"\s+", text.strip()) if w])
    if isinstance(text, dict):
        # Reading lessons store `text: {title, lines: [{text, ...}]}`.
        total = 0
        title = text.get("title")
        if title:
            total += _word_count(title)
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


def _vocab_count(content: dict[str, Any]) -> int:
    for key in ("vocabulary", "words", "items", "cards"):
        val = content.get(key)
        if isinstance(val, list):
            return len(val)
    return 0


def _iter_strings(payload: Any, path: str = "") -> Iterable[tuple[str, str]]:
    """Walk a nested JSON-like payload and yield (path, string_value) tuples."""
    if isinstance(payload, str):
        yield path or "<root>", payload
    elif isinstance(payload, dict):
        for k, v in payload.items():
            yield from _iter_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            yield from _iter_strings(v, f"{path}[{i}]")


def _iter_audio_refs(content: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """Yield (field_path, audio_ref) for every audio reference in content.

    Fully recursive. The previous version only visited the top level plus
    `items`/`questions`/`exercises` and `test_sections[].exercises[]`, which left
    `vocabulary[].audio`, `cards[].audio`, `sections[].table[].audio`,
    `text.lines[].audio` and `sections[].rules[].audio` unseen — 83% of all audio
    references in the corpus, and every one of the 1570 missing pronunciation
    clips. The walker also accepts the list form (`audio: [...]`), which the old
    code ignored even on the paths it did visit (audit CNT-004).
    """
    # `url` is generic; honour it only where it has always meant audio.
    for field_name in AUDIO_FIELDS:
        if field_name in NESTED_AUDIO_FIELDS:
            continue
        val = content.get(field_name)
        if isinstance(val, str) and val.strip():
            yield field_name, val

    yield from _walk_audio_refs(content, "")


def _walk_audio_refs(node: Any, path: str) -> Iterable[tuple[str, str]]:
    """Recursive half of :func:`_iter_audio_refs`."""
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            if key in NESTED_AUDIO_FIELDS:
                yield from _emit_audio_values(value, child_path)
                continue
            yield from _walk_audio_refs(value, child_path)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_audio_refs(value, f"{path}[{i}]")


def _emit_audio_values(value: Any, path: str) -> Iterable[tuple[str, str]]:
    """Yield audio refs from a `str`, a `list[str]`, or a nested container."""
    if isinstance(value, str):
        if value.strip():
            yield path, value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _emit_audio_values(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        # e.g. {"audio": {"url": "..."}} — keep walking rather than dropping it.
        yield from _walk_audio_refs(value, path)


def _resolve_audio_path(audio_ref: str, audio_dir: Path) -> tuple[Path | None, str]:
    """Return (filesystem_path, kind) for `audio_ref`.

    `kind` is one of:
      * `static` — `/static/audio/<name>` → audio_dir/<name>
      * `anki`   — `[sound:<name>]` → audio_dir/<name>
      * `external` — anything else (returned with path=None)
    """
    if not audio_ref:
        return None, "external"
    ref = audio_ref.strip()
    if ref.startswith(_STATIC_AUDIO_PREFIX):
        name = ref[len(_STATIC_AUDIO_PREFIX):]
        return audio_dir / name, "static"
    m = re.match(r"^\[sound:(?P<name>[^\]]+)\]$", ref)
    if m:
        return audio_dir / m.group("name"), "anki"
    return None, "external"


def _content_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


# ---------------------------------------------------------------------------
# Schema-driven lesson validation
# ---------------------------------------------------------------------------


def _validate_lesson_schema(lesson_type: str, content: Any) -> list[str]:
    """Run the lesson content through LessonContentValidator if known.

    Returns a list of error strings (empty if valid). The validator may raise
    ValidationError; we flatten its `.messages` into one human-readable line
    per field.
    """
    try:
        # Imported lazily so the script does not require Flask at module-load
        # time. The validators module itself only depends on marshmallow.
        from app.curriculum.validators import LessonContentValidator
    except Exception as exc:  # noqa: BLE001
        return [f"validator-import-failed: {type(exc).__name__}: {exc}"]

    if lesson_type not in SCHEMA_LESSON_TYPES:
        return []  # caller flags as unknown

    schema_key = SCHEMA_TYPE_ALIASES.get(lesson_type, lesson_type)
    if schema_key not in LessonContentValidator.SCHEMAS:
        return []

    try:
        LessonContentValidator.validate(schema_key, content)
        return []
    except Exception as exc:  # noqa: BLE001 — flatten ValidationError too
        messages: list[str] = []
        msg_attr = getattr(exc, "messages", None)
        if isinstance(msg_attr, dict):
            for k, v in msg_attr.items():
                if isinstance(v, list):
                    for item in v:
                        messages.append(f"{k}: {item}")
                else:
                    messages.append(f"{k}: {v}")
        elif isinstance(msg_attr, list):
            messages.extend(str(m) for m in msg_attr)
        else:
            messages.append(f"{type(exc).__name__}: {exc}")
        return messages


# ---------------------------------------------------------------------------
# Per-lesson placeholder / stub detection
# ---------------------------------------------------------------------------


_PLACEHOLDER_PATH_EXEMPT_TAILS: tuple[str, ...] = (
    ".section",
    ".title",
)


def _detect_placeholders(
    content: Any,
    skip_markers: tuple[str, ...] = (),
) -> list[tuple[str, str, str]]:
    """Return list of (field_path, marker, snippet) for every placeholder hit.

    Snippet is the matched string truncated to ~80 chars to keep the report
    readable. Section headings (`.section`, `.title`) are exempt — they
    legitimately describe what the section contains (e.g. "Вопросы — сделайте
    вопросительную форму") rather than being instructional stubs.

    ``skip_markers`` lets callers exclude markers that are handled by a more
    specific validator (e.g. ``FINAL_TEST_STUB_MARKERS`` are caught with better
    context by ``_validate_final_test``, so passing them here avoids
    double-counting the same finding).
    """
    active_markers = tuple(m for m in PLACEHOLDER_MARKERS if m not in skip_markers)
    hits: list[tuple[str, str, str]] = []
    for path, value in _iter_strings(content):
        if any(path.endswith(tail) for tail in _PLACEHOLDER_PATH_EXEMPT_TAILS):
            continue
        lower = value.lower()
        for marker in active_markers:
            if marker in lower:
                snippet = value.strip()
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                hits.append((path, marker, snippet))
                break  # one marker per string is enough
    return hits


def _detect_empty_required_fields(
    lesson_type: str, content: dict[str, Any]
) -> list[tuple[str, str]]:
    """Detect empty/missing fields that should be non-empty for the given type.

    The Marshmallow schema usually catches missing fields, but it allows
    empty strings/lists in many places (for forwards-compat). Production
    transfer wants those flagged anyway.
    """
    issues: list[tuple[str, str]] = []
    if lesson_type == "writing_prompt":
        if _content_is_empty(content.get("prompt")):
            issues.append(("prompt", "writing_prompt requires non-empty prompt"))
        checklist = content.get("checklist")
        if isinstance(checklist, list):
            blanks = [i for i, c in enumerate(checklist) if not isinstance(c, str) or not c.strip()]
            if blanks:
                issues.append(
                    ("checklist", f"writing_prompt checklist has {len(blanks)} blank entries")
                )
    if lesson_type == "audio_fill_blank":
        items = content.get("items") or []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if _content_is_empty(item.get("answer")):
                issues.append((f"items[{i}].answer", "audio_fill_blank item missing answer"))
            if _content_is_empty(item.get("text_with_gap")) and _content_is_empty(item.get("sentence")):
                issues.append((f"items[{i}].text_with_gap", "audio_fill_blank item missing sentence/gap text"))
    if lesson_type == "sentence_completion":
        items = content.get("items") or []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if _content_is_empty(item.get("answer")):
                issues.append((f"items[{i}].answer", "sentence_completion item missing answer"))
            # An empty leading `prompt` is legal: when the gap opens the sentence the
            # text lives in `context` / `prompt_after`, and the template renders it that
            # way (curriculum/lessons/sentence_completion.html). Only a row with no text
            # at all is broken. See CNT-012.
            if (
                _content_is_empty(item.get("prompt"))
                and _content_is_empty(item.get("prompt_after"))
                and _content_is_empty(item.get("context"))
            ):
                issues.append(
                    (f"items[{i}].prompt", "sentence_completion item has no prompt/prompt_after/context text")
                )
    if lesson_type == "sentence_correction":
        items = content.get("items") or []
        if items:
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                if _content_is_empty(item.get("incorrect_sentence")):
                    issues.append((f"items[{i}].incorrect_sentence", "sentence_correction item missing incorrect_sentence"))
                if _content_is_empty(item.get("correct_sentence")):
                    issues.append((f"items[{i}].correct_sentence", "sentence_correction item missing correct_sentence"))
    if lesson_type == "translation":
        items = content.get("items") or []
        if items:
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                if _content_is_empty(item.get("english")):
                    issues.append((f"items[{i}].english", "translation item missing english"))
                if _content_is_empty(item.get("russian")):
                    issues.append((f"items[{i}].russian", "translation item missing russian"))
    if lesson_type == "collocation_matching":
        pairs = content.get("pairs") or []
        for i, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                continue
            if _content_is_empty(pair.get("phrase")):
                issues.append((f"pairs[{i}].phrase", "collocation_matching pair missing phrase"))
            if _content_is_empty(pair.get("translation")):
                issues.append((f"pairs[{i}].translation", "collocation_matching pair missing translation"))
    if lesson_type == "matching":
        pairs = content.get("pairs") or []
        for i, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                continue
            has_left_right = bool(pair.get("left")) and bool(pair.get("right"))
            has_en_ru = bool(pair.get("english")) and bool(pair.get("russian"))
            if not has_left_right and not has_en_ru:
                issues.append((f"pairs[{i}]", "matching pair missing both halves"))
    return issues


# ---------------------------------------------------------------------------
# Index / structural validation
# ---------------------------------------------------------------------------


def _validate_indices(lessons: list[dict[str, Any]]) -> list[Finding]:
    """Verify id/number/order form contiguous 1..N sequences."""
    findings: list[Finding] = []
    if not lessons:
        findings.append(
            Finding("error", "empty-lessons", "module has zero lessons")
        )
        return findings

    n = len(lessons)
    for idx, lesson in enumerate(lessons, start=1):
        for field_name in ("id", "number", "order"):
            value = lesson.get(field_name)
            if value is None:
                findings.append(
                    Finding(
                        "error",
                        "missing-index",
                        f"lesson #{idx}: missing `{field_name}`",
                        lesson_index=idx,
                        lesson_type=lesson.get("type"),
                        field_path=field_name,
                    )
                )
                continue
            if not isinstance(value, int):
                findings.append(
                    Finding(
                        "error",
                        "non-integer-index",
                        f"lesson #{idx}: `{field_name}`={value!r} is not an integer",
                        lesson_index=idx,
                        lesson_type=lesson.get("type"),
                        field_path=field_name,
                    )
                )
                continue
            if value != idx:
                findings.append(
                    Finding(
                        "error",
                        "non-contiguous-index",
                        f"lesson #{idx}: `{field_name}`={value} (expected {idx})",
                        lesson_index=idx,
                        lesson_type=lesson.get("type"),
                        field_path=field_name,
                    )
                )

    # Duplicate detection via Counter.
    for field_name in ("id", "number", "order"):
        values = [l.get(field_name) for l in lessons if isinstance(l.get(field_name), int)]
        if not values:
            continue
        dups = [v for v, count in Counter(values).items() if count > 1]
        for v in sorted(dups):
            findings.append(
                Finding(
                    "error",
                    "duplicate-index",
                    f"`{field_name}` value {v} appears more than once",
                    field_path=field_name,
                )
            )
    return findings


def _validate_progression(level: str, lessons: list[dict[str, Any]]) -> list[Finding]:
    """Soft warnings for under-sized text content per CEFR level."""
    findings: list[Finding] = []
    band = PROGRESSION_BANDS.get(level)
    if not band:
        return findings
    for idx, lesson in enumerate(lessons, start=1):
        ltype = lesson.get("type")
        c = lesson.get("content") if isinstance(lesson.get("content"), dict) else {}
        if ltype == "vocabulary":
            n = _vocab_count(c)
            if n and n < band["vocab_items_min"]:
                findings.append(
                    Finding(
                        "warning",
                        "vocab-below-band",
                        f"vocabulary has {n} items (< {band['vocab_items_min']} for {level})",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )
        if ltype == "reading":
            words = _word_count(c.get("text"))
            if words and words < band["reading_words_min"]:
                findings.append(
                    Finding(
                        "warning",
                        "reading-below-band",
                        f"reading text is {words} words (< {band['reading_words_min']} for {level})",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )
        if ltype == "listening_immersion":
            transcript = c.get("text") or c.get("transcript")
            words = _word_count(transcript)
            min_words = band.get("listening_words_min", 0)
            if min_words and words and words < min_words:
                findings.append(
                    Finding(
                        "warning",
                        "listening-below-band",
                        f"listening_immersion transcript is {words} words (< {min_words} for {level})",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )
        if ltype == "shadow_reading":
            words = _word_count(c.get("text"))
            min_words = band["reading_words_min"] // 3
            if level in ("B1", "B2", "C1", "C2") and words and words < min_words:
                findings.append(
                    Finding(
                        "warning",
                        "shadow-reading-below-band",
                        f"shadow_reading text is {words} words (< {min_words} for {level})",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )

        # Hint density: writing_prompt should provide either hint_words or
        # template at A1/A2 (guided/structured modes). At B1+ the absence is
        # expected. We only warn if the prompt is missing BOTH at A-levels.
        if ltype == "writing_prompt" and level in ("A0", "A1", "A2"):
            has_support = (
                bool(c.get("hint_words"))
                or bool(c.get("template"))
                or bool(c.get("example_response"))
            )
            if not has_support:
                findings.append(
                    Finding(
                        "warning",
                        "writing-prompt-no-support",
                        f"writing_prompt at {level} has no hint_words/template/example",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )
    return findings


def _validate_final_test(lesson: dict[str, Any], lesson_index: int) -> list[Finding]:
    """Verify final_test prompt phrasing and matching-pair shape.

    Emits errors for stub phrasing and malformed matching pairs.
    Emits a warning when no matching exercise is present at all — full
    final-test coverage including matching pairs is a goal that may be
    deferred for some modules.
    """
    findings: list[Finding] = []
    content = lesson.get("content") if isinstance(lesson.get("content"), dict) else {}
    sections = content.get("test_sections") or content.get("sections") or []
    if not sections:
        # Schema covers this — only emit here if we want a stronger signal.
        return findings
    has_matching = False
    for s_idx, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        for qkey in ("exercises", "questions", "items"):
            qs = section.get(qkey)
            if not isinstance(qs, list):
                continue
            for q_idx, q in enumerate(qs):
                if not isinstance(q, dict):
                    continue
                for stub in FINAL_TEST_STUB_MARKERS:
                    for field_name in ("prompt", "question", "instruction"):
                        val = q.get(field_name)
                        if isinstance(val, str) and stub in val.lower():
                            findings.append(
                                Finding(
                                    "error",
                                    "final-test-stub",
                                    f"final_test section {s_idx} {qkey}[{q_idx}].{field_name}: stub phrase '{stub}'",
                                    lesson_index=lesson_index,
                                    lesson_type="final_test",
                                    field_path=f"{qkey}[{q_idx}].{field_name}",
                                )
                            )
                # Matching pairs shape check
                if (q.get("type") or "").lower() == "matching":
                    has_matching = True
                    pairs = q.get("pairs") or []
                    for p_idx, p in enumerate(pairs):
                        if not isinstance(p, dict):
                            continue
                        has_lr = bool(p.get("left")) and bool(p.get("right"))
                        has_er = bool(p.get("english")) and bool(p.get("russian"))
                        if not has_lr and not has_er:
                            findings.append(
                                Finding(
                                    "error",
                                    "final-test-matching-shape",
                                    f"final_test section {s_idx} matching pair {p_idx} missing both halves",
                                    lesson_index=lesson_index,
                                    lesson_type="final_test",
                                    field_path=f"{qkey}[{q_idx}].pairs[{p_idx}]",
                                )
                            )
    if not has_matching:
        findings.append(
            Finding(
                "warning",
                "final-test-no-matching",
                "final_test has no matching exercise; add one to complete coverage",
                lesson_index=lesson_index,
                lesson_type="final_test",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Top-level per-module validation
# ---------------------------------------------------------------------------


def validate_module(
    path: Path,
    *,
    audio_dir: Path | None,
    run_schemas: bool = True,
) -> ModuleValidation:
    """Validate a single source module JSON file."""
    match = _FILENAME_RE.match(path.name)
    if match is None:
        # Should not happen — caller filters by glob, but keep the shape valid.
        return ModuleValidation(
            filename=path.name,
            path=path,
            level="",
            file_order=0,
            lesson_count=0,
            findings=[
                Finding("error", "bad-filename", f"filename does not match module_<level>_<order>_*.json")
            ],
        )

    level = match.group("level")
    file_order = int(match.group("order"))

    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return ModuleValidation(
            filename=path.name,
            path=path,
            level=level,
            file_order=file_order,
            lesson_count=0,
            parse_error=f"{type(exc).__name__}: {exc}",
            findings=[
                Finding(
                    "error",
                    "parse-error",
                    f"failed to parse JSON: {type(exc).__name__}: {exc}",
                )
            ],
        )

    module_payload = data.get("module") if isinstance(data, dict) else None
    if not isinstance(module_payload, dict):
        return ModuleValidation(
            filename=path.name,
            path=path,
            level=level,
            file_order=file_order,
            lesson_count=0,
            parse_error="missing 'module' key",
            findings=[
                Finding(
                    "error",
                    "missing-module-key",
                    "top-level JSON object is missing the `module` key",
                )
            ],
        )

    lessons = module_payload.get("lessons")
    if not isinstance(lessons, list):
        return ModuleValidation(
            filename=path.name,
            path=path,
            level=level,
            file_order=file_order,
            lesson_count=0,
            findings=[
                Finding(
                    "error",
                    "missing-lessons-array",
                    "`module.lessons` is missing or not an array",
                )
            ],
        )

    result = ModuleValidation(
        filename=path.name,
        path=path,
        level=level,
        file_order=file_order,
        lesson_count=len(lessons),
    )

    # 1. Index continuity.
    result.findings.extend(_validate_indices(lessons))

    # 2. Per-lesson schema + placeholder + audio refs.
    for idx, lesson in enumerate(lessons, start=1):
        if not isinstance(lesson, dict):
            result.findings.append(
                Finding(
                    "error",
                    "non-dict-lesson",
                    f"lesson #{idx} is not a JSON object",
                    lesson_index=idx,
                )
            )
            continue

        ltype = (lesson.get("type") or "").strip()
        if not ltype:
            result.findings.append(
                Finding(
                    "error",
                    "missing-type",
                    f"lesson #{idx} has no `type`",
                    lesson_index=idx,
                )
            )
            continue

        content = lesson.get("content")
        if not isinstance(content, dict):
            result.findings.append(
                Finding(
                    "error",
                    "missing-content",
                    f"lesson #{idx} `{ltype}`: missing or non-object `content`",
                    lesson_index=idx,
                    lesson_type=ltype,
                )
            )
            continue

        # 2a. Schema validation against existing Marshmallow schemas.
        if run_schemas:
            schema_errs = _validate_lesson_schema(ltype, content)
            for err in schema_errs:
                if err.startswith("validator-import-failed"):
                    result.findings.append(
                        Finding(
                            "info",
                            "schema-skipped",
                            err,
                            lesson_index=idx,
                            lesson_type=ltype,
                        )
                    )
                else:
                    result.findings.append(
                        Finding(
                            "error",
                            "schema-violation",
                            err,
                            lesson_index=idx,
                            lesson_type=ltype,
                        )
                    )
            if ltype not in SCHEMA_LESSON_TYPES:
                result.findings.append(
                    Finding(
                        "info",
                        "unknown-lesson-type",
                        f"lesson #{idx} type `{ltype}` has no schema mapping (skipped schema check)",
                        lesson_index=idx,
                        lesson_type=ltype,
                    )
                )

        # 2b. Empty-required-field detection (stricter than schema).
        for path_, msg in _detect_empty_required_fields(ltype, content):
            result.findings.append(
                Finding(
                    "error",
                    "empty-required-field",
                    msg,
                    lesson_index=idx,
                    lesson_type=ltype,
                    field_path=path_,
                )
            )

        # 2c. Placeholder / stub markers.
        # For final_test, skip markers that _validate_final_test already catches
        # with richer context (section index, field name) to avoid double-reporting.
        placeholder_skip = FINAL_TEST_STUB_MARKERS if ltype == "final_test" else ()
        for f_path, marker, snippet in _detect_placeholders(content, skip_markers=placeholder_skip):
            result.findings.append(
                Finding(
                    "error",
                    "placeholder",
                    f"placeholder/stub `{marker}` in field {f_path}: {snippet!r}",
                    lesson_index=idx,
                    lesson_type=ltype,
                    field_path=f_path,
                )
            )

        # 2d. Final-test-specific phrasing.
        if ltype == "final_test":
            result.findings.extend(_validate_final_test(lesson, idx))

        # 2e. Audio references — collect & check existence.
        refs_found = False
        for f_path, ref in _iter_audio_refs(content):
            refs_found = True
            if audio_dir is not None:
                resolved, kind = _resolve_audio_path(ref, audio_dir)
            else:
                # Skip path resolution entirely so the manifest does not
                # carry CWD-relative pseudo-paths when --no-audio-check is on.
                _, kind = _resolve_audio_path(ref, Path("."))
                resolved = None
            entry = {
                "lesson_index": idx,
                "lesson_type": ltype,
                "field_path": f_path,
                "ref": ref,
                "kind": kind,
                "expected_path": str(resolved) if resolved else None,
                "exists": None,
            }
            if resolved is not None and audio_dir is not None:
                exists = resolved.exists()
                entry["exists"] = exists
                if not exists:
                    result.findings.append(
                        Finding(
                            "error",
                            "missing-audio-file",
                            f"audio file not found: `{ref}` (expected {resolved})",
                            lesson_index=idx,
                            lesson_type=ltype,
                            field_path=f_path,
                        )
                    )
            elif kind == "external":
                result.findings.append(
                    Finding(
                        "info",
                        "external-audio",
                        f"audio ref `{ref}` is not under /static/audio/",
                        lesson_index=idx,
                        lesson_type=ltype,
                        field_path=f_path,
                    )
                )
            result.audio_refs.append(entry)
        if ltype in AUDIO_REQUIRING_TYPES and not refs_found:
            result.findings.append(
                Finding(
                    "error",
                    "missing-audio-ref",
                    f"lesson type `{ltype}` requires at least one audio reference",
                    lesson_index=idx,
                    lesson_type=ltype,
                )
            )

    # 3. Progression.
    result.findings.extend(_validate_progression(level, lessons))

    return result


def validate_directory(
    source_dir: Path,
    *,
    audio_dir: Path | None,
    run_schemas: bool = True,
) -> list[ModuleValidation]:
    """Validate every `module_*.json` in `source_dir`."""
    out: list[ModuleValidation] = []
    if not source_dir.exists():
        return out
    for path in sorted(source_dir.glob("module_*.json")):
        out.append(validate_module(path, audio_dir=audio_dir, run_schemas=run_schemas))
    return out


# ---------------------------------------------------------------------------
# Manifest aggregation
# ---------------------------------------------------------------------------


def build_audio_manifest(
    modules: list[ModuleValidation],
    *,
    audio_dir: Path | None = None,
) -> dict[str, Any]:
    """Aggregate every audio reference into a deduplicated manifest.

    Each asset entry carries both the absolute `expected_path` (handy for
    `cp`-style copy steps) and a `relative_path` rooted at `audio_dir`
    (handy for portable runbooks that need `/static/audio/...`).
    """
    entries: dict[str, dict[str, Any]] = {}
    external_refs: list[dict[str, Any]] = []
    for m in modules:
        for ref_entry in m.audio_refs:
            ref = ref_entry["ref"]
            kind = ref_entry["kind"]
            if kind == "external":
                external_refs.append(
                    {
                        "filename": m.filename,
                        "lesson_index": ref_entry["lesson_index"],
                        "lesson_type": ref_entry["lesson_type"],
                        "ref": ref,
                    }
                )
                continue
            expected_path = ref_entry["expected_path"]
            if expected_path is None:
                continue
            key = expected_path
            if key not in entries:
                rel = None
                if audio_dir is not None:
                    try:
                        rel = str(Path(expected_path).relative_to(audio_dir))
                    except ValueError:
                        rel = None
                entries[key] = {
                    "expected_path": expected_path,
                    "relative_path": rel,
                    "ref": ref,
                    "kind": kind,
                    "exists": ref_entry["exists"],
                    "referenced_by": [],
                }
            entries[key]["referenced_by"].append(
                {
                    "filename": m.filename,
                    "lesson_index": ref_entry["lesson_index"],
                    "lesson_type": ref_entry["lesson_type"],
                    "field_path": ref_entry["field_path"],
                }
            )
    sorted_entries = sorted(entries.values(), key=lambda e: e["expected_path"])
    return {
        "total_assets": len(sorted_entries),
        "missing_assets": sum(1 for e in sorted_entries if e["exists"] is False),
        "external_audio_refs": external_refs,
        "assets": sorted_entries,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_validation_markdown(
    modules: list[ModuleValidation],
    *,
    source_dir: Path,
    audio_dir: Path | None,
) -> str:
    total = len(modules)
    failing = [m for m in modules if m.errors]
    warning_only = [m for m in modules if not m.errors and m.warnings]
    clean = [m for m in modules if not m.errors and not m.warnings]

    out: list[str] = []
    out.append("# module_completed/fixed source JSON validation\n\n")
    out.append(f"_Source directory_: `{source_dir}`\n")
    out.append(f"_Audio directory_: `{audio_dir}`\n\n" if audio_dir else "_Audio directory_: _(not checked)_\n\n")

    out.append("## Summary\n\n")
    out.append(f"- Total modules: **{total}**\n")
    out.append(f"- Modules with blocking errors: **{len(failing)}**\n")
    out.append(f"- Modules with warnings only: **{len(warning_only)}**\n")
    out.append(f"- Clean modules: **{len(clean)}**\n\n")

    # Aggregate finding codes.
    code_counter: Counter = Counter()
    for m in modules:
        for f in m.findings:
            code_counter[(f.severity, f.code)] += 1
    if code_counter:
        out.append("### Finding codes\n\n")
        out.append("| severity | code | count |\n| --- | --- | ---: |\n")
        for (sev, code), n in sorted(code_counter.items(), key=lambda kv: (-kv[1], kv[0])):
            out.append(f"| {sev} | `{code}` | {n} |\n")
        out.append("\n")

    if failing:
        out.append("## Modules with blocking errors\n\n")
        for m in failing:
            out.append(f"### `{m.filename}` ({m.level}, {m.lesson_count} lessons)\n\n")
            for f in m.errors:
                out.append(f"- **error** `{f.code}`: {f.message}\n")
            if m.warnings:
                out.append("  \n  _warnings:_\n")
                for f in m.warnings:
                    out.append(f"  - `{f.code}`: {f.message}\n")
            out.append("\n")
    else:
        out.append("## Modules with blocking errors\n\n_None._\n\n")

    if warning_only:
        out.append("## Modules with warnings only\n\n")
        for m in warning_only:
            out.append(f"### `{m.filename}` ({m.level}, {m.lesson_count} lessons)\n\n")
            for f in m.warnings:
                out.append(f"- **warning** `{f.code}`: {f.message}\n")
            out.append("\n")

    return "".join(out)


def render_manifest_markdown(
    manifest: dict[str, Any],
    *,
    source_dir: Path,
    audio_dir: Path | None,
) -> str:
    out: list[str] = []
    out.append("# module_completed/fixed audio manifest\n\n")
    out.append(f"_Source directory_: `{source_dir}`\n")
    out.append(f"_Audio root_: `{audio_dir}`\n\n" if audio_dir else "_Audio root_: _(not checked)_\n\n")

    out.append("## Summary\n\n")
    out.append(f"- Distinct static audio assets referenced: **{manifest['total_assets']}**\n")
    out.append(f"- Missing on disk: **{manifest['missing_assets']}**\n")
    out.append(f"- External / non-static audio refs: **{len(manifest['external_audio_refs'])}**\n\n")

    out.append("## How to use\n\n")
    out.append(
        "Every row in the table below is a static audio file that must be "
        "available at the listed path when the source JSON is imported into "
        "production. Copy these files from `app/static/audio/...` to the "
        "production audio root before running the import. The `referenced_by` "
        "column shows where in the source JSON the path is consumed.\n\n"
    )

    out.append("## Static audio assets\n\n")
    if not manifest["assets"]:
        out.append("_(no static audio referenced)_\n\n")
    else:
        out.append("| relative path (under audio root) | exists | kind | first ref | references |\n")
        out.append("| --- | :---: | --- | --- | ---: |\n")
        for entry in manifest["assets"]:
            exists = entry["exists"]
            mark = "✓" if exists else ("✗" if exists is False else "?")
            first_ref = entry["referenced_by"][0] if entry["referenced_by"] else {}
            display_path = entry.get("relative_path") or entry["expected_path"]
            out.append(
                f"| `{display_path}` "
                f"| {mark} "
                f"| {entry['kind']} "
                f"| `{first_ref.get('filename', '?')}` #{first_ref.get('lesson_index', '?')} "
                f"`{first_ref.get('lesson_type', '?')}`.{first_ref.get('field_path', '?')} "
                f"| {len(entry['referenced_by'])} |\n"
            )
        out.append("\n")

    missing = [e for e in manifest["assets"] if e["exists"] is False]
    if missing:
        out.append("## Missing files (BLOCKING for production transfer)\n\n")
        for entry in missing:
            display = entry.get("relative_path") or entry["expected_path"]
            out.append(f"- `{display}` (ref: `{entry['ref']}`)\n")
            for r in entry["referenced_by"][:3]:
                out.append(
                    f"  - in `{r['filename']}` #{r['lesson_index']} `{r['lesson_type']}` ({r['field_path']})\n"
                )
            if len(entry["referenced_by"]) > 3:
                out.append(f"  - _…and {len(entry['referenced_by']) - 3} more references_\n")
        out.append("\n")

    if manifest["external_audio_refs"]:
        out.append("## External audio refs (informational)\n\n")
        out.append(
            "These references don't point at `/static/audio/...` — they are "
            "either absolute URLs to other hosts or unusual relative paths. "
            "They're listed for completeness; production transfer does not "
            "need to copy them.\n\n"
        )
        for ref in manifest["external_audio_refs"]:
            out.append(
                f"- `{ref['ref']}` — `{ref['filename']}` #{ref['lesson_index']} `{ref['lesson_type']}`\n"
            )
        out.append("\n")

    return "".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate module_completed/fixed JSON files and emit audio manifest."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=DEFAULT_AUDIO_DIR,
        help="Static audio root for asset existence checks.",
    )
    parser.add_argument(
        "--no-audio-check",
        action="store_true",
        help="Skip filesystem audio existence checks.",
    )
    parser.add_argument(
        "--no-schemas",
        action="store_true",
        help="Skip schema validation (useful when Flask app cannot be imported).",
    )
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_REPORT,
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any module has blocking errors.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write JSON sidecar reports next to the markdown outputs.",
    )
    args = parser.parse_args(argv)

    audio_dir = None if args.no_audio_check else args.audio_dir

    modules = validate_directory(
        args.source_dir,
        audio_dir=audio_dir,
        run_schemas=not args.no_schemas,
    )
    manifest = build_audio_manifest(modules, audio_dir=audio_dir)

    validation_md = render_validation_markdown(
        modules, source_dir=args.source_dir, audio_dir=audio_dir
    )
    manifest_md = render_manifest_markdown(
        manifest, source_dir=args.source_dir, audio_dir=audio_dir
    )

    args.validation_output.parent.mkdir(parents=True, exist_ok=True)
    args.validation_output.write_text(validation_md, encoding="utf-8")
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(manifest_md, encoding="utf-8")

    if args.json:
        validation_json = args.validation_output.with_suffix(".json")
        manifest_json = args.manifest_output.with_suffix(".json")
        validation_json.write_text(
            json.dumps(
                {"modules": [m.as_dict() for m in modules]},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        manifest_json.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    total_errors = sum(len(m.errors) for m in modules)
    total_warnings = sum(len(m.warnings) for m in modules)
    print(
        f"validated {len(modules)} modules — "
        f"errors={total_errors}, warnings={total_warnings}, "
        f"audio_assets={manifest['total_assets']} "
        f"(missing={manifest['missing_assets']})",
        file=sys.stderr,
    )
    print(f"wrote {args.validation_output}", file=sys.stderr)
    print(f"wrote {args.manifest_output}", file=sys.stderr)

    if args.strict and total_errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
