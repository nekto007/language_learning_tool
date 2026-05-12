"""Unit tests for `scripts/import_immersion_lessons.py`.

These tests exercise the pure-Python parsing/planning/apply layer through
an in-memory `FakeRepository`. The DBRepository class is covered by the
integration smoke test at the bottom of this file via `db_session`.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PATH))

from import_immersion_lessons import (  # noqa: E402
    DBRepository,
    ImportChange,
    Repository,
    apply_plan,
    diff_lesson_fields,
    filter_entries,
    format_report,
    load_lessons,
    parse_entry,
    plan_import,
)


# ---------------------------------------------------------------------------
# FakeRepository for pure-logic tests
# ---------------------------------------------------------------------------


@dataclass
class FakeLesson:
    id: int
    module_id: int
    number: int
    type: str
    title: str
    description: Optional[str]
    content: dict


@dataclass
class FakeRepository(Repository):
    modules: dict = field(default_factory=dict)  # (level, module_number) -> module_id
    lessons: dict = field(default_factory=dict)  # id -> FakeLesson
    _next_id: int = 1

    @classmethod
    def with_modules(cls, modules: dict):
        return cls(modules=dict(modules))

    def get_module_id(self, level, module_number):
        return self.modules.get((level, module_number))

    def find_lesson_by_external_key(self, external_key):
        for lesson in self.lessons.values():
            if (lesson.content or {}).get("external_key") == external_key:
                return lesson
        return None

    def next_lesson_number(self, module_id):
        nums = [
            l.number for l in self.lessons.values() if l.module_id == module_id
        ]
        return (max(nums) if nums else 0) + 1

    def lesson_number_taken(self, module_id, number, *, exclude_external_key=None):
        for lesson in self.lessons.values():
            if lesson.module_id == module_id and lesson.number == number:
                if (
                    exclude_external_key is not None
                    and (lesson.content or {}).get("external_key")
                    == exclude_external_key
                ):
                    return False
                return True
        return False

    def create_lesson(
        self, *, module_id, number, lesson_type, title, description, content
    ):
        new_id = max([*self.lessons.keys(), self._next_id - 1]) + 1
        self._next_id = new_id + 1
        self.lessons[new_id] = FakeLesson(
            id=new_id,
            module_id=module_id,
            number=number,
            type=lesson_type,
            title=title,
            description=description,
            content=dict(content or {}),
        )
        return new_id

    def update_lesson(
        self,
        lesson_id,
        *,
        lesson_type=None,
        title=None,
        description=None,
        content=None,
        number=None,
    ):
        lesson = self.lessons[lesson_id]
        if lesson_type is not None:
            lesson.type = lesson_type
        if title is not None:
            lesson.title = title
        if description is not None:
            lesson.description = description
        if content is not None:
            lesson.content = dict(content)
        if number is not None:
            lesson.number = number


def make_raw(**overrides):
    base = {
        "external_key": "dictation:A1:01:greetings",
        "level": "A1",
        "module_number": 1,
        "lesson_type": "dictation",
        "title": "Диктант: Приветствия",
        "title_en": "Dictation: Greetings",
        "content": {
            "audio_url": "/static/audio/dictation_a1_01.mp3",
            "transcript": "Hello, how are you?",
            "duration_seconds": 12,
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_entry
# ---------------------------------------------------------------------------


def test_parse_entry_happy_path():
    entry, err = parse_entry(make_raw())
    assert err is None
    assert entry.external_key == "dictation:A1:01:greetings"
    assert entry.level == "A1"
    assert entry.module_number == 1
    assert entry.lesson_type == "dictation"
    assert entry.title.startswith("Диктант")
    assert entry.content["transcript"] == "Hello, how are you?"
    assert entry.lesson_number is None
    assert entry.has_description is False


def test_parse_entry_rejects_missing_keys():
    raw = make_raw()
    del raw["content"]
    entry, err = parse_entry(raw)
    assert entry is None
    assert "missing keys" in err
    assert "content" in err


def test_parse_entry_rejects_unknown_level():
    entry, err = parse_entry(make_raw(level="ZZ"))
    assert entry is None
    assert "invalid level" in err


def test_parse_entry_rejects_zero_module_number():
    entry, err = parse_entry(make_raw(module_number=0))
    assert entry is None
    assert "invalid module_number" in err


def test_parse_entry_rejects_non_dict_content():
    entry, err = parse_entry(make_raw(content="not-a-dict"))
    assert entry is None
    assert "content must be an object" in err


def test_parse_entry_records_description_presence():
    entry, err = parse_entry(make_raw(description="hi"))
    assert err is None
    assert entry.has_description is True
    assert entry.description == "hi"

    entry_explicit_none, _ = parse_entry(make_raw(description=None))
    assert entry_explicit_none.has_description is True
    assert entry_explicit_none.description is None


def test_parse_entry_accepts_explicit_lesson_number():
    entry, err = parse_entry(make_raw(lesson_number=8))
    assert err is None
    assert entry.lesson_number == 8


def test_parse_entry_rejects_invalid_lesson_number():
    entry, err = parse_entry(make_raw(lesson_number=-3))
    assert entry is None
    assert "invalid lesson_number" in err


# ---------------------------------------------------------------------------
# load_lessons
# ---------------------------------------------------------------------------


def test_load_lessons_array(tmp_path: Path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps([make_raw(), make_raw(external_key="x:A1:02:k")]), encoding="utf-8")
    rows = load_lessons(path)
    assert len(rows) == 2


def test_load_lessons_jsonl(tmp_path: Path):
    path = tmp_path / "a.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(make_raw()),
                json.dumps(make_raw(external_key="x:A1:02:k")),
            ]
        ),
        encoding="utf-8",
    )
    rows = load_lessons(path)
    assert len(rows) == 2


def test_load_lessons_rejects_top_level_object(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_lessons(path)


def test_load_lessons_empty(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    assert load_lessons(path) == []


# ---------------------------------------------------------------------------
# filter_entries
# ---------------------------------------------------------------------------


def _entry(**kw):
    raw = make_raw(**kw)
    e, _ = parse_entry(raw)
    return e


def test_filter_entries_by_level():
    a = _entry(level="A1")
    b = _entry(level="B2", external_key="dictation:B2:01:k")
    kept, skipped = filter_entries([a, b], level="A1")
    assert kept == [a]
    assert len(skipped) == 1
    assert skipped[0].action == "skip_filtered"
    assert skipped[0].external_key == b.external_key


def test_filter_entries_by_lesson_type():
    a = _entry(lesson_type="dictation")
    b = _entry(lesson_type="writing_prompt", external_key="writing_prompt:A1:01:k")
    kept, skipped = filter_entries([a, b], lesson_type="writing_prompt")
    assert kept == [b]
    assert skipped[0].external_key == a.external_key


def test_filter_entries_skips_staging_by_default():
    a = _entry()
    b = _entry(external_key="x:A1:02:k", environment="staging")
    kept, skipped = filter_entries([a, b])
    assert kept == [a]
    assert skipped[0].action == "skip_environment"


def test_filter_entries_include_staging():
    a = _entry(environment="staging")
    kept, skipped = filter_entries([a], skip_staging=False)
    assert kept == [a]
    assert skipped == []


# ---------------------------------------------------------------------------
# plan_import
# ---------------------------------------------------------------------------


def test_plan_create_when_module_present_and_no_existing():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    plan = plan_import([_entry()], repo)
    assert plan.errors == []
    assert len(plan.changes) == 1
    c = plan.changes[0]
    assert c.action == "create"
    assert c.db_module_id == 100
    assert c.lesson_id is None


def test_plan_skip_when_module_missing():
    repo = FakeRepository.with_modules({})
    plan = plan_import([_entry()], repo)
    assert plan.changes[0].action == "skip_no_module"
    assert "no DB module" in plan.changes[0].reason


def test_plan_module_id_filter():
    repo = FakeRepository.with_modules({("A1", 1): 100, ("A2", 1): 200})
    e_a1 = _entry(level="A1", module_number=1, external_key="x:A1:01:k")
    e_a2 = _entry(level="A2", module_number=1, external_key="x:A2:01:k")
    plan = plan_import([e_a1, e_a2], repo, db_module_id=200)
    actions = sorted(c.action for c in plan.changes)
    assert actions == ["create", "skip_filtered"]
    skipped = next(c for c in plan.changes if c.action == "skip_filtered")
    assert skipped.external_key == "x:A1:01:k"
    assert skipped.db_module_id == 100


def test_plan_update_only_when_content_differs():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry()
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title=e.title,
        description=None,
        content={**e.content, "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    assert [c.action for c in plan.changes] == ["noop"]


def test_plan_update_detects_title_and_content_changes():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry()
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title="Старое название",
        description=None,
        content={"transcript": "old", "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    assert plan.changes[0].action == "update"
    assert "title" in plan.changes[0].diff_fields
    assert "content" in plan.changes[0].diff_fields
    assert plan.changes[0].lesson_id == 1


def test_plan_duplicate_external_key_is_error():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    plan = plan_import([_entry(), _entry()], repo)
    assert plan.errors
    assert "duplicate external_key" in plan.errors[0]


def test_plan_lesson_number_collision_creates_error():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    # Pre-existing unrelated lesson at number 5
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=5,
        type="vocabulary",
        title="vocab",
        description=None,
        content={"external_key": "vocab:A1:01:x"},
    )
    e = _entry(lesson_number=5)
    plan = plan_import([e], repo)
    assert plan.errors
    assert any("lesson_number 5" in err for err in plan.errors)


def test_plan_explicit_lesson_number_owned_by_same_key_does_not_collide():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry(lesson_number=7)
    # Existing lesson has the same external_key at number 7
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title=e.title,
        description=None,
        content={**e.content, "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    assert plan.errors == []
    assert plan.changes[0].action == "noop"


def test_plan_rejects_move_to_taken_number():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry(lesson_number=10)
    # Existing lesson with our key currently at #7
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title=e.title,
        description=None,
        content={**e.content, "external_key": e.external_key},
    )
    # Another lesson sitting at #10
    repo.lessons[2] = FakeLesson(
        id=2,
        module_id=100,
        number=10,
        type="quiz",
        title="quiz",
        description=None,
        content={"external_key": "quiz:A1:01:y"},
    )
    plan = plan_import([e], repo)
    assert plan.errors
    assert any("cannot move to lesson_number 10" in err for err in plan.errors)


def test_plan_errors_when_existing_lesson_in_other_module():
    repo = FakeRepository.with_modules({("A1", 1): 100, ("A1", 2): 200})
    e = _entry(level="A1", module_number=2, external_key="dictation:A1:02:foo")
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,  # wrong module
        number=3,
        type=e.lesson_type,
        title=e.title,
        description=None,
        content={**e.content, "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    assert plan.errors
    assert any("belongs to module" in err for err in plan.errors)


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


def test_apply_plan_creates_lesson_with_external_key_in_content():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry()
    plan = plan_import([e], repo)
    apply_plan([e], plan, repo)
    assert len(repo.lessons) == 1
    lesson = next(iter(repo.lessons.values()))
    assert lesson.module_id == 100
    assert lesson.number == 1
    assert lesson.type == "dictation"
    assert lesson.title == e.title
    assert lesson.content["external_key"] == e.external_key
    assert lesson.content["transcript"] == "Hello, how are you?"


def test_apply_plan_is_idempotent():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry()
    plan = plan_import([e], repo)
    apply_plan([e], plan, repo)
    plan2 = plan_import([e], repo)
    assert plan2.errors == []
    assert [c.action for c in plan2.changes] == ["noop"]
    # No new lesson added by second apply
    apply_plan([e], plan2, repo)
    assert len(repo.lessons) == 1


def test_apply_plan_updates_only_diff_fields():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry()
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title="Старое",
        description="orig",
        content={"transcript": "old", "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    apply_plan([e], plan, repo)
    lesson = repo.lessons[1]
    assert lesson.title == e.title
    assert lesson.content["transcript"] == e.content["transcript"]
    # description not in raw -> preserved
    assert lesson.description == "orig"
    # number untouched -> preserved
    assert lesson.number == 7


def test_apply_plan_updates_description_when_explicit():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    e = _entry(description="нов")
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type=e.lesson_type,
        title=e.title,
        description="old",
        content={**e.content, "external_key": e.external_key},
    )
    plan = plan_import([e], repo)
    assert plan.changes[0].action == "update"
    assert "description" in plan.changes[0].diff_fields
    apply_plan([e], plan, repo)
    assert repo.lessons[1].description == "нов"


def test_apply_plan_preserves_unrelated_lesson():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=1,
        type="vocabulary",
        title="vocab",
        description=None,
        content={"external_key": "vocab:A1:01:x"},
    )
    e = _entry()
    plan = plan_import([e], repo)
    apply_plan([e], plan, repo)
    # Vocabulary lesson untouched
    assert repo.lessons[1].type == "vocabulary"
    assert repo.lessons[1].content["external_key"] == "vocab:A1:01:x"
    # New dictation present
    created_keys = {l.content["external_key"] for l in repo.lessons.values()}
    assert e.external_key in created_keys


# ---------------------------------------------------------------------------
# diff_lesson_fields / format_report
# ---------------------------------------------------------------------------


def test_diff_lesson_fields_picks_up_type_and_number_when_explicit():
    e = _entry(lesson_number=9)
    existing = FakeLesson(
        id=1,
        module_id=100,
        number=7,
        type="audio_fill_blank",
        title=e.title,
        description=None,
        content={**e.content, "external_key": e.external_key},
    )
    diff = diff_lesson_fields(existing, e)
    assert "type" in diff
    assert "number" in diff
    assert "title" not in diff
    assert "content" not in diff


def test_format_report_contains_counts_and_actions():
    plan = plan_import([_entry()], FakeRepository.with_modules({("A1", 1): 100}))
    text = format_report(plan, [Path("dummy.json")], dry_run=True)
    assert "Immersion Lesson Import Report" in text
    assert "dry-run" in text
    assert "create" in text


# ---------------------------------------------------------------------------
# CLI entry point (no-DB path: failure via missing files)
# ---------------------------------------------------------------------------


def test_main_returns_2_when_file_missing(tmp_path, capsys):
    import import_immersion_lessons as mod

    rc = mod.main([str(tmp_path / "nope.json"), "--dry-run", "--source-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "file not found" in err


def test_main_returns_2_on_parse_error(tmp_path, capsys):
    import import_immersion_lessons as mod

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"foo": "bar"}]), encoding="utf-8")
    rc = mod.main([str(bad), "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing keys" in err


def test_main_returns_2_on_malformed_json(tmp_path, capsys):
    import import_immersion_lessons as mod

    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    rc = mod.main([str(bad), "--dry-run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err


# ---------------------------------------------------------------------------
# DBRepository smoke test (requires the Flask app and DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_db_repository_round_trip(db_session):
    """End-to-end: create a level/module, run importer, verify idempotency."""
    from app.curriculum.models import CEFRLevel, Lessons, Module

    session = db_session
    level = CEFRLevel(code="A1", name="A1", order=1)
    session.add(level)
    session.flush()
    module = Module(level_id=level.id, number=1, title="M1")
    session.add(module)
    session.flush()

    e_raw = make_raw()
    e, err = parse_entry(e_raw)
    assert err is None
    repo = DBRepository(session)
    plan = plan_import([e], repo)
    assert plan.errors == []
    assert plan.changes[0].action == "create"
    apply_plan([e], plan, repo)
    session.flush()

    rows = (
        session.query(Lessons)
        .filter(Lessons.module_id == module.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].type == "dictation"
    assert rows[0].content["external_key"] == e.external_key

    # Second run: noop
    plan2 = plan_import([e], repo)
    assert [c.action for c in plan2.changes] == ["noop"]
    apply_plan([e], plan2, repo)
    rows2 = (
        session.query(Lessons)
        .filter(Lessons.module_id == module.id)
        .all()
    )
    assert len(rows2) == 1
