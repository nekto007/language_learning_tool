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
from app.daily_plan.repair_pressure import RepairBreakdown
from app.daily_plan.service import (
    get_mission_plan,
    get_daily_plan_unified,
    _mission_plan_to_dict,
)

MODULE = "app.daily_plan.service"


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
            id="42",
            label="Урок 5",
        ),
        phases=[
            MissionPhase(phase=PhaseKind.recall, title="Recall", source_kind=SourceKind.srs, mode="srs_review"),
            MissionPhase(phase=PhaseKind.learn, title="Learn", source_kind=SourceKind.normal_course, mode="curriculum_lesson"),
            MissionPhase(phase=PhaseKind.use, title="Use", source_kind=SourceKind.normal_course, mode="lesson_practice"),
        ],
        legacy={"next_lesson": {"lesson_id": 42}},
    )


def _make_repair_plan() -> MissionPlan:
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.repair,
            title="Укрепляем основу",
            reason_code="repair_pressure_high",
            reason_text="Слабые места",
        ),
        primary_goal=PrimaryGoal(type="repair", title="Закрыть слабые точки", success_criterion="repair_session_done"),
        primary_source=PrimarySource(kind=SourceKind.srs, id=None, label="Повторение"),
        phases=[
            MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.srs, mode="srs_review"),
            MissionPhase(phase=PhaseKind.learn, title="L", source_kind=SourceKind.grammar_lab, mode="grammar_practice"),
            MissionPhase(phase=PhaseKind.use, title="U", source_kind=SourceKind.grammar_lab, mode="targeted_quiz"),
            MissionPhase(phase=PhaseKind.close, title="C", source_kind=SourceKind.vocab, mode="success_marker", required=False),
        ],
        legacy={"overdue_srs": 20, "grammar_weak": 5},
    )


def _make_reading_plan() -> MissionPlan:
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.reading,
            title="Читаем и учимся",
            reason_code="primary_track_reading",
            reason_text="Чтение",
        ),
        primary_goal=PrimaryGoal(type="read", title="Прочитать", success_criterion="reading_completed"),
        primary_source=PrimarySource(kind=SourceKind.books, id="7", label="Alice"),
        phases=[
            MissionPhase(phase=PhaseKind.recall, title="R", source_kind=SourceKind.vocab, mode="book_vocab_recall"),
            MissionPhase(phase=PhaseKind.read, title="Read", source_kind=SourceKind.books, mode="book_reading"),
            MissionPhase(phase=PhaseKind.use, title="Use", source_kind=SourceKind.vocab, mode="reading_vocab_extract"),
        ],
        legacy={"book_to_read": {"id": 7}},
    )


def _low_breakdown() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=5, overdue_srs_score=0.1,
        grammar_weak_count=2, grammar_weak_score=0.1,
        failure_cluster_count=1, failure_cluster_score=0.05,
        total_score=0.1,
    )


def _high_breakdown() -> RepairBreakdown:
    return RepairBreakdown(
        overdue_srs_count=50, overdue_srs_score=1.0,
        grammar_weak_count=10, grammar_weak_score=1.0,
        failure_cluster_count=15, failure_cluster_score=1.0,
        total_score=1.0,
    )


class TestMissionPlanToDict:
    def test_serializes_enums_to_values(self):
        plan = _make_progress_plan()
        d = _mission_plan_to_dict(plan)
        assert d['mission']['type'] == 'progress'
        assert d['primary_source']['kind'] == 'normal_course'
        assert d['phases'][0]['phase'] == 'recall'
        assert d['phases'][0]['source_kind'] == 'srs'

    def test_includes_all_top_level_keys(self):
        plan = _make_progress_plan()
        d = _mission_plan_to_dict(plan)
        assert set(d.keys()) >= {'plan_version', 'mission', 'primary_goal', 'primary_source', 'phases', 'completion', 'legacy'}

    def test_phases_have_all_fields(self):
        plan = _make_progress_plan()
        d = _mission_plan_to_dict(plan)
        phase = d['phases'][0]
        assert set(phase.keys()) == {'id', 'phase', 'title', 'source_kind', 'mode', 'required', 'completed'}

    def test_legacy_block_preserved(self):
        plan = _make_progress_plan()
        d = _mission_plan_to_dict(plan)
        assert d['legacy'] == {"next_lesson": {"lesson_id": 42}}

    def test_no_legacy_key_when_none(self):
        plan = _make_progress_plan()
        plan.legacy = None
        d = _mission_plan_to_dict(plan)
        assert 'legacy' not in d


