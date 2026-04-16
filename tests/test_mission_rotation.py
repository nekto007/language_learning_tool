"""Tests for mission type rotation — no same type two days in a row."""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent
from app.daily_plan.models import MissionType, SourceKind
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, RepairBreakdown
from app.daily_plan.mission_selector import (
    get_last_mission_type,
    save_mission_type,
    select_mission,
    _find_rotation_alternative,
)

MODULE = "app.daily_plan.mission_selector"


def _low_pressure() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=0, overdue_srs_score=0.0,
        grammar_weak_count=0, grammar_weak_score=0.0,
        failure_cluster_count=0, failure_cluster_score=0.0,
        total_score=0.0,
    )


def _high_pressure() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=50, overdue_srs_score=1.0,
        grammar_weak_count=10, grammar_weak_score=1.0,
        failure_cluster_count=15, failure_cluster_score=1.0,
        total_score=1.0,
    )


# ── save / load round-trip ──

class TestSaveAndGetMissionType:
    def test_save_and_retrieve(self, db_session, test_user):
        today = date(2026, 4, 17)
        save_mission_type(test_user.id, MissionType.progress, today)
        db_session.flush()

        result = get_last_mission_type(test_user.id, before_date=today + timedelta(days=1))
        assert result == MissionType.progress

    def test_returns_none_when_no_history(self, db_session, test_user):
        result = get_last_mission_type(test_user.id, before_date=date(2026, 4, 17))
        assert result is None

    def test_returns_most_recent(self, db_session, test_user):
        save_mission_type(test_user.id, MissionType.progress, date(2026, 4, 15))
        save_mission_type(test_user.id, MissionType.reading, date(2026, 4, 16))
        db_session.flush()

        result = get_last_mission_type(test_user.id, before_date=date(2026, 4, 17))
        assert result == MissionType.reading

    def test_excludes_future_dates(self, db_session, test_user):
        save_mission_type(test_user.id, MissionType.reading, date(2026, 4, 18))
        db_session.flush()

        result = get_last_mission_type(test_user.id, before_date=date(2026, 4, 17))
        assert result is None

    def test_upsert_on_same_date(self, db_session, test_user):
        today = date(2026, 4, 17)
        save_mission_type(test_user.id, MissionType.progress, today)
        db_session.flush()
        save_mission_type(test_user.id, MissionType.reading, today)
        db_session.flush()

        result = get_last_mission_type(test_user.id, before_date=today + timedelta(days=1))
        assert result == MissionType.reading

        count = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='mission_selected', event_date=today,
        ).count()
        assert count == 1

    def test_handles_invalid_stored_value(self, db_session, test_user):
        today = date(2026, 4, 17)
        db_session.add(StreakEvent(
            user_id=test_user.id, event_type='mission_selected',
            coins_delta=0, event_date=today,
            details={'mission_type': 'nonexistent_type'},
        ))
        db_session.flush()

        result = get_last_mission_type(test_user.id, before_date=today + timedelta(days=1))
        assert result is None


# ── rotation alternative logic ──

class TestFindRotationAlternative:
    @patch(f"{MODULE}._has_book_reading", return_value=True)
    def test_progress_can_swap_to_reading(self, _mock):
        result = _find_rotation_alternative(1, MissionType.progress)
        assert result == MissionType.reading

    @patch(f"{MODULE}._has_book_reading", return_value=False)
    def test_progress_no_swap_without_books(self, _mock):
        result = _find_rotation_alternative(1, MissionType.progress)
        assert result is None

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    def test_reading_can_swap_to_progress(self, _mock):
        result = _find_rotation_alternative(1, MissionType.reading)
        assert result == MissionType.progress

    @patch(f"{MODULE}.detect_primary_track", return_value=None)
    def test_reading_no_swap_without_course(self, _mock):
        result = _find_rotation_alternative(1, MissionType.reading)
        assert result is None

    def test_repair_returns_none(self):
        result = _find_rotation_alternative(1, MissionType.repair)
        assert result is None


# ── select_mission with rotation ──

class TestSelectMissionRotation:
    @patch(f"{MODULE}._find_rotation_alternative", return_value=MissionType.reading)
    @patch(f"{MODULE}.get_last_mission_type", return_value=MissionType.progress)
    @patch(f"{MODULE}._pick_non_repair_mission")
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_swaps_when_yesterday_same(self, mock_pressure, mock_pick, mock_last, mock_alt):
        mock_pressure.return_value = _low_pressure()
        mock_pick.return_value = (MissionType.progress, "primary_track_progress", "text", None)

        mission_type, reason_code, _, _ = select_mission(1, tz="UTC")

        assert mission_type == MissionType.reading
        assert reason_code == "rotation_reading"

    @patch(f"{MODULE}.get_last_mission_type", return_value=MissionType.reading)
    @patch(f"{MODULE}._pick_non_repair_mission")
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_no_swap_when_yesterday_different(self, mock_pressure, mock_pick, mock_last):
        mock_pressure.return_value = _low_pressure()
        mock_pick.return_value = (MissionType.progress, "primary_track_progress", "text", None)

        mission_type, reason_code, _, _ = select_mission(1, tz="UTC")

        assert mission_type == MissionType.progress
        assert reason_code == "primary_track_progress"

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._pick_non_repair_mission")
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_no_swap_when_no_history(self, mock_pressure, mock_pick, mock_last):
        mock_pressure.return_value = _low_pressure()
        mock_pick.return_value = (MissionType.progress, "primary_track_progress", "text", None)

        mission_type, _, _, _ = select_mission(1, tz="UTC")

        assert mission_type == MissionType.progress

    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_repair_still_wins_over_rotation(self, mock_pressure):
        """Repair always takes priority regardless of yesterday's type."""
        mock_pressure.return_value = _high_pressure()

        mission_type, _, _, breakdown = select_mission(1, tz="UTC")

        assert mission_type == MissionType.repair
        assert breakdown is not None

    @patch(f"{MODULE}._find_rotation_alternative", return_value=None)
    @patch(f"{MODULE}.get_last_mission_type", return_value=MissionType.progress)
    @patch(f"{MODULE}._pick_non_repair_mission")
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_keeps_type_when_no_alternative(self, mock_pressure, mock_pick, mock_last, mock_alt):
        mock_pressure.return_value = _low_pressure()
        mock_pick.return_value = (MissionType.progress, "primary_track_progress", "text", None)

        mission_type, reason_code, _, _ = select_mission(1, tz="UTC")

        assert mission_type == MissionType.progress
        assert reason_code == "primary_track_progress"

    @patch(f"{MODULE}.get_last_mission_type", side_effect=Exception("DB error"))
    @patch(f"{MODULE}._pick_non_repair_mission")
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_graceful_fallback_on_error(self, mock_pressure, mock_pick, mock_last):
        """Rotation errors should not break mission selection."""
        mock_pressure.return_value = _low_pressure()
        mock_pick.return_value = (MissionType.progress, "primary_track_progress", "text", None)

        mission_type, _, _, _ = select_mission(1, tz="UTC")

        assert mission_type == MissionType.progress
