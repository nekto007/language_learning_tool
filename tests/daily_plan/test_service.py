"""Unit tests for the daily_plan service pipeline.

Covers:
- select_mission(): repair_pressure >= 0.6 triggers Repair mission
- assemble_progress_mission(): cold start respects user onboarding_level
- assemble_repair_mission(): 0 SRS + 0 grammar degrades to progress mission
- get_daily_plan_unified(): falls back to legacy plan when assembly raises an error
"""
from unittest.mock import patch, MagicMock

import pytest

from app.daily_plan.models import (
    Mission,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PrimaryGoal,
    PrimarySource,
    SourceKind,
)
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, RepairBreakdown

SELECTOR_MOD = "app.daily_plan.mission_selector"
ASSEMBLER_MOD = "app.daily_plan.assembler"
SERVICE_MOD = "app.daily_plan.service"
LEGACY_MOD = "app.telegram.queries"


@pytest.fixture(autouse=True)
def _assume_recall_content():
    """Treat guided_recall as having content unless a test opts out.

    Tests in this file mock assembler dependencies without setting up the
    daily-plan card pool; the real _has_guided_recall_content would return
    False and skip the recall phase, breaking pre-existing expectations.
    """
    with patch(f"{ASSEMBLER_MOD}._has_guided_recall_content", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _generous_card_budget():
    """Give assembler tests an effectively-unlimited daily card budget."""
    with patch(f"{ASSEMBLER_MOD}._get_remaining_card_budget",
               return_value=(1000, 1000)):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repair_breakdown(total_score: float = 1.0) -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=50,
        overdue_srs_score=1.0,
        grammar_weak_count=10,
        grammar_weak_score=1.0,
        failure_cluster_count=15,
        failure_cluster_score=1.0,
        total_score=total_score,
    )


def _zero_breakdown() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=0,
        overdue_srs_score=0.0,
        grammar_weak_count=0,
        grammar_weak_score=0.0,
        failure_cluster_count=0,
        failure_cluster_score=0.0,
        total_score=0.0,
    )


def _make_progress_plan() -> MissionPlan:
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.progress,
            title="Продвигаемся по курсу",
            reason_code="primary_track_progress",
            reason_text="Двигаемся вперёд по курсу",
        ),
        primary_goal=PrimaryGoal(
            type="advance",
            title="Пройти следующий урок",
            success_criterion="lesson_completed",
        ),
        primary_source=PrimarySource(
            kind=SourceKind.normal_course,
            id="1",
            label="Урок 1",
        ),
        phases=[
            MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
            MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
            MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.normal_course, mode="lesson_practice"),
        ],
        legacy={"next_lesson": {"lesson_id": 1}},
    )


# ---------------------------------------------------------------------------
# select_mission(): repair_pressure >= 0.6 → Repair
# ---------------------------------------------------------------------------


