"""Unit tests for scripts/audit_immersion_data.py.

These tests deliberately avoid spinning up the Flask app — they cover the
source-side logic (parsing module JSON, slot-critical-missing detection,
audio gap detection, format_markdown/json, reconciliation). The DB path is
exercised via `audit_db` in higher-level integration tests if/when needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from audit_immersion_data import (  # noqa: E402
    SLOT_CRITICAL_TYPES,
    audit_source,
    build_audit,
    format_json,
    format_markdown,
    load_source_modules,
    reconcile_source_vs_db,
)


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
                {"type": "vocabulary", "title": "vocab"},
                {"type": "grammar", "title": "g"},
                {
                    "type": "listening_immersion",
                    "title": "li",
                    "content": {"text": "hi"},
                },
                {
                    "type": "listening_quiz",
                    "title": "lq",
                    "content": {"audio_url": "/static/x.mp3"},
                },
                {"type": "dictation", "title": "d"},
                {"type": "writing_prompt", "title": "w"},
                {"type": "shadow_reading", "title": "sr"},
            ],
        },
    )
    _write_module(
        d,
        "module_A1_2_numbers.json",
        {
            "id": "a1-2",
            "title": "Numbers",
            "title_en": "Numbers",
            "level": "A1",
            "lessons": [
                {"type": "vocabulary", "title": "v"},
                {"type": "listening_immersion", "title": "li"},
            ],
        },
    )
    _write_module(
        d,
        "module_B2_5_culture.json",
        {
            "id": "b2-5",
            "title": "Culture",
            "title_en": "Culture",
            "level": "B2",
            "lessons": [
                {"type": "grammar", "title": "g"},
                {"type": "dictation", "title": "d"},
                {
                    "type": "listening_quiz",
                    "title": "lq",
                    "content": {
                        "items": [
                            {"text": "q1", "audio_url": "/static/q1.mp3"},
                        ]
                    },
                },
            ],
        },
    )
    return d


def test_load_source_modules_parses_filenames(source_dir):
    modules = load_source_modules(source_dir)
    assert {m.filename for m in modules} == {
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
    }
    by_name = {m.filename: m for m in modules}
    assert by_name["module_A1_1_greetings.json"].level == "A1"
    assert by_name["module_A1_1_greetings.json"].file_order == 1
    assert by_name["module_B2_5_culture.json"].file_order == 5
    assert len(by_name["module_A1_1_greetings.json"].lessons) == 7


def test_audit_source_counts_and_slot_missing(source_dir):
    modules = load_source_modules(source_dir)
    summary = audit_source(modules)
    assert summary["modules_total"] == 3
    assert summary["modules_by_level"] == {"A1": 2, "B2": 1}
    assert summary["lessons_total_by_type"]["vocabulary"] == 2
    assert summary["lessons_total_by_type"]["dictation"] == 2
    missing_dictation = summary["missing_slot_critical"]["dictation"]
    assert [m["filename"] for m in missing_dictation] == ["module_A1_2_numbers.json"]
    missing_writing = summary["missing_slot_critical"]["writing_prompt"]
    assert sorted(m["filename"] for m in missing_writing) == [
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
    ]
    missing_shadow = summary["missing_slot_critical"]["shadow_reading"]
    assert len(missing_shadow) == 2


def test_audit_source_detects_audio_gaps(source_dir):
    modules = load_source_modules(source_dir)
    summary = audit_source(modules)
    li_missing = summary["listening_missing_audio"]["listening_immersion"]
    assert sorted(m["filename"] for m in li_missing) == [
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
    ]
    lq_missing = summary["listening_missing_audio"]["listening_quiz"]
    assert lq_missing == []  # both listening_quiz lessons have audio


def test_reconcile_matches_by_order_and_title():
    src_modules = load_source_modules(
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "missing_dir_ignored"
    )
    # use synthetic objects via build_audit instead
    db_modules = [
        {"id": 10, "number": 1, "title": "Greetings", "level": "A1"},
        {"id": 99, "number": 7, "title": "Random Orphan", "level": "C1"},
    ]
    from audit_immersion_data import SourceModule

    src_modules = [
        SourceModule(
            filename="module_A1_1_greetings.json",
            level="A1",
            file_order=1,
            module_id="a1-1",
            title="Greetings",
            title_en="Greetings",
            order=None,
            lessons=[],
        ),
        SourceModule(
            filename="module_A1_2_numbers.json",
            level="A1",
            file_order=2,
            module_id="a1-2",
            title="Numbers",
            title_en="Numbers",
            order=None,
            lessons=[],
        ),
    ]
    rec = reconcile_source_vs_db(src_modules, db_modules)
    assert rec["matched_count"] == 1
    assert rec["matched"][0]["db_id"] == 10
    only_src = {m["filename"] for m in rec["only_in_source"]}
    assert only_src == {"module_A1_2_numbers.json"}
    only_db = {m["id"] for m in rec["only_in_db"]}
    assert only_db == {99}


def test_build_audit_without_db(source_dir):
    audit = build_audit(source_dir, db_session=None)
    assert "db" not in audit
    assert audit["source"]["modules_total"] == 3
    assert "new_lesson_types" in audit
    assert "slot_critical_types" in audit
    assert set(audit["slot_critical_types"]) == set(SLOT_CRITICAL_TYPES)


def test_format_markdown_smoke(source_dir):
    audit = build_audit(source_dir, db_session=None)
    md = format_markdown(audit)
    assert "Immersion Data Audit" in md
    assert "module_A1_1_greetings.json" in md
    assert "dictation" in md
    assert "shadow_reading" in md


def test_format_json_is_valid(source_dir):
    audit = build_audit(source_dir, db_session=None)
    raw = format_json(audit)
    parsed = json.loads(raw)
    assert parsed["source"]["modules_total"] == 3


def test_main_writes_report(tmp_path, source_dir, monkeypatch):
    import audit_immersion_data as mod

    out_path = tmp_path / "report.md"
    rc = mod.main(
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
    assert "Immersion Data Audit" in out_path.read_text(encoding="utf-8")


def test_main_writes_json(tmp_path, source_dir):
    import audit_immersion_data as mod

    out_path = tmp_path / "report.json"
    rc = mod.main(
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
    assert parsed["source"]["modules_total"] == 3