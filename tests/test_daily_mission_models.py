import pytest

from app.daily_plan.models import (
    MissionType,
    PhaseKind,
    SourceKind,
    MissionPhase,
    Mission,
    PrimaryGoal,
    PrimarySource,
    MissionPlan,
)


def _make_phase(phase: PhaseKind = PhaseKind.recall, **kwargs) -> MissionPhase:
    defaults = dict(
        phase=phase,
        title="Test phase",
        source_kind=SourceKind.normal_course,
        mode="default",
    )
    defaults.update(kwargs)
    return MissionPhase(**defaults)


def _make_mission(**kwargs) -> Mission:
    defaults = dict(
        type=MissionType.progress,
        title="Continue your course",
        reason_code="primary_track",
        reason_text="Your main course awaits",
    )
    defaults.update(kwargs)
    return Mission(**defaults)


def _make_goal(**kwargs) -> PrimaryGoal:
    defaults = dict(
        type="lesson_completion",
        title="Complete today's lesson",
        success_criterion="Finish lesson 5",
    )
    defaults.update(kwargs)
    return PrimaryGoal(**defaults)


def _make_source(**kwargs) -> PrimarySource:
    defaults = dict(
        kind=SourceKind.normal_course,
        id="course-1",
        label="English A2",
    )
    defaults.update(kwargs)
    return PrimarySource(**defaults)


def _make_plan(num_phases: int = 3, **kwargs) -> MissionPlan:
    phases = [
        _make_phase(PhaseKind.recall, title="Recall"),
        _make_phase(PhaseKind.learn, title="Learn"),
        _make_phase(PhaseKind.use, title="Use"),
    ]
    if num_phases == 4:
        phases.append(_make_phase(PhaseKind.check, title="Check"))
    defaults = dict(
        plan_version="1",
        mission=_make_mission(),
        primary_goal=_make_goal(),
        primary_source=_make_source(),
        phases=phases[:num_phases] if num_phases <= 3 else phases,
    )
    defaults.update(kwargs)
    return MissionPlan(**defaults)


class TestEnums:
    def test_mission_type_values(self):
        assert set(m.value for m in MissionType) == {"progress", "repair", "reading"}

    def test_phase_kind_values(self):
        assert set(p.value for p in PhaseKind) == {
            "recall", "learn", "use", "read", "check", "close",
        }

    def test_source_kind_values(self):
        assert set(s.value for s in SourceKind) == {
            "normal_course", "book_course", "books", "srs", "grammar_lab", "vocab",
        }


class TestMissionPhase:
    def test_defaults(self):
        p = _make_phase()
        assert p.required is True
        assert p.completed is False
        assert len(p.id) == 8

    def test_unique_ids(self):
        a, b = _make_phase(), _make_phase()
        assert a.id != b.id

    def test_custom_values(self):
        p = _make_phase(
            phase=PhaseKind.read,
            title="Read chapter",
            source_kind=SourceKind.books,
            mode="reading",
            required=False,
            completed=True,
            id="custom01",
        )
        assert p.phase == PhaseKind.read
        assert p.source_kind == SourceKind.books
        assert p.id == "custom01"
        assert p.required is False
        assert p.completed is True


class TestMission:
    def test_creation(self):
        m = _make_mission()
        assert m.type == MissionType.progress
        assert m.reason_code == "primary_track"

    def test_all_types(self):
        for mt in MissionType:
            m = _make_mission(type=mt)
            assert m.type == mt


class TestPrimaryGoal:
    def test_creation(self):
        g = _make_goal()
        assert g.type == "lesson_completion"
        assert g.success_criterion == "Finish lesson 5"


class TestPrimarySource:
    def test_creation(self):
        s = _make_source()
        assert s.kind == SourceKind.normal_course
        assert s.id == "course-1"

    def test_nullable_id(self):
        s = _make_source(id=None)
        assert s.id is None


class TestMissionPlan:
    def test_valid_3_phases(self):
        plan = _make_plan(3)
        assert len(plan.phases) == 3

    def test_valid_4_phases(self):
        plan = _make_plan(4)
        assert len(plan.phases) == 4

    def test_empty_phases_rejected(self):
        with pytest.raises(ValueError, match="3-4 phases"):
            _make_plan(phases=[])

    def test_1_phase_rejected(self):
        with pytest.raises(ValueError, match="3-4 phases"):
            _make_plan(phases=[_make_phase()])

    def test_2_phases_rejected(self):
        with pytest.raises(ValueError, match="3-4 phases"):
            _make_plan(phases=[_make_phase(), _make_phase()])

    def test_5_phases_rejected(self):
        with pytest.raises(ValueError, match="3-4 phases"):
            _make_plan(phases=[_make_phase() for _ in range(5)])

    def test_legacy_default_none(self):
        plan = _make_plan()
        assert plan.legacy is None

    def test_legacy_dict(self):
        plan = _make_plan(legacy={"next_lesson": 5, "words_due": 12})
        assert plan.legacy["next_lesson"] == 5

    def test_completion_default_none(self):
        plan = _make_plan()
        assert plan.completion is None

    def test_plan_version(self):
        plan = _make_plan()
        assert plan.plan_version == "1"

    def test_single_mission(self):
        plan = _make_plan()
        assert isinstance(plan.mission, Mission)
        assert plan.mission.type == MissionType.progress

    def test_single_goal(self):
        plan = _make_plan()
        assert isinstance(plan.primary_goal, PrimaryGoal)

    def test_single_source(self):
        plan = _make_plan()
        assert isinstance(plan.primary_source, PrimarySource)
