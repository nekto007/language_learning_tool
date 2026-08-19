"""Unit tests for scripts/sync_source_module_with_db.py.

Cover:
- batch flag parsing (--all, --level + --all-modules, --level + --module-number)
- 1..N renumbering of id/number/order
- dry-run does not mutate disk
- idempotency on re-run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

import sync_source_module_with_db as sync  # noqa: E402


def _scrambled_lessons() -> list[dict]:
    return [
        {"id": 99, "number": 99, "order": 99, "type": "vocabulary",
         "title": "v", "content": {}},
        {"id": 7, "number": 7, "order": 7, "type": "grammar",
         "title": "g", "content": {}},
        {"id": 3, "number": 3, "order": 3, "type": "final_test",
         "title": "f", "content": {}},
    ]


def _write_source(d: Path, filename: str, lessons: list[dict]) -> Path:
    payload = {"module": {"title": "Sample", "title_en": "Sample",
                          "level": "A1", "lessons": lessons}}
    p = d / filename
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    _write_source(d, "module_A1_1_greetings.json", _scrambled_lessons())
    _write_source(d, "module_A1_2_numbers.json", _scrambled_lessons())
    _write_source(d, "module_B2_1_topic.json", _scrambled_lessons())
    return d


def test_renumber_assigns_1_to_n(source_dir: Path):
    summary = sync.renumber_module("A1", 1, source_dir=source_dir, dry_run=False)
    assert summary["changed"] is True
    on_disk = json.loads((source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8"))
    lessons = on_disk["module"]["lessons"]
    for idx, l in enumerate(lessons, start=1):
        assert l["id"] == idx
        assert l["number"] == idx
        assert l["order"] == idx


def test_renumber_dry_run_does_not_write(source_dir: Path):
    before = (source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8")
    summary = sync.renumber_module("A1", 1, source_dir=source_dir, dry_run=True)
    after = (source_dir / "module_A1_1_greetings.json").read_text(encoding="utf-8")
    assert before == after
    assert summary["changed"] is True


def test_renumber_is_idempotent(source_dir: Path):
    sync.renumber_module("A1", 1, source_dir=source_dir, dry_run=False)
    summary = sync.renumber_module("A1", 1, source_dir=source_dir, dry_run=False)
    assert summary["changed"] is False


def test_renumber_batch_all(source_dir: Path):
    summaries = sync.renumber_batch(None, dry_run=False, source_dir=source_dir)
    assert len(summaries) == 3
    assert all(s.get("changed") is True for s in summaries)


def test_renumber_batch_level_filter(source_dir: Path):
    summaries = sync.renumber_batch(
        None, dry_run=True, source_dir=source_dir, level="A1",
    )
    assert len(summaries) == 2
    assert {(s["level"], s["module_number"]) for s in summaries} == {
        ("A1", 1), ("A1", 2),
    }


def test_cli_all_apply_writes_files(tmp_path: Path, source_dir: Path):
    rc = sync.main([
        "--all",
        "--apply",
        "--source-dir", str(source_dir),
    ])
    assert rc == 0
    on_disk = json.loads((source_dir / "module_B2_1_topic.json").read_text(encoding="utf-8"))
    assert on_disk["module"]["lessons"][0]["id"] == 1


def test_cli_dry_run_keeps_file_intact(source_dir: Path):
    before = (source_dir / "module_B2_1_topic.json").read_text(encoding="utf-8")
    rc = sync.main([
        "--all",
        "--dry-run",
        "--source-dir", str(source_dir),
    ])
    assert rc == 0
    after = (source_dir / "module_B2_1_topic.json").read_text(encoding="utf-8")
    assert before == after


def test_cli_apply_and_dry_run_mutually_exclusive():
    rc = sync.main(["--all", "--apply", "--dry-run"])
    assert rc == 2


def test_cli_all_modules_requires_level():
    rc = sync.main(["--all-modules"])
    assert rc == 2


def test_cli_needs_a_selector():
    rc = sync.main([])
    assert rc == 2
