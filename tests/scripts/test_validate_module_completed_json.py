"""Unit tests for scripts/validate_module_completed_json.py.

These tests cover the source-side validation axes (parsing, index continuity,
schema invocation, audio asset checks, placeholder detection, final-test
phrasing, progression warnings, and audio manifest aggregation).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from validate_module_completed_json import (  # noqa: E402
    build_audio_manifest,
    main,
    render_manifest_markdown,
    render_validation_markdown,
    validate_directory,
    validate_module,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _vocab_lesson(idx: int, *, n_items: int = 10) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "vocabulary",
        "title": f"Vocab {idx}",
        "content": {
            "vocabulary": [
                {"english": f"word{i}", "russian": f"слово{i}"}
                for i in range(n_items)
            ],
            "external_key": f"test:vocab:{idx}",
        },
    }


def _grammar_lesson(idx: int) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "grammar",
        "title": f"Grammar {idx}",
        "content": {
            "rule": "Use to be: am / is / are.",
            "sections": [{"heading": "intro", "body": "x"}],
            "external_key": f"test:grammar:{idx}",
        },
    }


def _writing_prompt_lesson(idx: int) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "writing_prompt",
        "title": "Письмо",
        "content": {
            "prompt": "Describe your morning routine.",
            "prompt_ru": "Опишите своё утро.",
            "min_sentences": 4,
            "min_checklist": 3,
            "mode": "guided",
            "template": "I usually wake up at...",
            "hint_words": ["breakfast", "coffee", "shower"],
            "target_phrases": ["I wake up", "I go to"],
            "checklist": ["wake up", "breakfast", "leave home"],
            "external_key": f"test:wp:{idx}",
        },
    }


def _dictation_lesson(idx: int) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "dictation",
        "title": "Диктант",
        "content": {
            "audio_url": "/static/audio/sample.mp3",
            "transcript": "Hello there friend.",
            "mode": "cloze",
            "external_key": f"test:dict:{idx}",
        },
    }


def _shadow_reading_lesson(idx: int) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "shadow_reading",
        "title": "Shadow",
        "content": {
            "audio_url": "/static/audio/sample.mp3",
            "text": "Read this aloud after the speaker.",
            "translation": "Прочитайте вслух после диктора.",
            "external_key": f"test:sr:{idx}",
        },
    }


def _final_test_lesson(idx: int) -> dict:
    return {
        "id": idx,
        "number": idx,
        "order": idx,
        "type": "final_test",
        "title": "Final Test",
        "content": {
            "test_sections": [
                {
                    "section": "vocab",
                    "exercises": [
                        {
                            "type": "multiple_choice",
                            "question": "What is 'hello'?",
                            "options": ["привет", "пока"],
                            "correct": 0,
                        }
                    ],
                }
            ],
            "external_key": f"test:ft:{idx}",
        },
    }


def _write_module(dir_path: Path, filename: str, lessons: list[dict], **kw) -> Path:
    payload = {
        "module": {
            "id": kw.get("id", 1),
            "title": kw.get("title", "Тест"),
            "title_en": kw.get("title_en", "Test"),
            "level": kw.get("level", "A1"),
            "order": kw.get("order", 1),
            "lessons": lessons,
        }
    }
    out = dir_path / filename
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static_audio"
    d.mkdir()
    (d / "sample.mp3").write_bytes(b"\x00")
    return d


@pytest.fixture
def clean_module_path(tmp_path: Path, audio_dir: Path) -> Path:
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        _vocab_lesson(1),
        _grammar_lesson(2),
        _dictation_lesson(3),
        _shadow_reading_lesson(4),
        _writing_prompt_lesson(5),
        _final_test_lesson(6),
    ]
    return _write_module(src, "module_A1_1_clean.json", lessons, level="A1")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_validate_module_clean(clean_module_path: Path, audio_dir: Path):
    result = validate_module(clean_module_path, audio_dir=audio_dir)
    assert result.parse_error is None
    assert result.lesson_count == 6
    assert result.errors == [], [e.as_dict() for e in result.errors]


def test_validate_module_records_audio_refs(clean_module_path: Path, audio_dir: Path):
    result = validate_module(clean_module_path, audio_dir=audio_dir)
    # dictation + shadow_reading both reference /static/audio/sample.mp3
    refs = [r["ref"] for r in result.audio_refs]
    assert refs.count("/static/audio/sample.mp3") == 2
    for r in result.audio_refs:
        assert r["exists"] is True
        assert r["kind"] == "static"


# ---------------------------------------------------------------------------
# Parse / structural errors
# ---------------------------------------------------------------------------


def test_validate_module_parse_error(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    path = src / "module_A1_99_broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = validate_module(path, audio_dir=audio_dir)
    assert result.parse_error is not None
    codes = {f.code for f in result.errors}
    assert "parse-error" in codes


def test_validate_module_missing_module_key(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    path = src / "module_A1_5_x.json"
    path.write_text(json.dumps({"other": True}), encoding="utf-8")
    result = validate_module(path, audio_dir=audio_dir)
    assert any(f.code == "missing-module-key" for f in result.errors)


def test_validate_module_missing_lessons_array(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    path = src / "module_A1_5_x.json"
    path.write_text(json.dumps({"module": {"title": "x"}}), encoding="utf-8")
    result = validate_module(path, audio_dir=audio_dir)
    assert any(f.code == "missing-lessons-array" for f in result.errors)


def test_validate_module_zero_lessons(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    path = _write_module(src, "module_A1_5_x.json", [], level="A1")
    result = validate_module(path, audio_dir=audio_dir)
    assert any(f.code == "empty-lessons" for f in result.errors)


# ---------------------------------------------------------------------------
# Index continuity
# ---------------------------------------------------------------------------


def test_validate_module_non_contiguous_index(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [_vocab_lesson(1), _grammar_lesson(3)]  # gap: missing #2
    lessons[1]["id"] = 3
    lessons[1]["number"] = 3
    lessons[1]["order"] = 3
    path = _write_module(src, "module_A1_5_g.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "non-contiguous-index" in codes


def test_validate_module_duplicate_index(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [_vocab_lesson(1), _grammar_lesson(2)]
    # Force duplicate id=1.
    lessons[1]["id"] = 1
    path = _write_module(src, "module_A1_5_d.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "duplicate-index" in codes or "non-contiguous-index" in codes


def test_validate_module_missing_index(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [_vocab_lesson(1), _grammar_lesson(2)]
    del lessons[1]["number"]
    path = _write_module(src, "module_A1_5_m.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "missing-index" in codes


def test_validate_module_non_integer_index(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [_vocab_lesson(1), _grammar_lesson(2)]
    lessons[1]["number"] = "two"
    path = _write_module(src, "module_A1_5_n.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "non-integer-index" in codes


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_validate_module_invokes_schemas(tmp_path: Path, audio_dir: Path):
    """Empty content fields surface as schema-violation."""
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        {
            "id": 1,
            "number": 1,
            "order": 1,
            "type": "vocabulary",
            "title": "v",
            "content": {"vocabulary": []},  # empty list — schema requires non-empty
        }
    ]
    path = _write_module(src, "module_A1_5_s.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "schema-violation" in codes


def test_validate_module_skips_schemas_when_disabled(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        {
            "id": 1,
            "number": 1,
            "order": 1,
            "type": "vocabulary",
            "title": "v",
            "content": {"vocabulary": []},
        }
    ]
    path = _write_module(src, "module_A1_5_s.json", lessons)
    result = validate_module(path, audio_dir=audio_dir, run_schemas=False)
    codes = {f.code for f in result.errors}
    assert "schema-violation" not in codes


def test_validate_module_unknown_lesson_type_is_info(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        {
            "id": 1,
            "number": 1,
            "order": 1,
            "type": "experimental_lesson",
            "title": "x",
            "content": {"foo": "bar"},
        }
    ]
    path = _write_module(src, "module_A1_5_u.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    infos = {f.code for f in result.infos}
    assert "unknown-lesson-type" in infos


# ---------------------------------------------------------------------------
# Audio validation
# ---------------------------------------------------------------------------


def test_validate_module_flags_missing_audio_file(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/does_not_exist.mp3"
    path = _write_module(src, "module_A1_5_a.json", [lesson, _final_test_lesson(2)])
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "missing-audio-file" in codes


def test_validate_module_flags_missing_audio_ref_for_required_type(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = {
        "id": 1,
        "number": 1,
        "order": 1,
        "type": "audio_fill_blank",
        "title": "x",
        "content": {
            "items": [
                {"text_with_gap": "I ___ home.", "answer": "go"}
            ],
        },
    }
    path = _write_module(src, "module_A1_5_af.json", [lesson])
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "missing-audio-ref" in codes


def test_validate_module_external_audio_is_info(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = {
        "id": 1,
        "number": 1,
        "order": 1,
        "type": "shadow_reading",
        "title": "x",
        "content": {
            "audio_url": "https://example.com/audio.mp3",
            "text": "x",
            "translation": "x",
        },
    }
    path = _write_module(src, "module_A1_5_ex.json", [lesson])
    result = validate_module(path, audio_dir=audio_dir)
    infos = {f.code for f in result.infos}
    assert "external-audio" in infos


def test_no_audio_check_skips_existence(tmp_path: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/does_not_exist.mp3"
    path = _write_module(src, "module_A1_5_n.json", [lesson])
    result = validate_module(path, audio_dir=None)
    assert not any(f.code == "missing-audio-file" for f in result.errors)


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------


def test_validate_module_flags_placeholder_text(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        _vocab_lesson(1),
        {
            "id": 2,
            "number": 2,
            "order": 2,
            "type": "grammar",
            "title": "g",
            "content": {"rule": "TODO: fill in the present continuous explanation"},
        },
    ]
    path = _write_module(src, "module_A1_5_p.json", lessons)
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "placeholder" in codes


def test_validate_module_exempts_section_headings_from_placeholder(
    tmp_path: Path, audio_dir: Path
):
    """A `section` heading legitimately describing the section content (e.g.
    "Вопросы — сделайте вопросительную форму") must not be flagged as a
    placeholder. The placeholder detector is scoped to instructional fields."""
    src = tmp_path / "modules"
    src.mkdir()
    ft = _final_test_lesson(1)
    ft["content"]["test_sections"].append(
        {
            "section": "Вопросы - сделайте вопросительную форму",
            "exercises": [
                {
                    "type": "transformation",
                    "instruction": "Преобразуйте утверждение в вопрос:",
                    "sentence": "You are a teacher.",
                    "correct": "Are you a teacher?",
                }
            ],
        }
    )
    path = _write_module(src, "module_A1_1_section_heading.json", [ft])
    result = validate_module(path, audio_dir=audio_dir)
    placeholder_findings = [f for f in result.errors if f.code == "placeholder"]
    assert placeholder_findings == [], (
        "section/title headings should be exempt from placeholder detection; "
        f"got: {[(f.field_path, f.message) for f in placeholder_findings]}"
    )


def test_validate_module_flags_stub_final_test(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    ft = _final_test_lesson(1)
    ft["content"]["test_sections"][0]["exercises"].append(
        {
            "type": "transformation",
            "instruction": "Сделайте вопрос из утверждения.",
            "question": "He is a student.",
        }
    )
    path = _write_module(src, "module_A1_5_st.json", [ft])
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "final-test-stub" in codes


def test_validate_module_flags_stub_in_items_collection(tmp_path: Path, audio_dir: Path):
    """Final-test sections that use `items` instead of `exercises`/`questions`
    must still go through stub detection — quality_pass walks all three keys."""
    src = tmp_path / "modules"
    src.mkdir()
    ft = _final_test_lesson(1)
    ft["content"]["test_sections"].append(
        {
            "section": "transformations",
            "items": [
                {
                    "type": "transformation",
                    "instruction": "Сделайте вопрос из утверждения.",
                    "question": "He is a student.",
                }
            ],
        }
    )
    path = _write_module(src, "module_A1_1_items_stub.json", [ft])
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "final-test-stub" in codes


def test_no_audio_check_does_not_emit_cwd_paths(tmp_path: Path):
    """When `--no-audio-check` is on, the manifest must not contain
    CWD-relative pseudo-paths derived from a `Path('.')` fallback."""
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/never_resolved.mp3"
    _write_module(src, "module_A1_1_noaudio.json", [lesson], level="A1")
    modules = validate_directory(src, audio_dir=None)
    manifest = build_audio_manifest(modules, audio_dir=None)
    # When audio_dir=None the manifest contains no resolved asset paths.
    assert manifest["assets"] == []
    # Audio refs themselves are still recorded — but with no resolved path.
    for module in modules:
        for entry in module.audio_refs:
            assert entry["expected_path"] is None


def test_validate_module_flags_empty_writing_prompt_checklist(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    wp = _writing_prompt_lesson(1)
    wp["content"]["checklist"] = ["", "   ", "ok"]
    path = _write_module(src, "module_A1_5_wp.json", [wp])
    result = validate_module(path, audio_dir=audio_dir)
    codes = {f.code for f in result.errors}
    assert "empty-required-field" in codes


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def test_validate_module_warns_on_low_reading_word_count(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    short_reading = {
        "id": 1,
        "number": 1,
        "order": 1,
        "type": "reading",
        "title": "r",
        "content": {
            "text": "Three small words.",  # well below B2 band
            "exercises": [{"question": "q", "answer": "a"}],
        },
    }
    path = _write_module(src, "module_B2_1_r.json", [short_reading], level="B2")
    result = validate_module(path, audio_dir=audio_dir)
    warns = {f.code for f in result.warnings}
    assert "reading-below-band" in warns


def test_validate_module_warns_on_a1_writing_prompt_no_support(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    wp = _writing_prompt_lesson(1)
    # Strip support fields.
    wp["content"].pop("template", None)
    wp["content"].pop("hint_words", None)
    wp["content"].pop("example_response", None)
    path = _write_module(src, "module_A1_5_wpns.json", [wp], level="A1")
    result = validate_module(path, audio_dir=audio_dir)
    warns = {f.code for f in result.warnings}
    assert "writing-prompt-no-support" in warns


# ---------------------------------------------------------------------------
# Manifest aggregation
# ---------------------------------------------------------------------------


def test_build_audio_manifest_deduplicates(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lessons = [
        _dictation_lesson(1),       # sample.mp3
        _shadow_reading_lesson(2),  # sample.mp3 — same asset
        _final_test_lesson(3),
    ]
    _write_module(src, "module_A1_1_m.json", lessons, level="A1")
    modules = validate_directory(src, audio_dir=audio_dir)
    manifest = build_audio_manifest(modules, audio_dir=audio_dir)
    # One distinct asset, two references.
    assert manifest["total_assets"] == 1
    assert manifest["missing_assets"] == 0
    assets = manifest["assets"]
    assert len(assets) == 1
    assert len(assets[0]["referenced_by"]) == 2
    # Relative path is rooted at audio_dir.
    assert assets[0]["relative_path"] == "sample.mp3"


def test_build_audio_manifest_counts_missing(tmp_path: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/missing.mp3"
    _write_module(src, "module_A1_1_m.json", [lesson], level="A1")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    modules = validate_directory(src, audio_dir=audio_dir)
    manifest = build_audio_manifest(modules, audio_dir=audio_dir)
    assert manifest["total_assets"] == 1
    assert manifest["missing_assets"] == 1


def test_render_manifest_markdown_lists_missing(tmp_path: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/missing.mp3"
    _write_module(src, "module_A1_1_m.json", [lesson], level="A1")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    modules = validate_directory(src, audio_dir=audio_dir)
    manifest = build_audio_manifest(modules, audio_dir=audio_dir)
    md = render_manifest_markdown(manifest, source_dir=src, audio_dir=audio_dir)
    assert "Missing files" in md
    assert "missing.mp3" in md


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_validation_markdown_smoke(clean_module_path: Path, audio_dir: Path):
    modules = validate_directory(clean_module_path.parent, audio_dir=audio_dir)
    md = render_validation_markdown(modules, source_dir=clean_module_path.parent, audio_dir=audio_dir)
    assert "module_completed/fixed source JSON validation" in md
    assert "Summary" in md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_writes_reports(tmp_path: Path, audio_dir: Path, clean_module_path: Path):
    validation = tmp_path / "validation.md"
    manifest = tmp_path / "manifest.md"
    rc = main(
        [
            "--source-dir", str(clean_module_path.parent),
            "--audio-dir", str(audio_dir),
            "--validation-output", str(validation),
            "--manifest-output", str(manifest),
        ]
    )
    assert rc == 0
    assert validation.exists()
    assert manifest.exists()
    md = validation.read_text(encoding="utf-8")
    assert "module_A1_1_clean.json" not in md or "Clean modules" in md
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "audio manifest" in manifest_text


def test_main_strict_returns_one_on_errors(tmp_path: Path, audio_dir: Path):
    src = tmp_path / "modules"
    src.mkdir()
    lesson = _dictation_lesson(1)
    lesson["content"]["audio_url"] = "/static/audio/does_not_exist.mp3"
    _write_module(src, "module_A1_5_x.json", [lesson], level="A1")
    rc = main(
        [
            "--source-dir", str(src),
            "--audio-dir", str(audio_dir),
            "--validation-output", str(tmp_path / "v.md"),
            "--manifest-output", str(tmp_path / "m.md"),
            "--strict",
        ]
    )
    assert rc == 1


def test_main_json_sidecar_emits(tmp_path: Path, audio_dir: Path, clean_module_path: Path):
    validation = tmp_path / "validation.md"
    manifest = tmp_path / "manifest.md"
    rc = main(
        [
            "--source-dir", str(clean_module_path.parent),
            "--audio-dir", str(audio_dir),
            "--validation-output", str(validation),
            "--manifest-output", str(manifest),
            "--json",
        ]
    )
    assert rc == 0
    val_json = validation.with_suffix(".json")
    man_json = manifest.with_suffix(".json")
    assert val_json.exists()
    assert man_json.exists()
    val_parsed = json.loads(val_json.read_text(encoding="utf-8"))
    assert "modules" in val_parsed
    man_parsed = json.loads(man_json.read_text(encoding="utf-8"))
    assert "assets" in man_parsed
