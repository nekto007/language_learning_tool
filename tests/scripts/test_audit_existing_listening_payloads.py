"""Unit tests for scripts/audit_existing_listening_payloads.py.

Deliberately avoids spinning up the Flask app — covers source-side logic:
parsing, audio classification, text detection, exclusion logic, and formatters.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from audit_existing_listening_payloads import (  # noqa: E402
    LISTENING_TYPES,
    ListeningLessonAudit,
    _is_placeholder,
    _is_real_url,
    audit_source,
    build_report,
    build_source_summary,
    format_json,
    format_markdown,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_module(dir_path: Path, filename: str, module_payload: dict) -> None:
    (dir_path / filename).write_text(
        json.dumps({"module": module_payload}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "modules"
    d.mkdir()

    # A1 module: listening_immersion with text+placeholder audio, listening_quiz with item placeholder audio
    _write_module(
        d,
        "module_A1_1_greetings.json",
        {
            "id": "a1-1",
            "title": "Greetings",
            "title_en": "Greetings",
            "level": "A1",
            "lessons": [
                {
                    "type": "listening_immersion",
                    "title": "Listen: Dialogue",
                    "order": 11,
                    "content": {
                        "title": "At the cafe",
                        "audio": "[sound:A1_M1_L11_dialogue.mp3]",
                        "text": "Hello, how are you? I am fine.",
                        "translation": "Привет, как дела? Я в порядке.",
                        "instruction": "Listen and read.",
                    },
                },
                {
                    "type": "listening_quiz",
                    "title": "Listening Quiz",
                    "order": 6,
                    "content": {
                        "exercises": [
                            {
                                "type": "listening_choice",
                                "audio": "[sound:A1M1L6_ex1.mp3]",
                                "question": "What did you hear?",
                                "options": ["Hello", "Goodbye"],
                                "correct": "Hello",
                            },
                            {
                                "type": "listening_choice",
                                "audio": "[sound:A1M1L6_ex2.mp3]",
                                "question": "What is the name?",
                                "options": ["Sarah", "Anna"],
                                "correct": "Sarah",
                            },
                        ]
                    },
                },
            ],
        },
    )

    # B1 module: listening_immersion with real audio_url, listening_quiz with item-level transcript
    _write_module(
        d,
        "module_B1_1_past_verbs.json",
        {
            "id": "b1-1",
            "title": "Past Verbs",
            "title_en": "Past Verbs",
            "level": "B1",
            "lessons": [
                {
                    "type": "listening_immersion",
                    "title": "Past Stories",
                    "order": 11,
                    "content": {
                        "audio_url": "https://cdn.example.com/b1_m1_l11.mp3",
                        "text": "Last weekend was incredible. I went to the market.",
                        "translation": "Прошлые выходные были невероятными.",
                    },
                },
                {
                    "type": "listening_quiz",
                    "title": "Listening Quiz B1",
                    "order": 6,
                    "content": {
                        "exercises": [
                            {
                                "audio": "[sound:B1M1L6_ex1.mp3]",
                                "question": "What did she do?",
                                "options": ["went", "goes", "gone"],
                                "correct": "went",
                                "transcript": "Yesterday she went to the gym.",
                            }
                        ]
                    },
                },
            ],
        },
    )

    # C1 module: listening_immersion with NO audio at all (no audio field)
    _write_module(
        d,
        "module_C1_1_advanced.json",
        {
            "id": "c1-1",
            "title": "Advanced Topics",
            "title_en": "Advanced Topics",
            "level": "C1",
            "lessons": [
                {
                    "type": "listening_immersion",
                    "title": "Deep Dive",
                    "order": 11,
                    "content": {
                        "text": "This is a very complex text about advanced topics in English literature.",
                        "translation": "Это очень сложный текст.",
                    },
                },
            ],
        },
    )

    return d


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


def test_is_placeholder_detects_sound_prefix():
    assert _is_placeholder("[sound:file.mp3]") is True
    assert _is_placeholder("https://cdn.example.com/file.mp3") is False
    assert _is_placeholder(None) is False
    assert _is_placeholder("") is False


def test_is_real_url_detects_http_and_static():
    assert _is_real_url("https://cdn.example.com/a.mp3") is True
    assert _is_real_url("http://localhost/a.mp3") is True
    assert _is_real_url("/static/audio/a.mp3") is True
    assert _is_real_url("/media/a.mp3") is True
    assert _is_real_url("[sound:a.mp3]") is False
    assert _is_real_url(None) is False


# ---------------------------------------------------------------------------
# Unit tests: audit_source
# ---------------------------------------------------------------------------


def test_audit_source_finds_all_listening_lessons(source_dir):
    audits = audit_source(source_dir)
    assert len(audits) == 5  # 2 from A1, 2 from B1, 1 from C1


def test_audit_source_filters_by_type(source_dir):
    audits = audit_source(source_dir)
    types = {a.lesson_type for a in audits}
    assert types == {"listening_immersion", "listening_quiz"}


def test_audit_source_placeholder_audio_a1_immersion(source_dir):
    audits = audit_source(source_dir)
    a1_immersion = next(
        a for a in audits if a.module_level == "A1" and a.lesson_type == "listening_immersion"
    )
    assert a1_immersion.lesson_audio_placeholder is True
    assert a1_immersion.lesson_audio_real is False
    assert a1_immersion.audio_style == "placeholder-lesson"


def test_audit_source_real_audio_b1_immersion(source_dir):
    audits = audit_source(source_dir)
    b1_immersion = next(
        a for a in audits if a.module_level == "B1" and a.lesson_type == "listening_immersion"
    )
    assert b1_immersion.lesson_audio_real is True
    assert b1_immersion.audio_style == "lesson-level"


def test_audit_source_no_audio_c1_immersion(source_dir):
    audits = audit_source(source_dir)
    c1_immersion = next(
        a for a in audits if a.module_level == "C1" and a.lesson_type == "listening_immersion"
    )
    assert c1_immersion.lesson_audio_real is False
    assert c1_immersion.lesson_audio_placeholder is False
    assert c1_immersion.audio_style == "none"


def test_audit_source_placeholder_item_audio_a1_quiz(source_dir):
    audits = audit_source(source_dir)
    a1_quiz = next(
        a for a in audits if a.module_level == "A1" and a.lesson_type == "listening_quiz"
    )
    assert a1_quiz.item_audio_placeholder is True
    assert a1_quiz.item_audio_real is False
    assert a1_quiz.audio_style == "placeholder-item"
    assert a1_quiz.item_count == 2
    assert a1_quiz.items_with_audio == 2


def test_audit_source_text_detection(source_dir):
    audits = audit_source(source_dir)
    a1_immersion = next(
        a for a in audits if a.module_level == "A1" and a.lesson_type == "listening_immersion"
    )
    assert a1_immersion.has_text is True
    assert a1_immersion.text_length > 0
    assert a1_immersion.has_translation is True


def test_audit_source_transcript_detection(source_dir):
    audits = audit_source(source_dir)
    b1_quiz = next(
        a for a in audits if a.module_level == "B1" and a.lesson_type == "listening_quiz"
    )
    assert b1_quiz.items_with_transcript == 1


# ---------------------------------------------------------------------------
# Unit tests: exclusion logic
# ---------------------------------------------------------------------------


def test_exclude_from_audio_requirement_immersion_with_text(source_dir):
    audits = audit_source(source_dir)
    immersion_audits = [a for a in audits if a.lesson_type == "listening_immersion"]
    # All immersion lessons in fixture have text
    for a in immersion_audits:
        assert a.exclude_from_audio_requirement is True
        assert a.exclusion_reason == "has_text_fallback"


def test_exclude_from_audio_requirement_quiz_never(source_dir):
    audits = audit_source(source_dir)
    quiz_audits = [a for a in audits if a.lesson_type == "listening_quiz"]
    for a in quiz_audits:
        assert a.exclude_from_audio_requirement is False


# ---------------------------------------------------------------------------
# Unit tests: build_source_summary
# ---------------------------------------------------------------------------


def test_build_source_summary_counts(source_dir):
    audits = audit_source(source_dir)
    summary = build_source_summary(audits)

    li_info = summary["listening_immersion"]
    assert li_info["total"] == 3
    assert li_info["by_level"] == {"A1": 1, "B1": 1, "C1": 1}

    lq_info = summary["listening_quiz"]
    assert lq_info["total"] == 2
    assert lq_info["by_level"] == {"A1": 1, "B1": 1}


def test_build_source_summary_audio_styles(source_dir):
    audits = audit_source(source_dir)
    summary = build_source_summary(audits)

    li_styles = summary["listening_immersion"]["audio_styles"]
    assert li_styles.get("placeholder-lesson", 0) == 1  # A1
    assert li_styles.get("lesson-level", 0) == 1  # B1
    assert li_styles.get("none", 0) == 1  # C1

    lq_styles = summary["listening_quiz"]["audio_styles"]
    assert lq_styles.get("placeholder-item", 0) == 2


def test_build_source_summary_audio_style_flags(source_dir):
    audits = audit_source(source_dir)
    summary = build_source_summary(audits)
    assert summary["listening_immersion"]["needs_lesson_level_audio"] is True
    assert summary["listening_immersion"]["needs_item_level_audio"] is False
    assert summary["listening_quiz"]["needs_lesson_level_audio"] is False
    assert summary["listening_quiz"]["needs_item_level_audio"] is True


def test_build_source_summary_excludable(source_dir):
    audits = audit_source(source_dir)
    summary = build_source_summary(audits)
    # All 3 immersion lessons have text → excludable
    assert summary["listening_immersion"]["excludable_count"] == 3
    # Quiz lessons are never excludable
    assert summary["listening_quiz"]["excludable_count"] == 0


# ---------------------------------------------------------------------------
# Unit tests: formatters
# ---------------------------------------------------------------------------


def test_format_markdown_smoke(source_dir):
    audits = audit_source(source_dir)
    report = build_report(audits, db_comparison=None)
    md = format_markdown(report)
    assert "Existing Listening Lesson Payload Audit" in md
    assert "listening_immersion" in md
    assert "listening_quiz" in md
    assert "placeholder" in md
    assert "Recommendations" in md


def test_format_json_valid(source_dir):
    audits = audit_source(source_dir)
    report = build_report(audits, db_comparison=None)
    raw = format_json(report)
    parsed = json.loads(raw)
    assert "source_summary" in parsed
    assert parsed["total_source_audits"] == 5


# ---------------------------------------------------------------------------
# Unit tests: main CLI
# ---------------------------------------------------------------------------


def test_main_writes_markdown_report(tmp_path, source_dir):
    out = tmp_path / "out.md"
    rc = main(["--source-dir", str(source_dir), "--output", str(out), "--format", "markdown", "--no-db"])
    assert rc == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Existing Listening Lesson Payload Audit" in content


def test_main_writes_json_report(tmp_path, source_dir):
    out = tmp_path / "out.json"
    rc = main(["--source-dir", str(source_dir), "--output", str(out), "--format", "json", "--no-db"])
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["total_source_audits"] == 5


def test_main_missing_source_dir(tmp_path):
    out = tmp_path / "out.md"
    rc = main(["--source-dir", str(tmp_path / "nonexistent"), "--output", str(out), "--no-db"])
    assert rc == 0  # graceful empty report
    assert out.exists()