class TestPlanMetaHelper:
    def test_mission_mode_meta_added(self):
        from app.daily_plan.service import _with_plan_meta

        payload = {'mission': {'type': 'progress'}}
        result = _with_plan_meta(
            payload,
            mission_plan_enabled=True,
            effective_mode='mission',
        )

        assert result['_plan_meta']['mission_plan_enabled'] is True
        assert result['_plan_meta']['effective_mode'] == 'mission'
        assert result['_plan_meta']['fallback_reason'] is None

    def test_legacy_fallback_meta_added(self):
        from app.daily_plan.service import _with_plan_meta

        payload = {'steps': {}}
        result = _with_plan_meta(
            payload,
            mission_plan_enabled=True,
            effective_mode='legacy_fallback',
            fallback_reason='mission_build_failed',
        )

        assert result['_plan_meta']['mission_plan_enabled'] is True
        assert result['_plan_meta']['effective_mode'] == 'legacy_fallback'
        assert result['_plan_meta']['fallback_reason'] == 'mission_build_failed'


class TestGetMissionPlan:
    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.assemble_progress_mission")
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "primary_track_progress", "Вперёд", None))
    def test_progress_happy_path(self, _sel, mock_asm, _track):
        mock_asm.return_value = _make_progress_plan()
        result = get_mission_plan(1)
        assert result is not None
        assert result['mission']['type'] == 'progress'
        assert result['plan_version'] == '1'
        mock_asm.assert_called_once_with(
            1,
            SourceKind.normal_course,
            reason_code="primary_track_progress",
            reason_text="Вперёд",
            tz=None,
        )

    @patch(f"{MODULE}.assemble_repair_mission")
    @patch(f"{MODULE}.select_mission")
    def test_repair_happy_path(self, mock_sel, mock_asm):
        breakdown = _high_breakdown()
        mock_sel.return_value = (MissionType.repair, "repair_pressure_high", "Слабые места", breakdown)
        mock_asm.return_value = _make_repair_plan()
        result = get_mission_plan(1)
        assert result is not None
        assert result['mission']['type'] == 'repair'
        mock_asm.assert_called_once_with(
            1,
            breakdown,
            reason_code="repair_pressure_high",
            reason_text="Слабые места",
            tz=None,
        )

    @patch(f"{MODULE}.assemble_reading_mission")
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.reading, "primary_track_reading", "Чтение", None))
    def test_reading_happy_path(self, _sel, mock_asm):
        mock_asm.return_value = _make_reading_plan()
        result = get_mission_plan(1)
        assert result is not None
        assert result['mission']['type'] == 'reading'

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.assemble_progress_mission", return_value=None)
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "cold_start", "Start", None))
    def test_assembly_returns_none(self, _sel, _asm, _track):
        result = get_mission_plan(1)
        assert result is None

    @patch(f"{MODULE}.select_mission", side_effect=Exception("DB error"))
    def test_exception_returns_none(self, _sel):
        result = get_mission_plan(1)
        assert result is None

    @patch(f"{MODULE}.detect_primary_track", return_value=None)
    @patch(f"{MODULE}.assemble_progress_mission")
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "cold_start", "Start", None))
    def test_no_track_defaults_to_normal_course(self, _sel, mock_asm, _track):
        mock_asm.return_value = _make_progress_plan()
        get_mission_plan(1)
        mock_asm.assert_called_once_with(
            1,
            SourceKind.normal_course,
            reason_code="cold_start",
            reason_text="Start",
            tz=None,
        )

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.book_course)
    @patch(f"{MODULE}.assemble_progress_mission")
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "primary_track_progress", "Вперёд", None))
    def test_book_course_track_passed_to_assembler(self, _sel, mock_asm, _track):
        mock_asm.return_value = _make_progress_plan()
        get_mission_plan(1)
        mock_asm.assert_called_once_with(
            1,
            SourceKind.book_course,
            reason_code="primary_track_progress",
            reason_text="Вперёд",
            tz=None,
        )

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.books)
    @patch(f"{MODULE}.assemble_progress_mission")
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "cold_start", "Start", None))
    def test_books_track_falls_back_to_normal_course(self, _sel, mock_asm, _track):
        mock_asm.return_value = _make_progress_plan()
        get_mission_plan(1)
        mock_asm.assert_called_once_with(
            1,
            SourceKind.normal_course,
            reason_code="cold_start",
            reason_text="Start",
            tz=None,
        )


