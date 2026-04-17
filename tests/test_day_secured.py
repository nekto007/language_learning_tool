"""Tests for Task 6: day_secured state in daily plan."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.daily_plan.models import (
    DailyPlanLog,
    Mission,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PrimaryGoal,
    PrimarySource,
    SourceKind,
)
from app.daily_plan.service import (
    _mission_plan_to_dict,
    compute_day_secured,
    write_secured_at,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _phase(mode: str, *, required: bool = True, completed: bool = False) -> dict:
    return {
        'id': mode,
        'phase': 'recall',
        'title': mode,
        'source_kind': 'srs',
        'mode': mode,
        'required': required,
        'completed': completed,
        'preview': None,
    }


def _make_plan(phases_cfg: list[tuple[bool, bool]]) -> MissionPlan:
    """Build a MissionPlan. phases_cfg is list of (required, completed) tuples."""
    phase_kinds = [PhaseKind.recall, PhaseKind.learn, PhaseKind.use, PhaseKind.read, PhaseKind.close]
    modes = ['srs_review', 'curriculum_lesson', 'lesson_practice', 'book_reading', 'success_marker']
    phases = []
    for i, (required, completed) in enumerate(phases_cfg):
        p = MissionPhase(
            phase=phase_kinds[i % len(phase_kinds)],
            title=f"Phase {i}",
            source_kind=SourceKind.srs,
            mode=modes[i % len(modes)],
            required=required,
            completed=completed,
        )
        phases.append(p)
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.progress,
            title="Test",
            reason_code="rc",
            reason_text="rt",
        ),
        primary_goal=PrimaryGoal(type="advance", title="Goal", success_criterion="done"),
        primary_source=PrimarySource(kind=SourceKind.normal_course, id="1", label="L1"),
        phases=phases,
    )


# ---------------------------------------------------------------------------
# compute_day_secured unit tests
# ---------------------------------------------------------------------------

class TestComputeDaySecured:
    def test_all_required_complete_returns_true(self):
        phases = [
            _phase('srs_review', required=True, completed=True),
            _phase('curriculum_lesson', required=True, completed=True),
        ]
        assert compute_day_secured(phases) is True

    def test_one_required_incomplete_returns_false(self):
        phases = [
            _phase('srs_review', required=True, completed=True),
            _phase('curriculum_lesson', required=True, completed=False),
        ]
        assert compute_day_secured(phases) is False

    def test_all_optional_complete_returns_false(self):
        # required=False phases do not count for day_secured
        phases = [
            _phase('srs_review', required=False, completed=True),
        ]
        assert compute_day_secured(phases) is False

    def test_empty_phases_returns_false(self):
        assert compute_day_secured([]) is False

    def test_optional_incomplete_does_not_block_secured(self):
        # required=True done, optional not done → still secured
        phases = [
            _phase('srs_review', required=True, completed=True),
            _phase('success_marker', required=False, completed=False),
        ]
        assert compute_day_secured(phases) is True

    def test_partial_completion_returns_false(self):
        phases = [
            _phase('srs_review', required=True, completed=True),
            _phase('curriculum_lesson', required=True, completed=False),
            _phase('lesson_practice', required=True, completed=True),
        ]
        assert compute_day_secured(phases) is False

    def test_single_required_complete_returns_true(self):
        phases = [_phase('srs_review', required=True, completed=True)]
        assert compute_day_secured(phases) is True


# ---------------------------------------------------------------------------
# MissionPlan → dict includes day_secured
# ---------------------------------------------------------------------------

class TestMissionPlanToDictDaySecured:
    def test_day_secured_false_when_no_phases_complete(self):
        plan = _make_plan([(True, False), (True, False), (True, False)])
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is False

    def test_day_secured_true_when_all_required_complete(self):
        plan = _make_plan([(True, True), (True, True), (True, True)])
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is True

    def test_day_secured_false_with_incomplete_required(self):
        # 2 of 3 required done → not secured
        plan = _make_plan([(True, True), (True, False), (True, True)])
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is False

    def test_day_secured_true_optional_not_done(self):
        # required done, optional not done → secured
        plan = _make_plan([(True, True), (True, True), (False, False)])
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is True

    def test_day_secured_present_for_repair_mission(self):
        plan = MissionPlan(
            plan_version="1",
            mission=Mission(
                type=MissionType.repair,
                title="Repair",
                reason_code="repair_pressure_high",
                reason_text="Fix it",
            ),
            primary_goal=PrimaryGoal(type="repair", title="Repair", success_criterion="done"),
            primary_source=PrimarySource(kind=SourceKind.srs, id=None, label="SRS"),
            phases=[
                MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review", completed=True),
                MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.grammar_lab, mode="grammar_practice", completed=True),
                MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.grammar_lab, mode="targeted_quiz", completed=True),
            ],
        )
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is True

    def test_day_secured_present_for_reading_mission(self):
        plan = MissionPlan(
            plan_version="1",
            mission=Mission(
                type=MissionType.reading,
                title="Reading",
                reason_code="primary_track_reading",
                reason_text="Read",
            ),
            primary_goal=PrimaryGoal(type="read", title="Read", success_criterion="done"),
            primary_source=PrimarySource(kind=SourceKind.books, id="5", label="Book"),
            phases=[
                MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.vocab, mode="book_vocab_recall", completed=False),
                MissionPhase(phase=PhaseKind.read, title="Read", source_kind=SourceKind.books, mode="book_reading", completed=False),
                MissionPhase(phase=PhaseKind.use, title="Use", source_kind=SourceKind.vocab, mode="reading_vocab_extract", completed=False),
            ],
        )
        d = _mission_plan_to_dict(plan)
        assert d['day_secured'] is False


# ---------------------------------------------------------------------------
# Edge cases from day-secured definition (Task 2)
# ---------------------------------------------------------------------------

class TestDaySecuredEdgeCases:
    def test_edge_case_9_bonus_phase_completed_but_required_not(self):
        # Bonus (required=False) done, but required phases not → not secured
        phases = [
            _phase('srs_review', required=True, completed=False),
            _phase('success_marker', required=False, completed=True),
        ]
        assert compute_day_secured(phases) is False

    def test_edge_case_8_partial_phase_not_counted(self):
        # All required phases must be completed (completed=False means not done)
        phases = [
            _phase('srs_review', required=True, completed=True),
            _phase('curriculum_lesson', required=True, completed=False),
        ]
        assert compute_day_secured(phases) is False

    def test_all_required_false_phases_returns_false(self):
        # If all phases are optional, day can never be secured (no required phases)
        phases = [
            _phase('srs_review', required=False, completed=True),
            _phase('curriculum_lesson', required=False, completed=True),
        ]
        assert compute_day_secured(phases) is False


# ---------------------------------------------------------------------------
# write_secured_at DB tests
# ---------------------------------------------------------------------------

class TestWriteSecuredAt:
    def test_creates_log_row_and_sets_secured_at(self, app, db_session, test_user):
        today = date.today()
        with app.app_context():
            write_secured_at(test_user.id, today, mission_type='progress')
            log = db_session.query(DailyPlanLog).filter_by(
                user_id=test_user.id, plan_date=today
            ).first()
            assert log is not None
            assert log.secured_at is not None
            assert log.mission_type == 'progress'

    def test_idempotent_second_call_does_not_overwrite_secured_at(self, app, db_session, test_user):
        today = date.today()
        with app.app_context():
            write_secured_at(test_user.id, today)
            log = db_session.query(DailyPlanLog).filter_by(
                user_id=test_user.id, plan_date=today
            ).first()
            first_ts = log.secured_at

            write_secured_at(test_user.id, today)
            log2 = db_session.query(DailyPlanLog).filter_by(
                user_id=test_user.id, plan_date=today
            ).first()
            # second call must not overwrite
            assert log2.secured_at == first_ts

    def test_different_dates_create_separate_rows(self, app, db_session, test_user):
        from datetime import timedelta
        today = date.today()
        yesterday = today - timedelta(days=1)
        with app.app_context():
            write_secured_at(test_user.id, today)
            write_secured_at(test_user.id, yesterday)
            count = db_session.query(DailyPlanLog).filter_by(
                user_id=test_user.id
            ).count()
            assert count == 2
