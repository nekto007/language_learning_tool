from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
_MODULE_KEY = "scripts_generate_audio"
if _MODULE_KEY not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE_KEY, SCRIPT_PATH / "generate_audio.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_KEY] = _mod
    _mod.__package__ = ""
    _spec.loader.exec_module(_mod)
else:
    _mod = sys.modules[_MODULE_KEY]

build_audio_jobs = _mod.build_audio_jobs
clean_text_for_audio = _mod.clean_text_for_audio
resolve_audio_path = _mod.resolve_audio_path
_pick_english_tts_text = _mod._pick_english_tts_text


def test_clean_text_for_audio_collapses_whitespace():
    assert clean_text_for_audio("Hello,\n\nworld!") == "Hello, world!"


def test_resolve_static_audio_url(tmp_path):
    path = resolve_audio_path("/static/audio/immersion/dictation/a.mp3", root=tmp_path)
    assert path == tmp_path / "app/static/audio/immersion/dictation/a.mp3"


def test_build_audio_jobs_prefers_audio_text(tmp_path):
    content_file = tmp_path / "lessons.json"
    content_file.write_text(
        json.dumps([
            {
                "external_key": "immersion:dictation:A1:01",
                "lesson_type": "dictation",
                "content": {
                    "audio_url": "/static/audio/immersion/dictation/a.mp3",
                    "audio_text": "Audio text",
                    "transcript": "Transcript text",
                },
            }
        ]),
        encoding="utf-8",
    )

    jobs = build_audio_jobs(content_file)

    assert len(jobs) == 1
    assert jobs[0].text == "Audio text"
    assert jobs[0].lesson_type == "dictation"


class TestPickEnglishTtsText:
    def test_prefers_audio_text_over_question(self):
        assert _pick_english_tts_text({"audio_text": "Audio", "question": "Q"}) == "Audio"

    def test_falls_back_to_question_when_no_audio_text(self):
        assert _pick_english_tts_text({"question": "What is this?"}) == "What is this?"

    def test_falls_back_to_transcript(self):
        assert _pick_english_tts_text({"transcript": "Hello world"}) == "Hello world"

    def test_falls_back_to_sentence(self):
        assert _pick_english_tts_text({"sentence": "A short sentence."}) == "A short sentence."

    def test_falls_back_to_text(self):
        assert _pick_english_tts_text({"text": "Plain text"}) == "Plain text"

    def test_returns_empty_when_no_field_present(self):
        assert _pick_english_tts_text({}) == ""

    def test_skips_empty_string_values(self):
        assert _pick_english_tts_text({"audio_text": "", "question": "Q"}) == "Q"

    def test_never_uses_audio_url_as_text(self):
        result = _pick_english_tts_text({"audio_url": "/static/audio/foo.mp3"})
        assert result == ""

    def test_cleans_whitespace(self):
        assert _pick_english_tts_text({"question": "Hello\n\nworld"}) == "Hello world"


def test_build_audio_jobs_filters_lesson_type(tmp_path):
    content_file = tmp_path / "lessons.json"
    content_file.write_text(
        json.dumps([
            {
                "external_key": "one",
                "lesson_type": "dictation",
                "content": {"audio_url": "/static/audio/a.mp3", "audio_text": "One"},
            },
            {
                "external_key": "two",
                "lesson_type": "writing_prompt",
                "content": {"audio_url": "/static/audio/b.mp3", "audio_text": "Two"},
            },
        ]),
        encoding="utf-8",
    )

    jobs = build_audio_jobs(content_file, lesson_type="dictation")

    assert [job.external_key for job in jobs] == ["one"]
