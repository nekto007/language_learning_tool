from unittest.mock import patch

import pytest

from app.daily_plan.models import MissionType, SourceKind
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, RepairBreakdown
from app.daily_plan.mission_selector import (
    detect_primary_track,
    select_mission,
)

MODULE = "app.daily_plan.mission_selector"


def _low_pressure() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=0,
        overdue_srs_score=0.0,
        grammar_weak_count=0,
        grammar_weak_score=0.0,
        failure_cluster_count=0,
        failure_cluster_score=0.0,
        total_score=0.0,
    )


def _high_pressure() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=50,
        overdue_srs_score=1.0,
        grammar_weak_count=10,
        grammar_weak_score=1.0,
        failure_cluster_count=15,
        failure_cluster_score=1.0,
        total_score=1.0,
    )


def _threshold_pressure() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=20,
        overdue_srs_score=0.6,
        grammar_weak_count=5,
        grammar_weak_score=0.5,
        failure_cluster_count=5,
        failure_cluster_score=0.5,
        total_score=REPAIR_THRESHOLD,
    )


def _just_below_threshold() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=10,
        overdue_srs_score=0.3,
        grammar_weak_count=2,
        grammar_weak_score=0.3,
        failure_cluster_count=2,
        failure_cluster_score=0.2,
        total_score=REPAIR_THRESHOLD - 0.01,
    )


class TestDetectPrimaryTrack:
    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}._has_lesson_progress", return_value=False)
    @patch(f"{MODULE}._has_active_book_course", return_value=True)
    def test_book_course_wins(self, _bc, _lp, _br):
        assert detect_primary_track(1) == SourceKind.book_course

    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}._has_lesson_progress", return_value=True)
    @patch(f"{MODULE}._has_active_book_course", return_value=False)
    def test_normal_course(self, _bc, _lp, _br):
        assert detect_primary_track(1) == SourceKind.normal_course

    @patch(f"{MODULE}._has_book_reading", return_value=True)
    @patch(f"{MODULE}._has_lesson_progress", return_value=False)
    @patch(f"{MODULE}._has_active_book_course", return_value=False)
    def test_books_reading(self, _bc, _lp, _br):
        assert detect_primary_track(1) == SourceKind.books

    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}._has_lesson_progress", return_value=False)
    @patch(f"{MODULE}._has_active_book_course", return_value=False)
    def test_no_track(self, _bc, _lp, _br):
        assert detect_primary_track(1) is None

    @patch(f"{MODULE}._has_book_reading", return_value=True)
    @patch(f"{MODULE}._has_lesson_progress", return_value=True)
    @patch(f"{MODULE}._has_active_book_course", return_value=True)
    def test_book_course_priority_over_others(self, _bc, _lp, _br):
        assert detect_primary_track(1) == SourceKind.book_course

    @patch(f"{MODULE}._has_book_reading", return_value=True)
    @patch(f"{MODULE}._has_lesson_progress", return_value=True)
    @patch(f"{MODULE}._has_active_book_course", return_value=False)
    def test_normal_course_priority_over_books(self, _bc, _lp, _br):
        assert detect_primary_track(1) == SourceKind.normal_course


class TestSelectMission:
    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_repair_when_high_pressure(self, mock_track, mock_pressure):
        mock_pressure.return_value = _high_pressure()
        mock_track.return_value = SourceKind.normal_course

        mission_type, reason_code, reason_text, breakdown = select_mission(1)

        assert mission_type == MissionType.repair
        assert reason_code == "repair_pressure_high"
        assert breakdown is not None
        mock_track.assert_not_called()

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_repair_at_exact_threshold(self, mock_track, mock_pressure):
        mock_pressure.return_value = _threshold_pressure()

        mission_type, reason_code, _, _ = select_mission(1)

        assert mission_type == MissionType.repair
        assert reason_code == "repair_pressure_high"

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_reading_when_track_is_books(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.books

        mission_type, reason_code, _, _ = select_mission(1)

        assert mission_type == MissionType.reading
        assert reason_code == "primary_track_reading"

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_progress_when_normal_course(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.normal_course

        mission_type, reason_code, _, _ = select_mission(1)

        assert mission_type == MissionType.progress
        assert reason_code == "primary_track_progress"

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_progress_when_book_course(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.book_course

        mission_type, reason_code, _, _ = select_mission(1)

        assert mission_type == MissionType.progress
        assert reason_code == "primary_track_progress"

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_cold_start_when_no_track(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = None

        mission_type, reason_code, _, _ = select_mission(1)

        assert mission_type == MissionType.progress
        assert reason_code == "cold_start"

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_repair_overrides_reading_track(self, mock_track, mock_pressure):
        mock_pressure.return_value = _high_pressure()
        mock_track.return_value = SourceKind.books

        mission_type, _, _, _ = select_mission(1)

        assert mission_type == MissionType.repair

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_no_repair_below_threshold(self, mock_track, mock_pressure):
        mock_pressure.return_value = _just_below_threshold()
        mock_track.return_value = SourceKind.normal_course

        mission_type, _, _, _ = select_mission(1)

        assert mission_type == MissionType.progress

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_returns_tuple_of_four(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.normal_course

        result = select_mission(1)

        assert isinstance(result, tuple)
        assert len(result) == 4
        assert isinstance(result[0], MissionType)
        assert isinstance(result[1], str)
        assert isinstance(result[2], str)
        assert result[3] is None

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_tz_passed_to_pressure(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.normal_course

        select_mission(42, tz="Europe/Moscow")

        mock_pressure.assert_called_once_with(42, "Europe/Moscow")

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_reason_text_not_empty(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        for track in [None, SourceKind.normal_course, SourceKind.books]:
            mock_track.return_value = track
            _, _, reason_text, _ = select_mission(1)
            assert len(reason_text) > 0

        mock_pressure.return_value = _high_pressure()
        _, _, reason_text, _ = select_mission(1)
        assert len(reason_text) > 0


class TestSelectMissionPriority:
    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_priority_order_repair_first(self, mock_track, mock_pressure):
        mock_pressure.return_value = _high_pressure()
        mock_track.return_value = SourceKind.books

        t, _, _, _ = select_mission(1)
        assert t == MissionType.repair

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_priority_order_reading_before_progress(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.books

        t, _, _, _ = select_mission(1)
        assert t == MissionType.reading

    @patch(f"{MODULE}.calculate_repair_pressure")
    @patch(f"{MODULE}.detect_primary_track")
    def test_priority_order_progress_default(self, mock_track, mock_pressure):
        mock_pressure.return_value = _low_pressure()
        mock_track.return_value = SourceKind.book_course

        t, _, _, _ = select_mission(1)
        assert t == MissionType.progress
