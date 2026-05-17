"""Smoke tests for scripts/audit_lesson_content_per_module.py.

Deliberately avoids the Flask app / DB — covers pure logic checks and the
format_markdown / format_json / main paths.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from audit_lesson_content_per_module import (  # noqa: E402
    LessonAuditRow,
    _check_audio_url,
    _check_new_schema,
    _check_pairs_keys,
    _check_transform_prompt,
    audit_lesson,
    build_audit,
    build_heatmap,
    format_json,
    format_markdown,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(**kwargs) -> LessonAuditRow:
    defaults = dict(
        lesson_id=1,
        module_id=1,
        module_title="Test Module",
        level_code="A1",
        module_number=1,
        lesson_number=1,
        lesson_title="Test Lesson",
        lesson_type="vocabulary",
        has_new_schema=None,
        has_audio_url=None,
        audio_on_disk=None,
        transform_prompt_ok=None,
        pairs_keys_ok=None,
    )
    defaults.update(kwargs)
    return LessonAuditRow(**defaults)


# ---------------------------------------------------------------------------
# _check_new_schema
# ---------------------------------------------------------------------------

class TestCheckNewSchema:
    def test_translation_legacy_returns_false(self):
        assert _check_new_schema("translation", {"russian": "Привет", "english": "Hello"}) is False

    def test_translation_with_items_returns_true(self):
        content = {"items": [{"russian": "Привет", "english": "Hello"}]}
        assert _check_new_schema("translation", content) is True

    def test_translation_with_mode_returns_true(self):
        assert _check_new_schema("translation", {"russian": "Привет", "mode": "guided"}) is True

    def test_writing_prompt_new_schema(self):
        assert _check_new_schema("writing_prompt", {"prompt": "Write", "mode": "guided"}) is True

    def test_writing_prompt_legacy(self):
        assert _check_new_schema("writing_prompt", {"prompt": "Write"}) is False

    def test_writing_prompt_with_prompt_ru(self):
        assert _check_new_schema("writing_prompt", {"prompt_ru": "Напишите"}) is True

    def test_sentence_correction_with_items(self):
        assert _check_new_schema("sentence_correction", {"items": [{"incorrect_sentence": "x"}]}) is True

    def test_sentence_correction_legacy(self):
        assert _check_new_schema("sentence_correction", {"incorrect_sentence": "She go"}) is False

    def test_dictation_with_transcript(self):
        assert _check_new_schema("dictation", {"transcript": "Hello world"}) is True

    def test_dictation_without_transcript(self):
        assert _check_new_schema("dictation", {"audio_url": "/x.mp3"}) is False

    def test_shadow_reading_with_text(self):
        assert _check_new_schema("shadow_reading", {"text": "Read this"}) is True

    def test_shadow_reading_empty(self):
        assert _check_new_schema("shadow_reading", {}) is False

    def test_final_test_with_test_sections(self):
        assert _check_new_schema("final_test", {"test_sections": []}) is True

    def test_final_test_with_passing_score_percent(self):
        assert _check_new_schema("final_test", {"passing_score_percent": 70}) is True

    def test_final_test_legacy(self):
        assert _check_new_schema("final_test", {"passing_score": 70}) is False

    def test_matching_with_pairs(self):
        assert _check_new_schema("matching", {"pairs": [{"english": "cat", "russian": "кошка"}]}) is True

    def test_matching_empty_pairs(self):
        assert _check_new_schema("matching", {"pairs": []}) is False

    def test_sentence_completion_with_items(self):
        assert _check_new_schema("sentence_completion", {"items": [{"prompt": "x", "answer": "y"}]}) is True

    def test_vocabulary_not_applicable(self):
        assert _check_new_schema("vocabulary", {"words": []}) is None

    def test_grammar_not_applicable(self):
        assert _check_new_schema("grammar", {"content": "rule"}) is None


# ---------------------------------------------------------------------------
# _check_audio_url
# ---------------------------------------------------------------------------

class TestCheckAudioUrl:
    def test_dictation_with_audio_url(self):
        assert _check_audio_url("dictation", {"audio_url": "/static/audio/x.mp3"}) is True

    def test_dictation_missing_audio(self):
        assert _check_audio_url("dictation", {}) is False

    def test_shadow_reading_with_audio(self):
        assert _check_audio_url("shadow_reading", {"audio_url": "/static/audio/x.mp3"}) is True

    def test_vocabulary_not_applicable(self):
        assert _check_audio_url("vocabulary", {}) is None

    def test_audio_fill_blank_per_item_audio_clip_url(self):
        content = {"items": [{"text_with_gap": "___", "answer": "a", "audio_clip_url": "/x.mp3"}]}
        assert _check_audio_url("audio_fill_blank", content) is True

    def test_audio_fill_blank_per_item_audio_url(self):
        content = {"items": [{"text_with_gap": "___", "answer": "a", "audio_url": "/x.mp3"}]}
        assert _check_audio_url("audio_fill_blank", content) is True

    def test_audio_fill_blank_no_audio(self):
        content = {"items": [{"text_with_gap": "___", "answer": "a"}]}
        assert _check_audio_url("audio_fill_blank", content) is False

    def test_audio_fill_blank_empty_items(self):
        assert _check_audio_url("audio_fill_blank", {"items": []}) is False

    def test_listening_quiz_item_audio(self):
        content = {"questions": [{"text": "q1", "audio_url": "/x.mp3"}]}
        assert _check_audio_url("listening_quiz", content) is True


# ---------------------------------------------------------------------------
# _check_transform_prompt
# ---------------------------------------------------------------------------

class TestCheckTransformPrompt:
    def test_not_final_test_returns_none(self):
        assert _check_transform_prompt("quiz", {}) is None

    def test_no_transformation_questions_returns_true(self):
        content = {
            "test_sections": [{"exercises": [{"type": "multiple_choice", "question": "q?"}]}]
        }
        assert _check_transform_prompt("final_test", content) is True

    def test_empty_content_returns_true(self):
        assert _check_transform_prompt("final_test", {}) is True

    def test_bad_transform_prompt_russian(self):
        content = {
            "test_sections": [
                {"exercises": [{"type": "transformation", "question": "Сделайте вопрос"}]}
            ]
        }
        assert _check_transform_prompt("final_test", content) is False

    def test_bad_transform_prompt_english(self):
        content = {
            "exercises": [{"type": "transformation", "question": "Make a question"}]
        }
        assert _check_transform_prompt("final_test", content) is False

    def test_good_transform_prompt(self):
        content = {
            "test_sections": [
                {
                    "exercises": [
                        {
                            "type": "transformation",
                            "question": "Преобразуйте утверждение в вопрос:",
                        }
                    ]
                }
            ]
        }
        assert _check_transform_prompt("final_test", content) is True


# ---------------------------------------------------------------------------
# _check_pairs_keys
# ---------------------------------------------------------------------------

class TestCheckPairsKeys:
    def test_matching_english_russian(self):
        content = {"pairs": [{"english": "cat", "russian": "кошка"}]}
        assert _check_pairs_keys("matching", content) is True

    def test_matching_left_right(self):
        content = {"pairs": [{"left": "cat", "right": "кошка"}]}
        assert _check_pairs_keys("matching", content) is True

    def test_matching_no_pairs_returns_none(self):
        assert _check_pairs_keys("matching", {}) is None

    def test_matching_bad_pair_keys(self):
        content = {"pairs": [{"foo": "bar", "baz": "qux"}]}
        assert _check_pairs_keys("matching", content) is False

    def test_matching_empty_pairs_returns_none(self):
        assert _check_pairs_keys("matching", {"pairs": []}) is None

    def test_not_applicable_type_returns_none(self):
        assert _check_pairs_keys("vocabulary", {}) is None

    def test_final_test_with_matching_pairs_ok(self):
        content = {
            "test_sections": [
                {
                    "exercises": [
                        {
                            "type": "matching",
                            "pairs": [{"english": "a", "russian": "б"}],
                        }
                    ]
                }
            ]
        }
        assert _check_pairs_keys("final_test", content) is True

    def test_final_test_no_matching_questions_returns_none(self):
        content = {
            "test_sections": [
                {"exercises": [{"type": "multiple_choice", "question": "q"}]}
            ]
        }
        assert _check_pairs_keys("final_test", content) is None


# ---------------------------------------------------------------------------
# audit_lesson
# ---------------------------------------------------------------------------

class TestAuditLesson:
    def test_translation_legacy_has_new_schema_gap(self):
        row = audit_lesson(
            lesson_id=1,
            module_id=1,
            module_title="M1",
            level_code="A1",
            module_number=1,
            lesson_number=5,
            lesson_title="Translation",
            lesson_type="translation",
            content={"russian": "Привет", "english": "Hello"},
        )
        assert row.has_new_schema is False
        assert row.gap_count >= 1

    def test_translation_new_schema_no_gap(self):
        row = audit_lesson(
            lesson_id=2,
            module_id=1,
            module_title="M1",
            level_code="A1",
            module_number=1,
            lesson_number=6,
            lesson_title="Translation",
            lesson_type="translation",
            content={"items": [{"russian": "Привет", "english": "Hello"}], "mode": "guided"},
        )
        assert row.has_new_schema is True
        assert row.gap_count == 0

    def test_dictation_with_audio_url_no_disk_file(self):
        row = audit_lesson(
            lesson_id=3,
            module_id=1,
            module_title="M1",
            level_code="A1",
            module_number=1,
            lesson_number=7,
            lesson_title="Dictation",
            lesson_type="dictation",
            content={
                "audio_url": "/static/audio/immersion/dictation/nonexistent_file.mp3",
                "transcript": "Hello world",
            },
        )
        assert row.has_new_schema is True
        assert row.has_audio_url is True
        assert row.audio_on_disk is False  # file doesn't exist

    def test_vocabulary_no_checks(self):
        row = audit_lesson(
            lesson_id=4,
            module_id=1,
            module_title="M1",
            level_code="A1",
            module_number=1,
            lesson_number=1,
            lesson_title="Vocab",
            lesson_type="vocabulary",
            content={"words": [{"word": "hello", "translation": "привет"}]},
        )
        assert row.gap_count == 0
        assert row.is_ok is True

    def test_gap_count_property(self):
        row = _make_row(has_new_schema=False, has_audio_url=False, audio_on_disk=None)
        assert row.gap_count == 2

    def test_is_ok_with_all_none(self):
        row = _make_row()
        assert row.is_ok is True

    def test_is_ok_with_false_check(self):
        row = _make_row(has_new_schema=False)
        assert row.is_ok is False


# ---------------------------------------------------------------------------
# build_heatmap
# ---------------------------------------------------------------------------

class TestBuildHeatmap:
    def test_ok_cell(self):
        rows = [_make_row(lesson_type="translation", has_new_schema=True)]
        heatmap = build_heatmap(rows)
        assert heatmap["lesson_types"] == ["translation"]
        assert heatmap["modules"][0]["cells"]["translation"] == "OK"

    def test_gap_cell(self):
        rows = [_make_row(lesson_type="translation", has_new_schema=False)]
        heatmap = build_heatmap(rows)
        assert "gap" in heatmap["modules"][0]["cells"]["translation"].lower()

    def test_absent_type_shows_dash(self):
        rows = [
            _make_row(module_id=1, module_number=1, lesson_type="translation", has_new_schema=True),
            _make_row(
                lesson_id=2, module_id=2, module_number=2, module_title="M2",
                lesson_type="dictation", has_new_schema=True,
            ),
        ]
        heatmap = build_heatmap(rows)
        mod1 = next(m for m in heatmap["modules"] if m["module_number"] == 1)
        assert mod1["cells"].get("dictation") == "-"

    def test_multi_gap_count(self):
        rows = [
            _make_row(lesson_type="dictation", has_audio_url=False, audio_on_disk=False),
        ]
        heatmap = build_heatmap(rows)
        cell = heatmap["modules"][0]["cells"]["dictation"]
        assert "2" in cell

    def test_empty_rows(self):
        heatmap = build_heatmap([])
        assert heatmap["lesson_types"] == []
        assert heatmap["modules"] == []


# ---------------------------------------------------------------------------
# format_markdown / format_json
# ---------------------------------------------------------------------------

class TestFormatMarkdown:
    def test_smoke_empty(self):
        md = format_markdown([])
        assert "Module Content Audit" in md
        assert "0" in md

    def test_with_ok_and_gap_rows(self):
        rows = [
            _make_row(lesson_type="translation", has_new_schema=False),
            _make_row(lesson_id=2, lesson_number=2, lesson_type="dictation", has_new_schema=True),
        ]
        md = format_markdown(rows)
        assert "translation" in md
        assert "dictation" in md
        assert "gap" in md.lower()

    def test_heatmap_table_present(self):
        rows = [_make_row(lesson_type="translation", has_new_schema=True)]
        md = format_markdown(rows)
        assert "Heatmap" in md
        assert "OK" in md


class TestFormatJson:
    def test_smoke(self):
        rows = [_make_row()]
        raw = format_json(rows)
        parsed = json.loads(raw)
        assert len(parsed) == 1
        assert parsed[0]["lesson_id"] == 1

    def test_all_fields_present(self):
        rows = [_make_row(has_new_schema=True, has_audio_url=False)]
        parsed = json.loads(format_json(rows))
        row = parsed[0]
        assert row["has_new_schema"] is True
        assert row["has_audio_url"] is False
        assert "gap_count" not in row  # properties not serialised by asdict


# ---------------------------------------------------------------------------
# build_audit / main
# ---------------------------------------------------------------------------

class TestBuildAudit:
    def test_without_db_returns_empty(self):
        result = build_audit(db_session=None)
        assert result == []


class TestMain:
    def test_no_db_markdown(self, tmp_path):
        import audit_lesson_content_per_module as mod

        out_path = tmp_path / "report.md"
        rc = mod.main(["--no-db", "--output", str(out_path), "--format", "markdown"])
        assert rc == 0
        assert out_path.exists()
        assert "Module Content Audit" in out_path.read_text(encoding="utf-8")

    def test_no_db_json(self, tmp_path):
        import audit_lesson_content_per_module as mod

        out_path = tmp_path / "report.json"
        rc = mod.main(["--no-db", "--output", str(out_path), "--format", "json"])
        assert rc == 0
        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(parsed, list)
        assert parsed == []  # no DB, no rows

    def test_creates_output_dir(self, tmp_path):
        import audit_lesson_content_per_module as mod

        out_path = tmp_path / "nested" / "dir" / "report.md"
        rc = mod.main(["--no-db", "--output", str(out_path)])
        assert rc == 0
        assert out_path.exists()
