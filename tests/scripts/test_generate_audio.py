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
