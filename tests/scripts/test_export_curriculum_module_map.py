"""Unit tests for scripts/export_curriculum_module_map.py.

DB access is intentionally avoided — tests cover row construction, CSV
formatting, and DB-state injection via stubs.
"""
from __future__ import annotations

import csv
import json
import sys
from io import StringIO
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from export_curriculum_module_map import (  # noqa: E402
    CSV_HEADERS,
    LISTENING_TYPES,
    build_rows,
    collect_mismatches,
    rows_to_csv,
)
from audit_immersion_data import load_source_modules  # noqa: E402


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
            "id": 1,
            "title": "Знакомство",
            "title_en": "Greetings",
            "level": "A1",
            "order": 1,
            "lessons": [
                {"id": 1, "order": 1, "type": "vocabulary", "title": "vocab"},
                {"id": 2, "order": 2, "type": "flashcards", "title": "fc"},
                {"id": 3, "order": 3, "type": "grammar", "title": "g"},
                {"id": 4, "order": 4, "type": "listening_quiz", "title": "lq"},
                {"id": 5, "order": 5, "type": "translation_quiz", "title": "tq"},
                {"id": 6, "order": 6, "type": "listening_immersion", "title": "li"},
            ],
        },
    )
    _write_module(
        d,
        "module_A1_2_numbers.json",
        {
            "id": 2,
            "title": "Числа",
            "title_en": "Numbers",
            "level": "A1",
            "lessons": [
                {"type": "vocabulary", "title": "v"},
                {"type": "listening_immersion", "title": "li2"},
            ],
        },
    )
    _write_module(
        d,
        "module_B2_5_culture.json",
        {
            "id": 5,
            "title": "Культура",
            "title_en": "Culture",
            "level": "B2",
            "lessons": [
                {"order": 1, "type": "grammar", "title": "g"},
                {"order": 2, "type": "listening_quiz", "title": "lq"},
            ],
        },
    )
    return d


def test_build_rows_without_db(source_dir):
    modules = load_source_modules(source_dir)
    rows = build_rows(modules, db_state=None)
    assert [r["source_filename"] for r in rows] == [
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
    ]
    for r in rows:
        assert r["db_match_status"] == "unknown"
        assert r["db_module_id"] == ""
        assert r["listening_quiz_lesson_ids"] == ""
        assert r["translation_quiz_lesson_ids"] == ""
        assert r["listening_immersion_lesson_ids"] == ""

    greetings = rows[0]
    assert greetings["level"] == "A1"
    assert greetings["file_order"] == 1
    assert greetings["source_module_id"] == "1"
    assert greetings["title"] == "Знакомство"
    assert greetings["title_en"] == "Greetings"
    assert greetings["source_lesson_count"] == 6
    assert greetings["source_lesson_order"] == (
        "1:vocabulary|2:flashcards|3:grammar|"
        "4:listening_quiz|5:translation_quiz|6:listening_immersion"
    )

    # Module with no explicit lesson order falls back to '?<index>:type'.
    numbers = rows[1]
    assert numbers["source_lesson_order"] == "?1:vocabulary|?2:listening_immersion"


def test_build_rows_with_db_matches_and_mismatches(source_dir):
    modules = load_source_modules(source_dir)
    db_state = {
        "modules": [
            # Match A1/1 by (level, file_order)
            {"id": 101, "number": 1, "title": "Greetings DB", "level": "A1"},
            # Match A1/2 by title fallback (different number)
            {"id": 102, "number": 99, "title": "Числа", "level": "A1"},
            # B2/5 source has no DB entry — only_in_source
            # Add an orphan only-in-DB module
            {"id": 999, "number": 7, "title": "Orphan", "level": "C1"},
        ],
        "lessons_by_module_type": {
            (101, "listening_quiz"): [501, 502],
            (101, "translation_quiz"): [503],
            (101, "listening_immersion"): [504],
            (102, "listening_immersion"): [510],
        },
    }
    rows = build_rows(modules, db_state=db_state)

    greetings, numbers, culture = rows
    assert greetings["db_match_status"] == "matched"
    assert greetings["db_module_id"] == 101
    assert greetings["db_module_title"] == "Greetings DB"
    assert greetings["listening_quiz_lesson_ids"] == "501|502"
    assert greetings["translation_quiz_lesson_ids"] == "503"
    assert greetings["listening_immersion_lesson_ids"] == "504"

    assert numbers["db_match_status"] == "matched"
    assert numbers["db_module_id"] == 102
    assert numbers["listening_immersion_lesson_ids"] == "510"
    assert numbers["listening_quiz_lesson_ids"] == ""

    assert culture["db_match_status"] == "only_in_source"
    assert culture["db_module_id"] == ""


def test_rows_to_csv_has_expected_headers(source_dir):
    modules = load_source_modules(source_dir)
    rows = build_rows(modules, db_state=None)
    text = rows_to_csv(rows)
    reader = csv.DictReader(StringIO(text))
    assert reader.fieldnames == CSV_HEADERS
    parsed = list(reader)
    assert len(parsed) == len(rows)
    assert parsed[0]["source_filename"] == "module_A1_1_greetings.json"


def test_collect_mismatches_reports_orphans(source_dir):
    modules = load_source_modules(source_dir)
    db_state = {
        "modules": [
            {"id": 101, "number": 1, "title": "Greetings DB", "level": "A1"},
            {"id": 999, "number": 7, "title": "Orphan", "level": "C1"},
        ],
        "lessons_by_module_type": {},
    }
    rows = build_rows(modules, db_state=db_state)
    mismatches = collect_mismatches(rows, db_state)
    assert mismatches["matched"] == 1
    assert {m["source_filename"] for m in mismatches["only_in_source"]} == {
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
    }
    assert {m["id"] for m in mismatches["only_in_db"]} == {999}


def test_listening_types_constant_is_aligned():
    # Guard against silent drift if anyone reorders/renames columns.
    expected_cols = {f"{t}_lesson_ids" for t in LISTENING_TYPES}
    assert expected_cols.issubset(set(CSV_HEADERS))


def test_main_writes_csv(tmp_path, source_dir):
    import export_curriculum_module_map as mod

    out_path = tmp_path / "module_map.csv"
    rc = mod.main(
        [
            "--source-dir",
            str(source_dir),
            "--output",
            str(out_path),
            "--no-db",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    reader = csv.DictReader(StringIO(out_path.read_text(encoding="utf-8")))
    rows = list(reader)
    assert {r["source_filename"] for r in rows} == {
        "module_A1_1_greetings.json",
        "module_A1_2_numbers.json",
        "module_B2_5_culture.json",
    }
    # --no-db means db_match_status is 'unknown'
    assert all(r["db_match_status"] == "unknown" for r in rows)
