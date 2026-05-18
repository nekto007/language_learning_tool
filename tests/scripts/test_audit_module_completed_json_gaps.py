"""Unit tests for scripts/audit_module_completed_json_gaps.py.

These tests deliberately avoid touching the Flask app — they cover the
source-side audit logic only (parsing module JSON, canonical coverage,
content-field validation, audio reference checks, progression flags,
and report rendering).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from audit_module_completed_json_gaps import (  # noqa: E402
    CANONICAL_SEQUENCE,
    MODULE_TYPE_EXEMPTIONS,
    REQUIRED_CANONICAL_TYPES,
    audit_module,
    build_audit,
    format_json,
    format_markdown,
    load_source_modules,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_canonical_a1_lessons() -> list[dict]:
    """Return a lesson list matching the A1/M1 canonical reference shape."""
    return [
        {"id": 1, "number": 1, "order": 1, "type": "vocabulary",
         "title": "Vocab", "content": {"vocabulary": [{"english": "x"} for _ in range(10)]}},
        {"id": 2, "number": 2, "order": 2, "type": "flashcards",
         "title": "Cards 1", "content": {"cards": [{"front": "a", "back": "b"}]}},
        {"id": 3, "number": 3, "order": 3, "type": "collocation_matching",
         "title": "Coll", "content": {"pairs": [{"phrase": "a", "translation": "b"}]}},
        {"id": 4, "number": 4, "order": 4, "type": "grammar",
         "title": "Grammar", "content": {"rule": "to be", "sections": []}},
        {"id": 5, "number": 5, "order": 5, "type": "sentence_completion",
         "title": "Compl", "content": {"items": [{"prompt": "a"}]}},
        {"id": 6, "number": 6, "order": 6, "type": "reading",
         "title": "Read",
         "content": {
             "text": "We meet new friends. Hello and hi. " * 12,
             "exercises": [{"question": "q"}],
         }},
        {"id": 7, "number": 7, "order": 7, "type": "listening_immersion",
         "title": "LI",
         "content": {
             "audio_url": "/static/audio/sample.mp3",
             "text": "A short transcript. " * 6,
         }},
        {"id": 8, "number": 8, "order": 8, "type": "listening_quiz",
         "title": "LQ",
         "content": {
             "exercises": [{"audio": "[sound:sample.mp3]", "question": "q"}]
         }},
        {"id": 9, "number": 9, "order": 9, "type": "audio_fill_blank",
         "title": "AFB",
         "content": {
             "items": [{"audio_clip_url": "/static/audio/sample.mp3",
                        "sentence": "x", "answer": "y"}]
         }},
        {"id": 10, "number": 10, "order": 10, "type": "shadow_reading",
         "title": "SR",
         "content": {
             "audio_url": "/static/audio/sample.mp3",
             "text": "Practice shadowing.",
         }},
        {"id": 11, "number": 11, "order": 11, "type": "dictation",
         "title": "Dict",
         "content": {
             "audio_url": "/static/audio/sample.mp3",
             "transcript": "Hello there.",
         }},
        {"id": 12, "number": 12, "order": 12, "type": "dialogue_completion_quiz",
         "title": "DCQ", "content": {"exercises": [{"q": "q"}]}},
        {"id": 13, "number": 13, "order": 13, "type": "ordering_quiz",
         "title": "OQ", "content": {"exercises": [{"q": "q"}]}},
        {"id": 14, "number": 14, "order": 14, "type": "flashcards",
         "title": "Cards 2", "content": {"cards": [{"front": "a", "back": "b"}]}},
        {"id": 15, "number": 15, "order": 15, "type": "translation",
         "title": "T", "content": {"items": [{"ru": "x", "en": "y"}]}},
        {"id": 16, "number": 16, "order": 16, "type": "translation_quiz",
         "title": "TQ", "content": {"exercises": [{"q": "q"}]}},
        {"id": 17, "number": 17, "order": 17, "type": "writing_prompt",
         "title": "WP",
         "content": {"prompt": "Write a note.", "checklist": ["greeting"]}},
        {"id": 18, "number": 18, "order": 18, "type": "final_test",
         "title": "FT", "content": {"test_sections": [{"q": "q"}]}},
    ]


def _write_module(dir_path: Path, filename: str, lessons: list[dict], **kw) -> None:
    payload = {"module": {"title": kw.get("title", "Sample"),
                          "title_en": kw.get("title_en", "Sample"),
                          "level": kw.get("level", "A1"),
                          "lessons": lessons}}
    (dir_path / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static_audio"
    d.mkdir()
    (d / "sample.mp3").write_bytes(b"\x00")
    return d


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "modules"
    d.mkdir()
    # Canonical-shaped A1/M1 (with sentence_correction inserted).
    canonical_lessons = _make_canonical_a1_lessons()
    # Slot sentence_correction at position 6 to match the canonical target.
    canonical_lessons.insert(5, {
        "id": 99, "number": 99, "order": 99,
        "type": "sentence_correction", "title": "Corr",
        "content": {"items": [{"wrong": "x", "right": "y"}]},
    })
    # Renumber.
    for i, l in enumerate(canonical_lessons, start=1):
        l["id"] = i
        l["number"] = i
        l["order"] = i
    _write_module(d, "module_A1_1_greetings.json", canonical_lessons, level="A1")

    # Needs-work module: bare A1 with only vocab and grammar.
    _write_module(
        d,
        "module_A1_2_numbers.json",
        [
            {"id": 1, "number": 1, "order": 1, "type": "vocabulary",
             "title": "v", "content": {"vocabulary": [{"english": "1"}] * 6}},
            {"id": 2, "number": 2, "order": 2, "type": "grammar",
             "title": "g", "content": {"rule": "x"}},
        ],
        level="A1",
    )

    # Module with invalid indices, missing audio, broken audio.
    _write_module(
        d,
        "module_B2_5_culture.json",
        [
            {"id": 1, "number": 1, "order": 1, "type": "vocabulary",
             "title": "v", "content": {"vocabulary": [{"english": "1"}] * 12}},
            {"id": 7, "number": 7, "order": 7, "type": "listening_quiz",
             "title": "lq", "content": {}},  # missing content + audio
            {"id": 3, "number": 3, "order": 3, "type": "dictation",
             "title": "d",
             "content": {"audio_url": "/static/audio/nope.mp3",
                         "transcript": "short transcript"}},  # broken audio
            {"id": 4, "number": 4, "order": 4, "type": "reading",
             "title": "r",
             "content": {"text": "Two words.", "exercises": []}},  # very short -> progression flag
        ],
        level="B2",
    )

    # Broken JSON file.
    (d / "module_A1_99_broken.json").write_text("{not valid json",
                                                 encoding="utf-8")

    return d


# ---------------------------------------------------------------------------
# load_source_modules
# ---------------------------------------------------------------------------


def test_load_source_modules_parses_each_file(source_dir):
    modules = load_source_modules(source_dir)
    names = {m.filename for m in modules}
    assert names == {
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
        "module_A1_99_broken.json",
    }
    broken = next(m for m in modules if m.filename == "module_A1_99_broken.json")
    assert broken.parse_error is not None
    assert broken.lessons == []


def test_load_source_modules_extracts_level_and_order(source_dir):
    modules = {m.filename: m for m in load_source_modules(source_dir)}
    assert modules["module_A1_1_greetings.json"].level == "A1"
    assert modules["module_A1_1_greetings.json"].file_order == 1
    assert modules["module_B2_5_culture.json"].level == "B2"
    assert modules["module_B2_5_culture.json"].file_order == 5


# ---------------------------------------------------------------------------
# audit_module
# ---------------------------------------------------------------------------


def test_audit_module_canonical_module_passes(source_dir, audio_dir):
    modules = {m.filename: m for m in load_source_modules(source_dir)}
    res = audit_module(modules["module_A1_1_greetings.json"], audio_dir)
    assert res.canonical, res.as_dict()
    assert res.missing_required_types == []
    assert res.invalid_indices == []
    assert res.missing_content_fields == []
    assert res.missing_audio_refs == []
    assert res.broken_audio_files == []


def test_audit_module_a1m1_exempt_from_sentence_correction(tmp_path, audio_dir):
    """A1/M1 stays canonical even when sentence_correction is missing."""
    src = tmp_path / "modules"
    src.mkdir()
    lessons = _make_canonical_a1_lessons()  # No sentence_correction.
    _write_module(src, "module_A1_1_greetings.json", lessons, level="A1")
    modules = load_source_modules(src)
    assert modules
    res = audit_module(modules[0], audio_dir)
    assert "sentence_correction" not in res.missing_required_types
    assert res.canonical_coverage["sentence_correction"] is True
    assert "module_A1_1_greetings.json" in MODULE_TYPE_EXEMPTIONS


def test_audit_module_flags_missing_required_types(source_dir, audio_dir):
    modules = {m.filename: m for m in load_source_modules(source_dir)}
    res = audit_module(modules["module_A1_2_numbers.json"], audio_dir)
    assert not res.canonical
    # Many required types absent.
    for t in ("collocation_matching", "sentence_completion", "reading",
              "listening_quiz", "audio_fill_blank", "dictation",
              "shadow_reading", "translation", "writing_prompt", "final_test"):
        assert t in res.missing_required_types
    # flashcards count = 0 → also missing.
    assert "flashcards" in res.missing_required_types


def test_audit_module_flags_invalid_indices_and_broken_audio(source_dir, audio_dir):
    modules = {m.filename: m for m in load_source_modules(source_dir)}
    res = audit_module(modules["module_B2_5_culture.json"], audio_dir)
    assert not res.canonical
    # Lesson #2 has id=7 — mismatch.
    assert any("id=7" in issue for issue in res.invalid_indices)
    # Broken audio: dictation references nope.mp3.
    assert res.broken_audio_files, "expected nope.mp3 to be flagged"
    assert any("nope.mp3" in entry["ref"] for entry in res.broken_audio_files)
    # listening_quiz has empty content → missing content fields + missing audio.
    has_lq_missing_audio = any(
        e["type"] == "listening_quiz" for e in res.missing_audio_refs
    )
    assert has_lq_missing_audio
    # Reading text of 2 words is below B2 band.
    progression = " ".join(res.progression_flags)
    assert "reading text" in progression.lower()


def test_audit_module_handles_parse_error(source_dir, audio_dir):
    modules = {m.filename: m for m in load_source_modules(source_dir)}
    res = audit_module(modules["module_A1_99_broken.json"], audio_dir)
    assert not res.canonical
    assert len(res.missing_required_types) == len(REQUIRED_CANONICAL_TYPES)
    assert any("parse error" in line for line in res.invalid_indices)


# ---------------------------------------------------------------------------
# build_audit / format_*
# ---------------------------------------------------------------------------


def test_build_audit_top_level_shape(source_dir, audio_dir):
    audit = build_audit(source_dir, audio_dir=audio_dir, db_session=None)
    assert "survey" in audit
    assert "modules" in audit
    assert audit["survey"]["total_files"] == 4
    assert audit["survey"]["lesson_count_buckets"]  # populated
    canonical = audit["survey"]["canonical_files"]
    assert "module_A1_1_greetings.json" in canonical
    needs = audit["survey"]["needs_work_files"]
    assert "module_A1_2_numbers.json" in needs
    assert "module_B2_5_culture.json" in needs
    assert audit["canonical_sequence"] == list(CANONICAL_SEQUENCE)
    assert "db" not in audit


def test_build_audit_lesson_type_counter(source_dir, audio_dir):
    audit = build_audit(source_dir, audio_dir=audio_dir, db_session=None)
    counter = audit["survey"]["lesson_type_counter"]
    assert counter["vocabulary"] >= 3
    assert counter["flashcards"] >= 2
    assert counter["sentence_correction"] == 1


def test_format_markdown_smoke(source_dir, audio_dir):
    audit = build_audit(source_dir, audio_dir=audio_dir, db_session=None)
    md = format_markdown(audit)
    assert "module_completed/fixed JSON gap report" in md
    assert "Current-state survey" in md
    assert "Per-module canonical coverage heatmap" in md
    assert "module_A1_1_greetings.json" in md
    assert "OK" in md
    assert "WORK" in md


def test_format_json_round_trip(source_dir, audio_dir):
    audit = build_audit(source_dir, audio_dir=audio_dir, db_session=None)
    raw = format_json(audit)
    parsed = json.loads(raw)
    assert parsed["survey"]["total_files"] == 4


def test_main_writes_markdown_report(tmp_path, source_dir, audio_dir):
    import audit_module_completed_json_gaps as mod

    out = tmp_path / "report.md"
    rc = mod.main(
        [
            "--source-dir", str(source_dir),
            "--audio-dir", str(audio_dir),
            "--output", str(out),
            "--format", "markdown",
            "--no-db",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "Per-module canonical coverage heatmap" in text


def test_main_writes_json_report(tmp_path, source_dir, audio_dir):
    import audit_module_completed_json_gaps as mod

    out = tmp_path / "report.json"
    rc = mod.main(
        [
            "--source-dir", str(source_dir),
            "--audio-dir", str(audio_dir),
            "--output", str(out),
            "--format", "json",
            "--no-db",
        ]
    )
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["survey"]["total_files"] == 4
    # Per-module audit entries should be sorted by filename.
    file_order = [m["filename"] for m in parsed["modules"]]
    assert file_order == sorted(file_order)


def test_no_audio_check_skips_filesystem_validation(tmp_path, audio_dir):
    src = tmp_path / "src"
    src.mkdir()
    _write_module(
        src,
        "module_A1_3_x.json",
        [
            {"id": 1, "number": 1, "order": 1, "type": "dictation",
             "title": "d", "content": {
                 "audio_url": "/static/audio/does_not_exist.mp3",
                 "transcript": "hello world",
             }}
        ],
        level="A1",
    )
    # With audio_dir=None the audit must not flag broken_audio_files.
    audit = build_audit(src, audio_dir=None, db_session=None)
    m = audit["modules"][0]
    assert m["broken_audio_files"] == []