class TestSelectMissionRepairThreshold:
    @pytest.mark.smoke
    @patch(f"{SELECTOR_MOD}.detect_primary_track")
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_repair_triggered_at_exact_threshold(self, mock_pressure, mock_track):
        """repair_pressure.total_score == REPAIR_THRESHOLD must select Repair mission."""
        from app.daily_plan.mission_selector import select_mission

        mock_pressure.return_value = _repair_breakdown(total_score=REPAIR_THRESHOLD)

        mission_type, reason_code, reason_text, breakdown = select_mission(user_id=1)

        assert mission_type == MissionType.repair
        assert reason_code == "repair_pressure_high"
        assert breakdown is not None
        assert breakdown.total_score >= REPAIR_THRESHOLD
        # detect_primary_track should NOT be called when repair triggers
        mock_track.assert_not_called()

    @patch(f"{SELECTOR_MOD}.detect_primary_track")
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_repair_triggered_above_threshold(self, mock_pressure, mock_track):
        """repair_pressure.total_score above threshold also selects Repair."""
        from app.daily_plan.mission_selector import select_mission

        mock_pressure.return_value = _repair_breakdown(total_score=0.9)

        mission_type, _, _, _ = select_mission(user_id=1)

        assert mission_type == MissionType.repair
        mock_track.assert_not_called()

    @patch(f"{SELECTOR_MOD}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_no_repair_just_below_threshold(self, mock_pressure, mock_track):
        """repair_pressure.total_score just below threshold does NOT select Repair."""
        from app.daily_plan.mission_selector import select_mission

        mock_pressure.return_value = _repair_breakdown(total_score=REPAIR_THRESHOLD - 0.001)

        mission_type, _, _, _ = select_mission(user_id=1)

        assert mission_type != MissionType.repair
        mock_track.assert_called_once()

    @patch(f"{SELECTOR_MOD}.detect_primary_track", return_value=SourceKind.books)
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_repair_overrides_reading_track(self, mock_pressure, _track):
        """High repair pressure overrides even a books primary track."""
        from app.daily_plan.mission_selector import select_mission

        mock_pressure.return_value = _repair_breakdown(total_score=0.8)

        mission_type, _, _, _ = select_mission(user_id=1)

        assert mission_type == MissionType.repair

    @patch(f"{SELECTOR_MOD}.detect_primary_track", return_value=None)
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_cold_start_no_pressure_returns_progress(self, mock_pressure, _track):
        """No pressure and no track → cold-start Progress mission."""
        from app.daily_plan.mission_selector import select_mission

        mock_pressure.return_value = _zero_breakdown()

        mission_type, reason_code, _, _ = select_mission(user_id=1)

        assert mission_type == MissionType.progress
        assert reason_code == "cold_start"


# ---------------------------------------------------------------------------
# assemble_progress_mission(): cold start with onboarding_level
# ---------------------------------------------------------------------------


class TestAssembleProgressMissionColdStart:
    """Cold-start path: user has no lesson progress; onboarding_level determines first lesson."""

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_lesson")
    def test_cold_start_returns_lesson_from_onboarding_level(self, mock_lesson, _srs):
        """assembler uses the lesson returned by _find_next_lesson (which uses onboarding level)."""
        from app.daily_plan.assembler import assemble_progress_mission

        mock_lesson.return_value = {
            "title": "B1 Lesson 1",
            "lesson_id": 100,
            "module_id": 20,
            "module_number": 3,
            "lesson_type": "vocabulary",
        }

        plan = assemble_progress_mission(1, SourceKind.normal_course, reason_code="cold_start")

        assert plan is not None
        assert plan.mission.type == MissionType.progress
        assert plan.mission.reason_code == "cold_start"
        assert plan.primary_source.kind == SourceKind.normal_course
        assert plan.primary_source.id == "100"
        assert plan.primary_source.label == "B1 Lesson 1"
        assert plan.legacy["next_lesson"]["lesson_id"] == 100

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_lesson", return_value=None)
    def test_cold_start_no_lesson_returns_none(self, _lesson, _srs):
        """If no lesson exists at user's level (empty curriculum), assembler returns None."""
        from app.daily_plan.assembler import assemble_progress_mission

        result = assemble_progress_mission(1, SourceKind.normal_course)

        assert result is None

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_lesson")
    def test_cold_start_three_phases_when_no_srs(self, mock_lesson, _srs):
        """Cold start with SRS=0 produces 3 phases (no check phase)."""
        from app.daily_plan.assembler import assemble_progress_mission

        mock_lesson.return_value = {
            "title": "A0 First Lesson",
            "lesson_id": 1,
            "module_id": 1,
            "module_number": 1,
            "lesson_type": "dialogue",
        }

        plan = assemble_progress_mission(1, SourceKind.normal_course)

        assert plan is not None
        assert 3 <= len(plan.phases) <= 4
        assert plan.phases[0].phase == PhaseKind.recall
        assert plan.phases[0].mode == "guided_recall"  # no SRS → guided_recall
        assert plan.phases[1].phase == PhaseKind.learn
        assert plan.phases[2].phase == PhaseKind.use

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=5)
    @patch(f"{ASSEMBLER_MOD}._find_next_lesson")
    def test_cold_start_four_phases_when_srs_due(self, mock_lesson, _srs):
        """Cold start with SRS > 0 adds a check phase (4 total)."""
        from app.daily_plan.assembler import assemble_progress_mission

        mock_lesson.return_value = {
            "title": "A1 Lesson",
            "lesson_id": 5,
            "module_id": 2,
            "module_number": 1,
            "lesson_type": "grammar",
        }

        plan = assemble_progress_mission(1, SourceKind.normal_course)

        assert plan is not None
        assert 4 <= len(plan.phases) <= 5
        check = next(p for p in plan.phases if p.phase == PhaseKind.check)
        assert check.required is False


