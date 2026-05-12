"""Tests for scripts/import_lesson_audio_metadata.py.

Uses a FakeRepository so no DB is required for unit tests.
The integration smoke test at the bottom verifies DBRepository
can be instantiated via db_session.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from import_lesson_audio_metadata import (  # noqa: E402
    DEFAULT_PATCH_FIELDS,
    AudioEntry,
    DBRepository,
    PatchPlan,
    Repository,
    apply_plan,
    filter_entries,
    format_report,
    load_entries,
    parse_entry,
    plan_patch,
)


# ---------------------------------------------------------------------------
# FakeRepository
# ---------------------------------------------------------------------------


@dataclass
class FakeLesson:
    id: int
    module_id: int
    number: int
    type: str
    content: dict


@dataclass
class FakeRepository(Repository):
    modules: dict = field(default_factory=dict)  # (level, module_number) -> module_id
    lessons: dict = field(default_factory=dict)  # id -> FakeLesson
    _next_id: int = 1

    def get_module_id(self, level: str, module_number: int) -> Optional[int]:
        return self.modules.get((level, module_number))

    def find_lesson_by_type(self, module_id: int, lesson_type: str) -> Optional[FakeLesson]:
        candidates = [
            l for l in self.lessons.values()
            if l.module_id == module_id and l.type == lesson_type
        ]
        return min(candidates, key=lambda l: l.number) if candidates else None

    def patch_lesson_content(self, lesson_id: int, patch: dict) -> None:
        lesson = self.lessons.get(lesson_id)
        if lesson is None:
            return
        lesson.content = {**lesson.content, **patch}

    def add_lesson(self, level: str, module_number: int, lesson_type: str, content: dict) -> int:
        module_id = self.modules[(level, module_number)]
        lid = self._next_id
        self._next_id += 1
        self.lessons[lid] = FakeLesson(
            id=lid,
            module_id=module_id,
            number=len(self.lessons) + 1,
            type=lesson_type,
            content=dict(content),
        )
        return lid


def make_repo(level="A1", module_number=1, lesson_type="listening_immersion") -> FakeRepository:
    repo = FakeRepository(modules={(level, module_number): 101})
    repo.add_lesson(level, module_number, lesson_type, {"audio": "[sound:A1_M1_L11_dialogue.mp3]"})
    return repo


def make_raw(**overrides) -> dict:
    base = {
        "level": "A1",
        "module_number": 1,
        "lesson_type": "listening_immersion",
        "audio_url": "/static/audio/A1_M1_L11_dialogue.mp3",
        "duration_seconds": 54,
        "external_key": "audio_meta:listening_immersion:A1:01",
        "needs_audio_file": True,
        "exclusion_reason": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_entry
# ---------------------------------------------------------------------------


def test_parse_entry_happy_path():
    entry, err = parse_entry(make_raw())
    assert err is None
    assert entry.level == "A1"
    assert entry.module_number == 1
    assert entry.lesson_type == "listening_immersion"
    assert entry.audio_url == "/static/audio/A1_M1_L11_dialogue.mp3"
    assert entry.duration_seconds == 54
    assert entry.needs_audio_file is True
    assert entry.exclusion_reason is None


def test_parse_entry_invalid_level():
    _, err = parse_entry(make_raw(level="X9"))
    assert err is not None
    assert "level" in err


def test_parse_entry_invalid_module_number():
    _, err = parse_entry(make_raw(module_number=0))
    assert err is not None
    assert "module_number" in err


def test_parse_entry_empty_audio_url():
    _, err = parse_entry(make_raw(audio_url=""))
    assert err is not None
    assert "audio_url" in err


def test_parse_entry_invalid_duration():
    _, err = parse_entry(make_raw(duration_seconds=0))
    assert err is not None
    assert "duration_seconds" in err


def test_parse_entry_not_a_dict():
    _, err = parse_entry("not a dict")
    assert err is not None


def test_parse_entry_patch_fields_subset():
    entry, err = parse_entry(make_raw(), patch_fields=("audio_url",))
    assert err is None
    assert "audio_url" in entry.patch_fields
    assert "duration_seconds" not in entry.patch_fields


def test_parse_entry_exclusion_reason_kept():
    entry, err = parse_entry(make_raw(exclusion_reason="no audio planned"))
    assert err is None
    assert entry.exclusion_reason == "no audio planned"


# ---------------------------------------------------------------------------
# load_entries
# ---------------------------------------------------------------------------


def test_load_entries_from_json_file(tmp_path):
    data = [make_raw(), make_raw(level="A2", module_number=2, external_key="k2")]
    p = tmp_path / "audio.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    entries, errors = load_entries([str(p)])
    assert errors == []
    assert len(entries) == 2


def test_load_entries_bad_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    entries, errors = load_entries([str(p)])
    assert entries == []
    assert len(errors) == 1


def test_load_entries_not_array(tmp_path):
    p = tmp_path / "obj.json"
    p.write_text('{"level": "A1"}', encoding="utf-8")
    _, errors = load_entries([str(p)])
    assert errors


# ---------------------------------------------------------------------------
# plan_patch
# ---------------------------------------------------------------------------


def test_plan_patch_action_patch():
    repo = make_repo()
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    assert len(plan.changes) == 1
    ch = plan.changes[0]
    assert ch.action == "patch"
    assert "audio_url" in ch.patched_fields
    assert "duration_seconds" in ch.patched_fields


def test_plan_patch_noop_when_already_set():
    repo = make_repo()
    # Pre-set the values that the entry would write
    lesson_id = list(repo.lessons.keys())[0]
    repo.lessons[lesson_id].content["audio_url"] = "/static/audio/A1_M1_L11_dialogue.mp3"
    repo.lessons[lesson_id].content["duration_seconds"] = 54
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    assert plan.changes[0].action == "noop"


def test_plan_patch_skip_no_module():
    repo = FakeRepository(modules={})
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    assert plan.changes[0].action == "skip_no_module"


def test_plan_patch_skip_no_lesson():
    repo = FakeRepository(modules={("A1", 1): 101})
    # No lesson added
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    assert plan.changes[0].action == "skip_no_lesson"


def test_plan_patch_skip_excluded():
    repo = make_repo()
    raw = make_raw(exclusion_reason="no audio planned")
    entries = [parse_entry(raw)[0]]
    plan = plan_patch(entries, repo)
    assert plan.changes[0].action == "skip_excluded"


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


def test_apply_plan_patches_content():
    repo = make_repo()
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    apply_plan(plan, entries, repo, dry_run=False)
    lesson = list(repo.lessons.values())[0]
    assert lesson.content["audio_url"] == "/static/audio/A1_M1_L11_dialogue.mp3"
    assert lesson.content["duration_seconds"] == 54


def test_apply_plan_dry_run_no_write():
    repo = make_repo()
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    apply_plan(plan, entries, repo, dry_run=True)
    lesson = list(repo.lessons.values())[0]
    # audio_url should NOT be set
    assert "audio_url" not in lesson.content


def test_apply_plan_idempotent():
    repo = make_repo()
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    apply_plan(plan, entries, repo, dry_run=False)
    # Second run
    plan2 = plan_patch(entries, repo)
    apply_plan(plan2, entries, repo, dry_run=False)
    assert plan2.changes[0].action == "noop"


def test_apply_plan_does_not_remove_existing_content():
    repo = make_repo()
    lesson_id = list(repo.lessons.keys())[0]
    repo.lessons[lesson_id].content["transcript"] = "Hello, my name is Anna."
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    apply_plan(plan, entries, repo, dry_run=False)
    lesson = repo.lessons[lesson_id]
    assert lesson.content.get("transcript") == "Hello, my name is Anna."
    assert lesson.content["audio_url"] == "/static/audio/A1_M1_L11_dialogue.mp3"


# ---------------------------------------------------------------------------
# filter_entries
# ---------------------------------------------------------------------------


def test_filter_entries_by_level():
    entries = [
        parse_entry(make_raw(level="A1"))[0],
        parse_entry(make_raw(level="A2", module_number=2, external_key="k2"))[0],
    ]
    result = filter_entries(entries, level="A1")
    assert len(result) == 1
    assert result[0].level == "A1"


def test_filter_entries_by_lesson_type():
    entries = [
        parse_entry(make_raw(lesson_type="listening_immersion"))[0],
        parse_entry(make_raw(lesson_type="listening_quiz", module_number=2, external_key="k2"))[0],
    ]
    result = filter_entries(entries, lesson_type="listening_immersion")
    assert len(result) == 1


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_contains_summary():
    repo = make_repo()
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    report = format_report(plan)
    assert "patch" in report
    assert "Summary" in report


def test_format_report_skip_section():
    repo = FakeRepository(modules={})
    entries = [parse_entry(make_raw())[0]]
    plan = plan_patch(entries, repo)
    report = format_report(plan)
    assert "skip_no_module" in report


def test_format_report_input_files():
    plan = PatchPlan()
    report = format_report(plan, input_files=["content/immersion/listening_immersion_audio.json"])
    assert "listening_immersion_audio.json" in report


# ---------------------------------------------------------------------------
# Integration: listening_immersion_audio.json round-trip parsing
# ---------------------------------------------------------------------------


def test_listening_immersion_audio_json_parses():
    data_file = (
        Path(__file__).resolve().parents[2]
        / "content"
        / "immersion"
        / "listening_immersion_audio.json"
    )
    assert data_file.exists(), f"Missing: {data_file}"
    entries, errors = load_entries([str(data_file)])
    assert errors == [], f"Parse errors: {errors}"
    assert len(entries) == 77, f"Expected 77 entries, got {len(entries)}"


def test_listening_immersion_audio_all_have_audio_url():
    data_file = (
        Path(__file__).resolve().parents[2]
        / "content"
        / "immersion"
        / "listening_immersion_audio.json"
    )
    entries, _ = load_entries([str(data_file)])
    for e in entries:
        assert e.audio_url.startswith("/static/audio/"), (
            f"{e.external_key}: audio_url={e.audio_url!r}"
        )
        assert e.duration_seconds > 0, f"{e.external_key}: duration={e.duration_seconds}"


def test_listening_immersion_audio_unique_keys():
    data_file = (
        Path(__file__).resolve().parents[2]
        / "content"
        / "immersion"
        / "listening_immersion_audio.json"
    )
    entries, _ = load_entries([str(data_file)])
    keys = [e.external_key for e in entries]
    assert len(keys) == len(set(keys)), "Duplicate external_key found"


def test_listening_immersion_audio_covers_all_levels():
    data_file = (
        Path(__file__).resolve().parents[2]
        / "content"
        / "immersion"
        / "listening_immersion_audio.json"
    )
    entries, _ = load_entries([str(data_file)])
    levels = {e.level for e in entries}
    assert levels == {"A1", "A2", "B1", "B2", "C1"}


# ---------------------------------------------------------------------------
# Integration smoke: DBRepository imports correctly
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_db_repository_smoke(db_session):
    repo = DBRepository(db_session)
    # get_module_id for A1/1 may return None on empty DB — just confirm no exception
    result = repo.get_module_id("A1", 1)
    assert result is None or isinstance(result, int)
