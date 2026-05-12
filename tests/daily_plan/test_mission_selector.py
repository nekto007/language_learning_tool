"""Tests for LISTENING mission type: selection, assembly, and rotation."""
from unittest.mock import MagicMock, patch

import pytest

from app.daily_plan.models import MissionPhase, MissionPlan, MissionType, PhaseKind, SourceKind
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, RepairBreakdown

MODULE = "app.daily_plan.mission_selector"
ASSEMBLER = "app.daily_plan.assembler"


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


class TestListeningMissionSelection:
    """select_mission() returns LISTENING when conditions are met."""

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=0)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_listening_selected_when_streak_low_and_dictation_available(
        self, mock_pressure, _track, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        mission_type, reason_code, reason_text, breakdown = select_mission(1)

        assert mission_type == MissionType.listening
        assert reason_code == "listening_streak_low"
        assert breakdown is None

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=3)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_not_listening_when_streak_already_3(
        self, mock_pressure, _track, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        mission_type, _, _, _ = select_mission(1)

        assert mission_type == MissionType.progress

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=0)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=False)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_not_listening_when_no_dictation_available(
        self, mock_pressure, _track, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        mission_type, _, _, _ = select_mission(1)

        assert mission_type == MissionType.progress

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=0)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_repair_overrides_listening(
        self, mock_pressure, _track, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _high_pressure()
        from app.daily_plan.mission_selector import select_mission

        mission_type, _, _, _ = select_mission(1)

        assert mission_type == MissionType.repair

    @patch(f"{MODULE}.get_last_mission_type", return_value=None)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=0)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.books)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_reading_track_wins_over_listening(
        self, mock_pressure, _track, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        mission_type, _, _, _ = select_mission(1)

        # Reading track (books) takes priority over listening
        assert mission_type == MissionType.reading


class TestListeningMissionRotation:
    """Rotation logic includes LISTENING in the cycle."""

    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    def test_rotation_progress_to_listening_when_no_books(
        self, _track, _books, _dictation
    ):
        from app.daily_plan.mission_selector import _find_rotation_alternative

        alt = _find_rotation_alternative(1, MissionType.progress)
        assert alt == MissionType.listening

    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=False)
    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    def test_rotation_progress_to_none_when_no_alternative(
        self, _track, _books, _dictation
    ):
        from app.daily_plan.mission_selector import _find_rotation_alternative

        alt = _find_rotation_alternative(1, MissionType.progress)
        assert alt is None

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    def test_rotation_listening_to_progress(self, _track):
        from app.daily_plan.mission_selector import _find_rotation_alternative

        alt = _find_rotation_alternative(1, MissionType.listening)
        assert alt == MissionType.progress

    @patch(f"{MODULE}._has_book_reading", return_value=True)
    @patch(f"{MODULE}.detect_primary_track", return_value=None)
    def test_rotation_listening_to_reading_when_no_course(self, _track, _books):
        from app.daily_plan.mission_selector import _find_rotation_alternative

        alt = _find_rotation_alternative(1, MissionType.listening)
        assert alt == MissionType.reading

    @patch(f"{MODULE}.get_last_mission_type", return_value=MissionType.listening)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=1)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=True)
    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_listening_streak_building_suppresses_rotation(
        self, mock_pressure, _track, _books, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        # Yesterday was LISTENING and streak < 3: rotation must NOT fire so
        # the user can accumulate consecutive listening days toward the 3-day habit.
        mission_type, reason_code, _, _ = select_mission(1)
        assert mission_type == MissionType.listening
        assert reason_code == 'listening_streak_low'

    @patch(f"{MODULE}.get_last_mission_type", return_value=MissionType.listening)
    @patch(f"{MODULE}._get_listening_streak_days", return_value=3)
    @patch(f"{MODULE}._has_dictation_lessons_available", return_value=False)
    @patch(f"{MODULE}._has_book_reading", return_value=False)
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.calculate_repair_pressure")
    def test_rotation_applies_to_listening_when_streak_established(
        self, mock_pressure, _track, _books, _dictation, _streak, _last
    ):
        mock_pressure.return_value = _low_pressure()
        from app.daily_plan.mission_selector import select_mission

        # Streak >= 3 and no dictation available → picks progress, rotation fires
        mission_type, _, _, _ = select_mission(1)
        assert mission_type == MissionType.progress


class TestAssembleListeningMission:
    """assemble_listening_mission() builds a valid MissionPlan."""

    def _make_lesson_dict(self, lesson_id: int, title: str, lesson_type: str) -> dict:
        return {
            'lesson_id': lesson_id,
            'lesson_title': title,
            'lesson_type': lesson_type,
            'module_id': 1,
        }

    @patch(f"{ASSEMBLER}._maybe_add_bonus_phase", side_effect=lambda p, **kw: p)
    @patch(f"{ASSEMBLER}._has_guided_recall_content", return_value=False)
    @patch(f"{ASSEMBLER}._get_remaining_card_budget", return_value=(0, 0))
    @patch(f"{ASSEMBLER}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER}._find_next_lesson_of_types")
    def test_assembles_with_both_lessons(
        self, mock_find, _srs, _budget, _recall_content, _bonus
    ):
        def find_side_effect(user_id, lesson_types):
            if 'dictation' in lesson_types:
                return self._make_lesson_dict(1, "Диктант 1", "dictation")
            return self._make_lesson_dict(2, "Listening Immersion 1", "listening_immersion")

        mock_find.side_effect = find_side_effect
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(user_id=1)

        assert plan is not None
        assert plan.mission.type == MissionType.listening
        phase_kinds = [p.phase for p in plan.phases]
        assert PhaseKind.learn in phase_kinds
        assert PhaseKind.use in phase_kinds
        learn_phase = next(p for p in plan.phases if p.phase == PhaseKind.learn)
        assert learn_phase.mode == "dictation_lesson"
        use_phase = next(p for p in plan.phases if p.phase == PhaseKind.use)
        assert use_phase.mode == "listening_lesson"

    @patch(f"{ASSEMBLER}._maybe_add_bonus_phase", side_effect=lambda p, **kw: p)
    @patch(f"{ASSEMBLER}._has_guided_recall_content", return_value=False)
    @patch(f"{ASSEMBLER}._get_remaining_card_budget", return_value=(0, 0))
    @patch(f"{ASSEMBLER}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER}._find_next_lesson_of_types")
    def test_falls_back_to_meaning_prompt_when_no_listening_immersion(
        self, mock_find, _srs, _budget, _recall_content, _bonus
    ):
        def find_side_effect(user_id, lesson_types):
            if 'dictation' in lesson_types:
                return self._make_lesson_dict(1, "Диктант 1", "dictation")
            return None  # no listening_immersion

        mock_find.side_effect = find_side_effect
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(user_id=1)

        assert plan is not None
        use_phase = next(p for p in plan.phases if p.phase == PhaseKind.use)
        assert use_phase.mode == "meaning_prompt"

    @patch(f"{ASSEMBLER}._find_next_lesson_of_types", return_value=None)
    def test_returns_none_when_no_dictation(self, _find):
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(user_id=1)
        assert plan is None

    @patch(f"{ASSEMBLER}._maybe_add_bonus_phase", side_effect=lambda p, **kw: p)
    @patch(f"{ASSEMBLER}._has_guided_recall_content", return_value=True)
    @patch(f"{ASSEMBLER}._get_remaining_card_budget", return_value=(5, 5))
    @patch(f"{ASSEMBLER}._count_srs_due", return_value=5)
    @patch(f"{ASSEMBLER}._find_next_lesson_of_types")
    def test_includes_recall_when_srs_due(
        self, mock_find, _srs, _budget, _recall_content, _bonus
    ):
        def find_side_effect(user_id, lesson_types):
            if 'dictation' in lesson_types:
                return self._make_lesson_dict(1, "Диктант 1", "dictation")
            return self._make_lesson_dict(2, "Listening 1", "listening_immersion")

        mock_find.side_effect = find_side_effect
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(user_id=1)

        assert plan is not None
        phase_kinds = [p.phase for p in plan.phases]
        assert PhaseKind.recall in phase_kinds
        recall_phase = next(p for p in plan.phases if p.phase == PhaseKind.recall)
        assert recall_phase.mode == "srs_review"

    @patch(f"{ASSEMBLER}._maybe_add_bonus_phase", side_effect=lambda p, **kw: p)
    @patch(f"{ASSEMBLER}._has_guided_recall_content", return_value=False)
    @patch(f"{ASSEMBLER}._get_remaining_card_budget", return_value=(0, 0))
    @patch(f"{ASSEMBLER}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER}._find_next_lesson_of_types")
    def test_plan_has_3_to_5_phases(
        self, mock_find, _srs, _budget, _recall_content, _bonus
    ):
        def find_side_effect(user_id, lesson_types):
            if 'dictation' in lesson_types:
                return self._make_lesson_dict(1, "Диктант 1", "dictation")
            return self._make_lesson_dict(2, "Listening 1", "listening_immersion")

        mock_find.side_effect = find_side_effect
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(user_id=1)

        assert plan is not None
        assert 3 <= len(plan.phases) <= 5

    @patch(f"{ASSEMBLER}._maybe_add_bonus_phase", side_effect=lambda p, **kw: p)
    @patch(f"{ASSEMBLER}._has_guided_recall_content", return_value=False)
    @patch(f"{ASSEMBLER}._get_remaining_card_budget", return_value=(0, 0))
    @patch(f"{ASSEMBLER}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER}._find_next_lesson_of_types")
    def test_reason_code_and_text_passed_through(
        self, mock_find, _srs, _budget, _recall_content, _bonus
    ):
        def find_side_effect(user_id, lesson_types):
            if 'dictation' in lesson_types:
                return self._make_lesson_dict(1, "Диктант 1", "dictation")
            return None

        mock_find.side_effect = find_side_effect
        from app.daily_plan.assembler import assemble_listening_mission

        plan = assemble_listening_mission(
            user_id=1,
            reason_code="rotation_listening",
            reason_text="Сегодня тренируем слух для разнообразия",
        )

        assert plan is not None
        assert plan.mission.reason_code == "rotation_listening"
        assert plan.mission.reason_text == "Сегодня тренируем слух для разнообразия"
