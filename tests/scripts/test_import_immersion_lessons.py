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
    AUDIO_REQUIRED_TYPES,
    DBRepository,
    ImportChange,
    Repository,
    apply_plan,
    diff_lesson_fields,
    filter_entries,
    format_report,
    load_canonical_module_ids,
    load_lessons,
    parse_entry,
    plan_import,
    validate_entries,
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

    def find_lesson_number_by_type(self, module_id, lesson_type):
        nums = [
            l.number
            for l in self.lessons.values()
            if l.module_id == module_id and l.type == lesson_type
        ]
        return min(nums) if nums else None

    def shift_module_lessons_above(self, module_id, threshold):
        affected = [
            l
            for l in self.lessons.values()
            if l.module_id == module_id and l.number >= threshold
        ]
        for lesson in affected:
            lesson.number += 1
        return len(affected)


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


# ---------------------------------------------------------------------------
# anchor_after positional insertion (Task 17)
# ---------------------------------------------------------------------------


def _seed_module_with_anchor(repo, module_id):
    """Seed a module with listening_quiz at #6 and dependent lessons after."""
    types = [
        (1, "vocabulary"),
        (2, "card"),
        (3, "grammar"),
        (4, "quiz"),
        (5, "reading"),
        (6, "listening_quiz"),
        (7, "dialogue_completion_quiz"),
        (8, "ordering_quiz"),
        (9, "card"),
        (10, "translation_quiz"),
        (11, "listening_immersion"),
        (12, "final_test"),
    ]
    for i, (n, t) in enumerate(types, start=1):
        repo.lessons[i] = FakeLesson(
            id=i,
            module_id=module_id,
            number=n,
            type=t,
            title=f"{t} #{n}",
            description=None,
            content={"external_key": f"seed:{t}:{n}"},
        )
    repo._next_id = 100
    return repo


def test_plan_anchor_after_targets_position_after_anchor():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    _seed_module_with_anchor(repo, 100)
    e = _entry()
    plan = plan_import([e], repo, anchor_after="listening_quiz")
    assert plan.errors == []
    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.action == "create"
    assert change.target_number == 7
    assert change.shift_above == 7
    assert change.anchor_type == "listening_quiz"


def test_apply_anchor_after_shifts_existing_lessons_and_inserts():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    _seed_module_with_anchor(repo, 100)
    e = _entry()
    plan = plan_import([e], repo, anchor_after="listening_quiz")
    apply_plan([e], plan, repo)
    # Dictation now at #7
    by_number = {l.number: l for l in repo.lessons.values() if l.module_id == 100}
    assert by_number[7].type == "dictation"
    assert by_number[7].content["external_key"] == e.external_key
    # listening_quiz still at #6
    assert by_number[6].type == "listening_quiz"
    # everything below shifted by +1
    assert by_number[8].type == "dialogue_completion_quiz"
    assert by_number[12].type == "listening_immersion"
    assert by_number[13].type == "final_test"


def test_anchor_after_is_idempotent_on_rerun():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    _seed_module_with_anchor(repo, 100)
    e = _entry()
    plan = plan_import([e], repo, anchor_after="listening_quiz")
    apply_plan([e], plan, repo)
    initial_count = len(repo.lessons)
    plan2 = plan_import([e], repo, anchor_after="listening_quiz")
    assert plan2.errors == []
    assert [c.action for c in plan2.changes] == ["noop"]
    apply_plan([e], plan2, repo)
    assert len(repo.lessons) == initial_count


def test_plan_anchor_after_missing_anchor_is_error():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    # Module has lessons but no listening_quiz
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=1,
        type="vocabulary",
        title="v",
        description=None,
        content={"external_key": "seed:v:1"},
    )
    e = _entry()
    plan = plan_import([e], repo, anchor_after="listening_quiz")
    assert plan.errors
    assert any("anchor lesson_type" in err for err in plan.errors)


def test_plan_anchor_after_skips_shift_when_slot_empty():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    # listening_quiz at #6, nothing after it
    repo.lessons[1] = FakeLesson(
        id=1,
        module_id=100,
        number=6,
        type="listening_quiz",
        title="lq",
        description=None,
        content={"external_key": "seed:lq:6"},
    )
    e = _entry()
    plan = plan_import([e], repo, anchor_after="listening_quiz")
    assert plan.errors == []
    change = plan.changes[0]
    assert change.action == "create"
    assert change.target_number == 7
    assert change.shift_above is None