ASSEMBLER_MODULE = "app.daily_plan.assembler"


MISSION_SELECTOR_MODULE = "app.daily_plan.mission_selector"


class TestRepairMissionDegradation:
    """Repair mission degrades to progress when SRS=0 and grammar=0."""

    @patch(f"{ASSEMBLER_MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{ASSEMBLER_MODULE}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MODULE}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MODULE}._count_srs_due", return_value=0)
    def test_zero_srs_and_grammar_delegates_to_progress(self, _srs, _gram, mock_progress, _track):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.0,
        )
        mock_progress.return_value = _make_progress_plan()

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.progress
        mock_progress.assert_called_once_with(1, SourceKind.normal_course, reason_code="progress_next_step", reason_text="Всё повторено — двигаемся дальше по курсу", tz=None)

    @patch(f"{ASSEMBLER_MODULE}.detect_primary_track", return_value=SourceKind.book_course)
    @patch(f"{ASSEMBLER_MODULE}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MODULE}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MODULE}._count_srs_due", return_value=0)
    def test_zero_srs_and_grammar_book_course_track(self, _srs, _gram, mock_progress, _track):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.0,
        )
        mock_progress.return_value = _make_progress_plan()

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.progress
        mock_progress.assert_called_once_with(1, SourceKind.book_course, reason_code="progress_next_step", reason_text="Всё повторено — двигаемся дальше по курсу", tz=None)

    @patch(f"{ASSEMBLER_MODULE}.detect_primary_track", return_value=SourceKind.books)
    @patch(f"{ASSEMBLER_MODULE}.assemble_reading_mission")
    @patch(f"{ASSEMBLER_MODULE}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MODULE}._count_srs_due", return_value=0)
    def test_zero_srs_and_grammar_books_track_delegates_to_reading(self, _srs, _gram, mock_reading, _track):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.0,
        )
        mock_reading.return_value = _make_reading_plan()

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.reading
        mock_reading.assert_called_once_with(1, reason_code="progress_next_step", reason_text="Всё повторено — продолжаем чтение", tz=None)

    @patch(f"{ASSEMBLER_MODULE}.detect_primary_track", return_value=SourceKind.books)
    @patch(f"{ASSEMBLER_MODULE}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MODULE}.assemble_reading_mission", return_value=None)
    @patch(f"{ASSEMBLER_MODULE}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MODULE}._count_srs_due", return_value=0)
    def test_zero_srs_and_grammar_books_track_reading_none_falls_back_to_progress(
        self, _srs, _gram, _reading, mock_progress, _track
    ):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.0,
        )
        mock_progress.return_value = _make_progress_plan()

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.progress
        mock_progress.assert_called_once_with(
            1, SourceKind.normal_course,
            reason_code="progress_next_step",
            reason_text="Всё повторено — двигаемся дальше по курсу",
            tz=None,
        )

    @patch(f"{ASSEMBLER_MODULE}.detect_primary_track", return_value=None)
    @patch(f"{ASSEMBLER_MODULE}.assemble_progress_mission")
    @patch(f"{ASSEMBLER_MODULE}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MODULE}._count_srs_due", return_value=0)
    def test_zero_srs_and_grammar_no_track_defaults_to_normal_course(self, _srs, _gram, mock_progress, _track):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.0,
        )
        mock_progress.return_value = _make_progress_plan()

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.progress
        mock_progress.assert_called_once_with(1, SourceKind.normal_course, reason_code="progress_next_step", reason_text="Всё повторено — двигаемся дальше по курсу", tz=None)