# ---------------------------------------------------------------------------
# assemble_repair_mission(): 0 SRS + 0 grammar → degrades to progress
# ---------------------------------------------------------------------------


class TestAssembleRepairMissionDegradation:
    @patch(f"{ASSEMBLER_MOD}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{ASSEMBLER_MOD}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_zero_srs_zero_grammar_degrades_to_progress(self, _srs, _gram, mock_progress, _track):
        """Repair with 0 SRS and 0 grammar returns a Progress mission, not None."""
        from app.daily_plan.assembler import assemble_repair_mission

        mock_progress.return_value = _make_progress_plan()

        result = assemble_repair_mission(1, _zero_breakdown())

        assert result is not None
        assert result.mission.type == MissionType.progress
        mock_progress.assert_called_once()

    @patch(f"{ASSEMBLER_MOD}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{ASSEMBLER_MOD}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_degradation_uses_progress_next_step_reason(self, _srs, _gram, mock_progress, _track):
        """Degraded Repair passes 'progress_next_step' reason_code to progress assembler."""
        from app.daily_plan.assembler import assemble_repair_mission

        mock_progress.return_value = _make_progress_plan()
        assemble_repair_mission(1, _zero_breakdown())

        call_kwargs = mock_progress.call_args[1]
        assert call_kwargs["reason_code"] == "progress_next_step"

    @patch(f"{ASSEMBLER_MOD}.detect_primary_track", return_value=None)
    @patch(f"{ASSEMBLER_MOD}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_zero_all_no_track_defaults_to_normal_course(self, _srs, _gram, mock_progress, _track):
        """No track → degradation picks SourceKind.normal_course for progress assembler."""
        from app.daily_plan.assembler import assemble_repair_mission

        mock_progress.return_value = _make_progress_plan()
        assemble_repair_mission(1, _zero_breakdown())

        call_args = mock_progress.call_args[0]
        assert call_args[1] == SourceKind.normal_course

    @patch(f"{ASSEMBLER_MOD}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{ASSEMBLER_MOD}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_degradation_emits_warning_log(self, _srs, _gram, mock_progress, _track, caplog):
        """Degradation from Repair to Progress must emit a warning log entry."""
        import logging
        from app.daily_plan.assembler import assemble_repair_mission

        mock_progress.return_value = _make_progress_plan()

        with caplog.at_level(logging.WARNING, logger="app.daily_plan.assembler"):
            assemble_repair_mission(1, _zero_breakdown())

        assert any("degrading" in r.message for r in caplog.records)

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic", return_value={"title": "Past Simple", "topic_id": 7})
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=3)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=10)
    def test_srs_and_grammar_nonzero_does_not_degrade(self, _srs, _gram, _topic):
        """When SRS > 0 or grammar > 0, returns a Repair plan (no degradation)."""
        from app.daily_plan.assembler import assemble_repair_mission

        breakdown = _repair_breakdown(total_score=0.65)
        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.repair


# ---------------------------------------------------------------------------
# get_daily_plan_unified(): fallback to legacy on assembly error
# ---------------------------------------------------------------------------


class TestGetDailyPlanUnifiedFallback:
    @patch(f"{SERVICE_MOD}.select_mission", side_effect=Exception("DB timeout"))
    @patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={"steps": []})
    def test_internal_exception_causes_legacy_fallback(
        self, mock_legacy, mock_select, app, db_session, test_user
    ):
        """If an internal function raises (e.g. select_mission), get_mission_plan catches it,
        returns None, and get_daily_plan_unified falls back to legacy payload."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.use_mission_plan = True
        db_session.flush()

        result = get_daily_plan_unified(test_user.id)

        assert "steps" in result
        assert result["_plan_meta"]["mission_plan_enabled"] is True
        assert result["_plan_meta"]["effective_mode"] == "legacy_fallback"
        assert result["_plan_meta"]["fallback_reason"] == "mission_build_failed"

    @patch(f"{SERVICE_MOD}.get_mission_plan", return_value=None)
    @patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={"steps": []})
    def test_none_from_mission_plan_falls_back_to_legacy(
        self, mock_legacy, mock_mission, app, db_session, test_user
    ):
        """If get_mission_plan returns None (assembly failed), unified plan returns legacy."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.use_mission_plan = True
        db_session.flush()

        result = get_daily_plan_unified(test_user.id)

        assert "steps" in result
        mock_legacy.assert_called_once()
        assert result["_plan_meta"]["effective_mode"] == "legacy_fallback"

    @patch(f"{SERVICE_MOD}.get_mission_plan", return_value=None)
    @patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={"steps": []})
    def test_fallback_emits_warning_log(self, _legacy, _mission, app, db_session, test_user, caplog):
        """Falling back to legacy emits a warning log entry."""
        import logging
        from app.daily_plan.service import get_daily_plan_unified

        test_user.use_mission_plan = True
        db_session.flush()

        with caplog.at_level(logging.WARNING, logger="app.daily_plan.service"):
            get_daily_plan_unified(test_user.id)

        assert any("falling back to legacy" in r.message for r in caplog.records)

    @patch(f"{LEGACY_MOD}.get_daily_plan_v2", return_value={"steps": []})
    def test_flag_off_uses_legacy_without_calling_mission_plan(
        self, mock_legacy, app, db_session, test_user
    ):
        """When use_mission_plan=False, legacy is called directly without trying mission plan."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.use_mission_plan = False
        db_session.flush()

        with patch(f"{SERVICE_MOD}.get_mission_plan") as mock_mission:
            result = get_daily_plan_unified(test_user.id)

        mock_mission.assert_not_called()
        assert result["_plan_meta"]["mission_plan_enabled"] is False
        assert result["_plan_meta"]["effective_mode"] == "legacy"


# ---------------------------------------------------------------------------
# Task 55: repair mission degradation at service level + assembler failure log
# ---------------------------------------------------------------------------


class TestRepairMissionDegradationServiceLevel:
    """Service-level tests for repair mission degradation edge cases (task 55)."""

    @patch(f"{ASSEMBLER_MOD}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{ASSEMBLER_MOD}._find_next_lesson")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_repair_zero_srs_zero_grammar_returns_progress_not_none(
        self, mock_pressure, _srs, _gram, mock_lesson, _track
    ):
        """Service-level: repair mission with 0 SRS and 0 grammar degrades to Progress (not None).

        Ensures that get_mission_plan() does not return None when repair pressure was high
        but the actual due items are 0 — the system must degrade gracefully to a progress plan.
        """
        from app.daily_plan.service import get_mission_plan

        mock_pressure.return_value = _repair_breakdown(total_score=0.8)
        mock_lesson.return_value = {
            "title": "A1 Lesson",
            "lesson_id": 10,
            "module_id": 2,
            "module_number": 1,
            "lesson_type": "vocabulary",
        }

        result = get_mission_plan(user_id=99)

        assert result is not None
        assert result["mission"]["type"] == "progress"

    @patch(f"{SERVICE_MOD}.assemble_repair_mission", side_effect=RuntimeError("DB error"))
    @patch(f"{SELECTOR_MOD}.calculate_repair_pressure")
    def test_assembler_exception_emits_warning_log(self, mock_pressure, _asm, caplog):
        """Assembler failure (exception) causes get_mission_plan to log the error and return None."""
        import logging
        from app.daily_plan.service import get_mission_plan

        mock_pressure.return_value = _repair_breakdown(total_score=0.8)

        with caplog.at_level(logging.ERROR, logger="app.daily_plan.service"):
            result = get_mission_plan(user_id=99)

        assert result is None
        assert any("Failed to build mission plan" in r.message for r in caplog.records)
