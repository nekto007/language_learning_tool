"""Unit tests for scripts/report_immersion_gaps.py.

The gap reporter consumes `build_audit` output, so these tests reuse the
same synthetic source-module fixture pattern used in
`test_audit_immersion_data.py`. We exercise:

* slot-critical gap detection from source modules,
* CEFR coverage matrix when only source data is available,
* CEFR coverage matrix when a synthetic "db" dict is injected (no Flask),
* audio-metadata gap surfacing,
* reconciliation + vocabulary + SRS gaps when DB-shaped data is injected,
* markdown / JSON formatters, and
* CLI entrypoint writing the report to disk.

We never spin up the real Flask app — DB-shaped data is constructed in
the test by monkey-patching `build_audit` to return a deterministic
payload that mirrors what `audit_immersion_data.build_audit` would yield
on a primed DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

import report_immersion_gaps as gaps  # noqa: E402


def _write_module(dir_path: Path, filename: str, module_payload: dict) -> None:
    (dir_path / filename).write_text(
        json.dumps({"module": module_payload}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "modules"
    d.mkdir()
    _write_module(
        d,
        "module_A1_1_greetings.json",
        {
            "id": "a1-1",
            "title": "Greetings",
            "title_en": "Greetings",
            "level": "A1",
            "lessons": [
                {"type": "vocabulary", "title": "v"},
                {"type": "dictation", "title": "d"},
                {"type": "writing_prompt", "title": "w"},
                {"type": "shadow_reading", "title": "sr"},
                {
                    "type": "listening_immersion",
                    "title": "li",
                    "content": {"audio_url": "/static/li.mp3"},
                },
                {
                    "type": "listening_quiz",
                    "title": "lq",
                    "content": {"text": "no audio"},
                },
            ],
        },
    )
    _write_module(
        d,
        "module_A2_3_food.json",
        {
            "id": "a2-3",
            "title": "Food",
            "title_en": "Food",
            "level": "A2",
            "lessons": [
                {"type": "vocabulary", "title": "v"},
                {"type": "grammar", "title": "g"},
                {
                    "type": "listening_immersion",
                    "title": "li",
                    "content": {"text": "no audio"},
                },
            ],
        },
    )
    return d


def test_source_only_report_marks_db_unavailable(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None)
    assert report["db_available"] is False
    assert report["vocabulary"]["available"] is False
    assert report["srs_source"]["available"] is False
    assert report["reconciliation"]["summary"]["available"] is False


def test_slot_critical_gaps_from_source(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None)
    summary = report["slot_critical"]["summary"]
    # A1 has all three slot-critical lessons; A2 has none of them.
    assert summary["dictation"] == 1
    assert summary["writing_prompt"] == 1
    assert summary["shadow_reading"] == 1
    a2_missing = [
        m for m in report["slot_critical"]["missing"]["dictation"]
        if m["level"] == "A2"
    ]
    assert len(a2_missing) == 1
    assert a2_missing[0]["filename"] == "module_A2_3_food.json"


def test_audio_metadata_gaps_from_source(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None)
    li = report["audio_metadata"]["listening_immersion"]
    lq = report["audio_metadata"]["listening_quiz"]
    # A1 listening_immersion has audio, A2 does not.
    assert li["source_missing"] == 1
    assert "db_missing" not in li
    # A1 listening_quiz has no audio.
    assert lq["source_missing"] == 1


def test_cefr_coverage_matrix_uses_source_counts(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None, min_coverage_per_level=1)
    matrix = report["cefr_coverage"]["matrix"]
    # A1 has dictation; A2 does not.
    assert matrix["dictation"]["A1"] == 1
    assert matrix["dictation"]["A2"] == 0
    # CEFR gap rows should list every (new_type, level) where count < 1.
    gap_keys = {(g["lesson_type"], g["level"]) for g in report["cefr_coverage"]["gaps"]}
    assert ("dictation", "A2") in gap_keys
    assert ("writing_prompt", "A2") in gap_keys
    # New types never present in source ⇒ all levels are gaps.
    assert ("idiom", "A1") in gap_keys
    assert ("idiom", "A2") in gap_keys


def test_min_coverage_threshold_is_respected(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None, min_coverage_per_level=2)
    matrix = report["cefr_coverage"]["matrix"]
    # A1 has only one dictation lesson — threshold 2 ⇒ still a gap.
    assert matrix["dictation"]["A1"] == 1
    gap_keys = {(g["lesson_type"], g["level"]) for g in report["cefr_coverage"]["gaps"]}
    assert ("dictation", "A1") in gap_keys


def test_injected_db_payload_drives_reconciliation_and_vocab_srs(monkeypatch, source_dir):
    """Simulate a DB-loaded audit by monkey-patching build_audit."""
    fake_audit = {
        "source_dir": str(source_dir),
        "source": {
            "modules_by_level": {"A1": 1, "A2": 1},
            "modules_total": 2,
            "lessons_per_level_type": {
                "A1": {"vocabulary": 1, "dictation": 1, "listening_immersion": 1, "listening_quiz": 1, "writing_prompt": 1, "shadow_reading": 1},
                "A2": {"vocabulary": 1, "grammar": 1, "listening_immersion": 1},
            },
            "lessons_total_by_type": {
                "vocabulary": 2,
                "dictation": 1,
                "writing_prompt": 1,
                "shadow_reading": 1,
                "listening_immersion": 2,
                "listening_quiz": 1,
                "grammar": 1,
            },
            "missing_slot_critical": {
                "dictation": [{"filename": "module_A2_3_food.json", "level": "A2", "file_order": 3, "title": "Food"}],
                "writing_prompt": [{"filename": "module_A2_3_food.json", "level": "A2", "file_order": 3, "title": "Food"}],
                "shadow_reading": [{"filename": "module_A2_3_food.json", "level": "A2", "file_order": 3, "title": "Food"}],
            },
            "listening_missing_audio": {
                "listening_immersion": [{"filename": "module_A2_3_food.json", "level": "A2", "file_order": 3, "title": "Food"}],
                "listening_quiz": [{"filename": "module_A1_1_greetings.json", "level": "A1", "file_order": 1, "title": "Greetings"}],
            },
        },
        "new_lesson_types": list(gaps.NEW_LESSON_TYPES),
        "slot_critical_types": list(gaps.SLOT_CRITICAL_TYPES),
        "db": {
            "modules_by_level": {"A1": 1},
            "modules_total": 1,
            "db_modules": [{"id": 10, "number": 1, "title": "Greetings", "level": "A1"}],
            "lessons_per_level_type": {
                "A1": {"vocabulary": 1, "dictation": 1, "writing_prompt": 1, "shadow_reading": 1},
            },
            "lessons_total_by_type": {
                "vocabulary": 1,
                "dictation": 1,
                "writing_prompt": 1,
                "shadow_reading": 1,
            },
            "missing_slot_critical": {
                "dictation": [],
                "writing_prompt": [],
                "shadow_reading": [],
            },
            "listening_missing_audio": {
                "listening_immersion": [{"id": 11, "module_id": 10, "title": "li"}],
                "listening_quiz": [],
            },
            "vocab_coverage": {
                "total_words": 1000,
                "ipa_transcription": 200,
                "frequency_band": 0,
                "synonyms": 50,
                "antonyms": 50,
                "etymology": 0,
                "word_collocations_rows": 5,
                "cultural_notes_rows": 0,
            },
            "srs_source": {
                "total_card_directions": 100,
                "with_source": 40,
                "without_source": 60,
                "breakdown": {"null": 60, "manual": 40},
            },
        },
        "reconciliation": {
            "matched_count": 1,
            "matched": [{"filename": "module_A1_1_greetings.json", "level": "A1", "file_order": 1, "source_title": "Greetings", "db_id": 10, "db_title": "Greetings", "db_number": 1}],
            "only_in_source": [{"filename": "module_A2_3_food.json", "level": "A2", "file_order": 3, "title": "Food"}],
            "only_in_db": [],
        },
    }
    monkeypatch.setattr(gaps, "build_audit", lambda src, db_session=None: fake_audit)
    report = gaps.build_gap_report(source_dir, db_session="sentinel")

    # Reconciliation should be live.
    assert report["reconciliation"]["summary"]["available"] is True
    assert report["reconciliation"]["summary"]["only_in_source"] == 1
    assert report["reconciliation"]["only_in_source"][0]["filename"] == "module_A2_3_food.json"

    # CEFR coverage should now come from DB (not source).
    matrix = report["cefr_coverage"]["matrix"]
    assert matrix["dictation"]["A1"] == 1
    assert matrix["dictation"]["A2"] == 0  # A2 isn't in DB modules at all

    # Audio gaps include DB counts now.
    assert report["audio_metadata"]["listening_immersion"]["db_missing"] == 1
    assert report["audio_metadata"]["listening_quiz"]["db_missing"] == 0

    # Vocabulary gaps populated.
    assert report["vocabulary"]["available"] is True
    assert report["vocabulary"]["total_words"] == 1000
    ipa_row = next(f for f in report["vocabulary"]["fields"] if f["field"] == "ipa_transcription")
    assert ipa_row["filled"] == 200
    assert ipa_row["missing"] == 800
    assert ipa_row["coverage_pct"] == 20.0

    # SRS gaps populated.
    assert report["srs_source"]["available"] is True
    assert report["srs_source"]["without_source"] == 60


def test_format_markdown_smoke(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None)
    md = gaps.format_markdown(report)
    assert "Immersion Content Gap Report" in md
    assert "Missing slot-critical lesson types" in md
    assert "Missing CEFR coverage per new lesson type" in md
    assert "Audio metadata gaps" in md
    assert "Vocabulary enrichment gaps" in md
    assert "SRS source tagging gaps" in md
    assert "dictation" in md


def test_format_json_is_valid(source_dir):
    report = gaps.build_gap_report(source_dir, db_session=None)
    raw = gaps.format_json(report)
    parsed = json.loads(raw)
    assert "slot_critical" in parsed
    assert "cefr_coverage" in parsed


def test_main_writes_markdown_report(tmp_path, source_dir):
    out_path = tmp_path / "gap.md"
    rc = gaps.main(
        [
            "--source-dir",
            str(source_dir),
            "--output",
            str(out_path),
            "--format",
            "markdown",
            "--no-db",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "Immersion Content Gap Report" in text


def test_main_writes_json_report(tmp_path, source_dir):
    out_path = tmp_path / "gap.json"
    rc = gaps.main(
        [
            "--source-dir",
            str(source_dir),
            "--output",
            str(out_path),
            "--format",
            "json",
            "--no-db",
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert "slot_critical" in parsed
    assert parsed["db_available"] is False