class TestAssemblerWarningLogs:
    """Assembler failures produce structured warning logs in get_mission_plan."""

    @patch(f"{MODULE}.detect_primary_track", return_value=SourceKind.normal_course)
    @patch(f"{MODULE}.assemble_progress_mission", return_value=None)
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.progress, "cold_start", "Start", None))
    def test_progress_assembler_none_emits_warning(self, _sel, _asm, _track, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.daily_plan.service"):
            result = get_mission_plan(1)
        assert result is None
        assert any("assembler returned None" in r.message for r in caplog.records)

    @patch(f"{MODULE}.assemble_repair_mission", return_value=None)
    @patch(f"{MODULE}.select_mission")
    def test_repair_assembler_none_emits_warning(self, mock_sel, _asm, caplog):
        import logging
        breakdown = _high_breakdown()
        mock_sel.return_value = (MissionType.repair, "repair_pressure_high", "Слабые места", breakdown)

        with caplog.at_level(logging.WARNING, logger="app.daily_plan.service"):
            result = get_mission_plan(1)
        assert result is None
        assert any("assembler returned None" in r.message for r in caplog.records)

    @patch(f"{MODULE}.assemble_reading_mission", return_value=None)
    @patch(f"{MODULE}.select_mission", return_value=(MissionType.reading, "primary_track_reading", "Чтение", None))
    def test_reading_assembler_none_emits_warning(self, _sel, _asm, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.daily_plan.service"):
            result = get_mission_plan(1)
        assert result is None
        assert any("assembler returned None" in r.message for r in caplog.records)


LEGACY_MODULE = "app.telegram.queries"


class TestGetDailyPlanUnified:
    @patch(f"{MODULE}.get_mission_plan")
    @patch(f"{LEGACY_MODULE}.get_daily_plan_v2")
    def test_flag_on_returns_mission_plan(self, mock_legacy, mock_mission, app, db_session, test_user):
        test_user.use_mission_plan = True
        db_session.flush()

        mock_mission.return_value = {'mission': {'type': 'progress'}, 'plan_version': '1'}
        result = get_daily_plan_unified(test_user.id)
        assert result['mission']['type'] == 'progress'
        mock_legacy.assert_not_called()

    @patch(f"{MODULE}.get_mission_plan")
    @patch(f"{LEGACY_MODULE}.get_daily_plan_v2")
    def test_flag_off_returns_legacy(self, mock_legacy, mock_mission, app, db_session, test_user):
        test_user.use_mission_plan = False
        db_session.flush()

        mock_legacy.return_value = {'steps': []}
        result = get_daily_plan_unified(test_user.id)
        assert 'steps' in result
        mock_mission.assert_not_called()
        assert result['_plan_meta']['mission_plan_enabled'] is False
        assert result['_plan_meta']['effective_mode'] == 'legacy'

    @patch(f"{MODULE}.get_mission_plan", return_value=None)
    @patch(f"{LEGACY_MODULE}.get_daily_plan_v2", return_value={'steps': []})
    def test_flag_on_but_mission_fails_falls_back(self, mock_legacy, mock_mission, app, db_session, test_user):
        test_user.use_mission_plan = True
        db_session.flush()

        result = get_daily_plan_unified(test_user.id)
        assert 'steps' in result
        mock_legacy.assert_called_once()
        assert result['_plan_meta']['mission_plan_enabled'] is True
        assert result['_plan_meta']['effective_mode'] == 'legacy_fallback'
        assert result['_plan_meta']['fallback_reason'] == 'mission_build_failed'

    @patch(f"{LEGACY_MODULE}.get_daily_plan_v2", return_value={'steps': []})
    def test_nonexistent_user_returns_legacy(self, mock_legacy, app):
        result = get_daily_plan_unified(999999)
        assert 'steps' in result