def test_entry_level_anchor_after_overrides_global():
    repo = FakeRepository.with_modules({("A1", 1): 100})
    _seed_module_with_anchor(repo, 100)
    raw = make_raw()
    raw["anchor_after"] = "listening_quiz"
    entry, err = parse_entry(raw)
    assert err is None
    plan = plan_import([entry], repo, anchor_after="vocabulary")
    # Per-entry anchor wins → still anchored after listening_quiz
    change = plan.changes[0]
    assert change.anchor_type == "listening_quiz"
    assert change.target_number == 7


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
# validate_entries / load_canonical_module_ids (Task 11)
# ---------------------------------------------------------------------------


def test_load_canonical_module_ids_reads_filenames(tmp_path: Path):
    (tmp_path / "module_A1_01_greetings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "module_B2_07_advanced.json").write_text("{}", encoding="utf-8")
    (tmp_path / "module_invalid.json").write_text("{}", encoding="utf-8")
    (tmp_path / "not_a_module.txt").write_text("", encoding="utf-8")
    ids = load_canonical_module_ids(tmp_path)
    assert ids == {("A1", 1), ("B2", 7)}


def test_load_canonical_module_ids_missing_dir():
    assert load_canonical_module_ids(Path("/no/such/dir/here")) == set()


def test_validate_entries_passes_for_clean_dictation():
    entry = _entry()
    errors = validate_entries(
        [entry],
        canonical_module_ids={(entry.level, entry.module_number)},
    )
    assert errors == []


def test_validate_entries_rejects_module_missing_from_source():
    entry = _entry()
    errors = validate_entries(
        [entry],
        canonical_module_ids={("B2", 99)},  # different module
    )
    assert any("not in canonical source directory" in e for e in errors)
    assert any(entry.external_key in e for e in errors)


def test_validate_entries_skips_source_check_when_none():
    entry = _entry()
    errors = validate_entries([entry], canonical_module_ids=None)
    assert errors == []


def test_validate_entries_detects_missing_audio_url():
    raw = make_raw()
    raw["content"] = {"transcript": "Hello world"}  # no audio_url
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries([entry], canonical_module_ids=None)
    assert any("requires non-empty content.audio_url" in e for e in errors)


def test_validate_entries_rejects_empty_audio_url():
    raw = make_raw(content={"audio_url": "   ", "transcript": "hi"})
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries([entry], canonical_module_ids=None)
    assert any("audio_url" in e for e in errors)


def test_validate_entries_rejects_invalid_dictation_content_via_schema():
    # transcript is required by DictationContentSchema
    raw = make_raw(content={"audio_url": "/a.mp3"})
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries([entry], canonical_module_ids=None)
    assert any("content invalid" in e or "transcript" in e for e in errors)


def test_validate_entries_rejects_unknown_lesson_type():
    raw = make_raw(lesson_type="not_a_real_type")
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries([entry], canonical_module_ids=None)
    assert any("Unknown lesson type" in e for e in errors)


def test_validate_entries_accepts_writing_prompt_without_audio():
    raw = make_raw(
        external_key="writing:A1:01:journal",
        lesson_type="writing_prompt",
        content={
            "prompt": "Describe your morning routine.",
            "min_words": 25,
            "example_response": "Every morning I wake up...",
            "checklist": ["Used 3 new words", "Past tense", "5+ sentences", "Reread it"],
        },
    )
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries([entry], canonical_module_ids=None)
    assert errors == []


def test_validate_entries_detects_duplicate_external_key():
    a = _entry()
    b = _entry()  # same external_key
    errors = validate_entries([a, b], canonical_module_ids=None)
    assert any("duplicate external_key" in e for e in errors)


def test_validate_entries_detects_duplicate_lesson_number_in_module():
    a = _entry(lesson_number=5, external_key="dictation:A1:01:k1")
    b = _entry(
        lesson_number=5,
        external_key="dictation:A1:01:k2",
        content={
            "audio_url": "/static/audio/dictation_a1_01b.mp3",
            "transcript": "Goodbye!",
        },
    )
    errors = validate_entries([a, b], canonical_module_ids=None)
    assert any("duplicate lesson_number 5" in e for e in errors)


def test_validate_entries_allows_skipping_content_schema():
    raw = make_raw(content={"audio_url": "/a.mp3"})  # missing transcript
    entry, err = parse_entry(raw)
    assert err is None
    errors = validate_entries(
        [entry], canonical_module_ids=None, check_content_schema=False
    )
    # audio_url present, schema check disabled → no errors
    assert errors == []


def test_audio_required_types_includes_dictation():
    assert "dictation" in AUDIO_REQUIRED_TYPES
    assert "writing_prompt" not in AUDIO_REQUIRED_TYPES


# ---------------------------------------------------------------------------
# main() validation path
# ---------------------------------------------------------------------------


def _write_canonical(tmp_path: Path, *triples: tuple[str, int, str]):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    for level, order, slug in triples:
        (canonical / f"module_{level}_{order:02d}_{slug}.json").write_text(
            "{}", encoding="utf-8"
        )
    return canonical


def test_main_validate_only_passes_returns_zero(tmp_path, capsys):
    import import_immersion_lessons as mod

    canonical = _write_canonical(tmp_path, ("A1", 1, "greetings"))
    payload = tmp_path / "good.json"
    payload.write_text(json.dumps([make_raw()]), encoding="utf-8")
    rc = mod.main(
        [
            str(payload),
            "--validate-only",
            "--canonical-modules-dir",
            str(canonical),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "validate-only" in out


def test_main_validate_only_fails_on_missing_audio(tmp_path, capsys):
    import import_immersion_lessons as mod

    canonical = _write_canonical(tmp_path, ("A1", 1, "greetings"))
    bad = make_raw(content={"transcript": "no audio here"})
    payload = tmp_path / "bad.json"
    payload.write_text(json.dumps([bad]), encoding="utf-8")
    rc = mod.main(
        [
            str(payload),
            "--validate-only",
            "--canonical-modules-dir",
            str(canonical),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "audio_url" in err


def test_main_validate_only_fails_on_missing_canonical_module(tmp_path, capsys):
    import import_immersion_lessons as mod

    # canonical dir exists but doesn't include A1#1
    canonical = _write_canonical(tmp_path, ("B2", 9, "advanced"))
    payload = tmp_path / "p.json"
    payload.write_text(json.dumps([make_raw()]), encoding="utf-8")
    rc = mod.main(
        [
            str(payload),
            "--validate-only",
            "--canonical-modules-dir",
            str(canonical),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "canonical source directory" in err


def test_main_no_source_check_skips_canonical_lookup(tmp_path, capsys):
    import import_immersion_lessons as mod

    # canonical dir empty — should fail without --no-source-check
    canonical = tmp_path / "empty_canonical"
    canonical.mkdir()
    payload = tmp_path / "p.json"
    payload.write_text(json.dumps([make_raw()]), encoding="utf-8")
    rc = mod.main(
        [
            str(payload),
            "--validate-only",
            "--canonical-modules-dir",
            str(canonical),
            "--no-source-check",
        ]
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# Content fixture tests (Task 13)
# ---------------------------------------------------------------------------


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "immersion_lessons"
VALID_FIXTURES_DIR = FIXTURES_DIR / "valid"
INVALID_FIXTURES_DIR = FIXTURES_DIR / "invalid"

NEW_LESSON_TYPES = (
    "dictation",
    "audio_fill_blank",
    "translation",
    "sentence_correction",
    "writing_prompt",
    "sentence_completion",
    "collocation_matching",
    "shadow_reading",
    "pronunciation",
    "idiom",
)


def _load_fixture_entries(path: Path) -> list:
    raws = load_lessons(path)
    out = []
    for raw in raws:
        entry, err = parse_entry(raw, source_path=str(path))
        assert err is None, f"{path}: parse_entry failed: {err}"
        out.append(entry)
    return out


def test_fixtures_dir_has_one_valid_fixture_per_new_lesson_type():
    """Every new lesson type must have at least one valid fixture file."""
    found_types = set()
    for fixture in VALID_FIXTURES_DIR.glob("*.json"):
        for entry in _load_fixture_entries(fixture):
            found_types.add(entry.lesson_type)
    missing = set(NEW_LESSON_TYPES) - found_types
    assert not missing, f"missing valid fixtures for: {sorted(missing)}"


@pytest.mark.parametrize("lesson_type", NEW_LESSON_TYPES)
def test_valid_fixture_passes_validation(lesson_type: str):
    """Each valid fixture parses and passes content-schema + audio validation."""
    fixture = VALID_FIXTURES_DIR / f"{lesson_type}.json"
    assert fixture.exists(), f"missing fixture: {fixture}"
    entries = _load_fixture_entries(fixture)
    assert entries, f"empty fixture: {fixture}"
    canonical_ids = {(e.level, e.module_number) for e in entries}
    errors = validate_entries(
        entries,
        canonical_module_ids=canonical_ids,
        check_content_schema=True,
    )
    assert errors == [], f"unexpected errors for {lesson_type}: {errors}"


def test_invalid_fixtures_dir_is_non_empty():
    """Sanity check: at least one invalid fixture per new lesson type exists."""
    invalid_files = list(INVALID_FIXTURES_DIR.glob("*.json"))
    assert invalid_files, "no invalid fixtures found"
    # Each invalid fixture filename starts with the lesson_type it exercises.
    covered = set()
    for path in invalid_files:
        for lt in NEW_LESSON_TYPES:
            if path.name.startswith(lt + "_"):
                covered.add(lt)
    missing = set(NEW_LESSON_TYPES) - covered
    assert not missing, f"no invalid fixture for: {sorted(missing)}"


@pytest.mark.parametrize(
    "invalid_filename",
    sorted(p.name for p in INVALID_FIXTURES_DIR.glob("*.json")),
)
def test_invalid_fixture_is_rejected_by_validation(invalid_filename: str):
    """Every invalid fixture must surface at least one validation error."""
    fixture = INVALID_FIXTURES_DIR / invalid_filename
    entries = _load_fixture_entries(fixture)
    canonical_ids = {(e.level, e.module_number) for e in entries}
    errors = validate_entries(
        entries,
        canonical_module_ids=canonical_ids,
        check_content_schema=True,
    )
    assert errors, f"expected validation errors for {invalid_filename}, got none"


def test_invalid_fixtures_block_db_writes_via_main(tmp_path, capsys):
    """`--validate-only` over an invalid fixture exits with rc=2 and writes nothing."""
    import import_immersion_lessons as mod

    canonical = _write_canonical(tmp_path, ("A1", 1, "greetings"), ("A2", 1, "x"), ("B1", 1, "y"))
    for fixture in INVALID_FIXTURES_DIR.glob("*.json"):
        rc = mod.main(
            [
                str(fixture),
                "--validate-only",
                "--canonical-modules-dir",
                str(canonical),
            ]
        )
        assert rc == 2, f"expected rc=2 for {fixture.name}, got {rc}"
        err = capsys.readouterr().err
        assert "ERROR" in err, f"no error reported for {fixture.name}"


def test_valid_fixtures_can_be_imported_and_rerun_without_duplicates():
    """End-to-end through FakeRepository: import every valid fixture, then re-run.

    On the second run, every entry must hit `noop` and the lesson count must
    stay constant — the importer is fully idempotent.
    """
    all_entries: list = []
    modules: dict = {}
    next_module_id = 1000
    for fixture in sorted(VALID_FIXTURES_DIR.glob("*.json")):
        for entry in _load_fixture_entries(fixture):
            key = (entry.level, entry.module_number)
            if key not in modules:
                modules[key] = next_module_id
                next_module_id += 1
            all_entries.append(entry)

    # Sanity: input is internally consistent.
    canonical_ids = set(modules.keys())
    errors = validate_entries(
        all_entries,
        canonical_module_ids=canonical_ids,
        check_content_schema=True,
    )
    assert errors == [], errors

    repo = FakeRepository.with_modules(modules)
    plan = plan_import(all_entries, repo)
    assert plan.errors == []
    actions = [c.action for c in plan.changes]
    assert actions.count("create") == len(all_entries)

    apply_plan(all_entries, plan, repo)
    first_run_count = len(repo.lessons)
    assert first_run_count == len(all_entries)

    plan2 = plan_import(all_entries, repo)
    assert plan2.errors == []
    assert [c.action for c in plan2.changes] == ["noop"] * len(all_entries)
    apply_plan(all_entries, plan2, repo)
    assert len(repo.lessons) == first_run_count


@pytest.mark.parametrize("lesson_type", NEW_LESSON_TYPES)
def test_valid_fixture_round_trip_per_type(lesson_type: str):
    """Per-type round trip: load fixture, plan create, apply, replay -> noop."""
    fixture = VALID_FIXTURES_DIR / f"{lesson_type}.json"
    entries = _load_fixture_entries(fixture)
    modules = {(e.level, e.module_number): 500 + i for i, e in enumerate(entries)}
    repo = FakeRepository.with_modules(modules)
    plan = plan_import(entries, repo)
    assert plan.errors == []
    assert all(c.action == "create" for c in plan.changes)
    apply_plan(entries, plan, repo)
    assert len(repo.lessons) == len(entries)

    plan2 = plan_import(entries, repo)
    assert all(c.action == "noop" for c in plan2.changes)
    apply_plan(entries, plan2, repo)
    assert len(repo.lessons) == len(entries)


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


# ---------------------------------------------------------------------------
# Staging smoke data set (Task 14)
# ---------------------------------------------------------------------------


STAGING_SMOKE_PATH = (
    Path(__file__).resolve().parents[2]
    / "content"
    / "immersion"
    / "staging_smoke_lessons.json"
)


def _load_staging_smoke_entries() -> list:
    assert STAGING_SMOKE_PATH.exists(), f"missing fixture: {STAGING_SMOKE_PATH}"
    raws = load_lessons(STAGING_SMOKE_PATH)
    out = []
    for raw in raws:
        entry, err = parse_entry(raw, source_path=str(STAGING_SMOKE_PATH))
        assert err is None, f"parse_entry failed for {raw.get('external_key')}: {err}"
        out.append(entry)
    return out


def test_staging_smoke_covers_every_new_lesson_type():
    """Staging smoke set must include exactly one lesson per new type."""
    entries = _load_staging_smoke_entries()
    found_types = [e.lesson_type for e in entries]
    assert sorted(found_types) == sorted(NEW_LESSON_TYPES), (
        f"types mismatch: {sorted(found_types)} vs {sorted(NEW_LESSON_TYPES)}"
    )


def test_staging_smoke_entries_all_marked_staging():
    """Every entry must carry environment=staging so prod imports skip it by default."""
    entries = _load_staging_smoke_entries()
    for entry in entries:
        assert entry.environment == "staging", (
            f"{entry.external_key}: environment must be 'staging', got {entry.environment!r}"
        )


def test_staging_smoke_entries_use_local_static_audio_paths():
    """Audio refs must be small/local — no remote URLs that staging can't fetch."""
    entries = _load_staging_smoke_entries()
    for entry in entries:
        if entry.lesson_type not in AUDIO_REQUIRED_TYPES:
            continue
        audio_url = entry.content.get("audio_url")
        assert isinstance(audio_url, str) and audio_url.startswith("/static/"), (
            f"{entry.external_key}: lesson-level audio_url must start with /static/, got {audio_url!r}"
        )


def test_staging_smoke_entries_pass_content_validation():
    """Every staging entry must pass the same validator the importer runs."""
    entries = _load_staging_smoke_entries()
    canonical_ids = {(e.level, e.module_number) for e in entries}
    errors = validate_entries(
        entries,
        canonical_module_ids=canonical_ids,
        check_content_schema=True,
    )
    assert errors == [], f"validation errors: {errors}"


def test_staging_smoke_skipped_by_default_filter():
    """`filter_entries(skip_staging=True)` must drop every staging fixture."""
    entries = _load_staging_smoke_entries()
    kept, skipped = filter_entries(entries, skip_staging=True)
    assert kept == []
    assert len(skipped) == len(entries)
    assert all(c.action == "skip_environment" for c in skipped)


def test_staging_smoke_included_when_staging_flag_set():
    """`filter_entries(skip_staging=False)` must keep every staging fixture."""
    entries = _load_staging_smoke_entries()
    kept, skipped = filter_entries(entries, skip_staging=False)
    assert kept == entries
    assert skipped == []


def test_staging_smoke_imports_idempotently():
    """Round-trip: import staging set, re-run → every change is noop."""
    entries = _load_staging_smoke_entries()
    unique_module_keys = {(e.level, e.module_number) for e in entries}
    modules = {key: 800 + i for i, key in enumerate(sorted(unique_module_keys))}
    repo = FakeRepository.with_modules(modules)
    plan = plan_import(entries, repo)
    assert plan.errors == []
    assert all(c.action == "create" for c in plan.changes)
    apply_plan(entries, plan, repo)
    assert len(repo.lessons) == len(entries)

    plan2 = plan_import(entries, repo)
    assert plan2.errors == []
    assert [c.action for c in plan2.changes] == ["noop"] * len(entries)
    apply_plan(entries, plan2, repo)
    assert len(repo.lessons) == len(entries)


def test_staging_smoke_external_keys_are_unique_and_staging_namespaced():
    """Stable external_keys must be unique and clearly marked as staging."""
    entries = _load_staging_smoke_entries()
    keys = [e.external_key for e in entries]
    assert len(keys) == len(set(keys)), "duplicate external_key in staging smoke set"
    for key in keys:
        assert key.startswith("staging:"), (
            f"staging external_key must start with 'staging:', got {key!r}"
        )
