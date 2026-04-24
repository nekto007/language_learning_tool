"""Tests for app/daily_plan/assembler.py — level-aware cold start and edge cases."""
from unittest.mock import MagicMock, patch, ANY

import pytest

ASSEMBLER_MOD = "app.daily_plan.assembler"


@pytest.fixture(autouse=True)
def _assume_recall_content():
    """Treat guided_recall as having content unless a test opts out.

    Tests in this file drive the assembler with mocks for lesson/SRS counts
    and don't set up the daily-plan card pool; without this patch every
    no-SRS scenario would skip the recall phase and break pre-existing
    expectations.
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
# assemble_repair_mission — normal (non-degenerate) path
# ---------------------------------------------------------------------------


class TestAssembleRepairMissionNormalPath:
    """assemble_repair_mission when SRS > 0 or grammar_due > 0 (no degradation)."""

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic")
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=3)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=10)
    def test_returns_repair_plan_with_grammar_topic(self, _srs, _gram, mock_topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        mock_topic.return_value = {'title': 'Past Simple', 'topic_id': 7}
        breakdown = RepairBreakdown(
            overdue_srs_count=10, overdue_srs_score=0.5,
            grammar_weak_count=3, grammar_weak_score=0.3,
            failure_cluster_count=1, failure_cluster_score=0.1,
            total_score=0.65,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.repair
        assert 4 <= len(result.phases) <= 5
        assert any(p.phase == PhaseKind.close for p in result.phases)
        assert result.primary_source.kind == SourceKind.srs
        assert result.legacy['grammar_topic'] == {'title': 'Past Simple', 'topic_id': 7}

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic", return_value=None)
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=5)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    def test_returns_repair_plan_without_grammar_topic(self, _srs, _gram, _topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=0, overdue_srs_score=0.0,
            grammar_weak_count=5, grammar_weak_score=0.5,
            failure_cluster_count=2, failure_cluster_score=0.2,
            total_score=0.65,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        assert result.mission.type == MissionType.repair
        assert 4 <= len(result.phases) <= 5
        # When grammar_topic is None and srs_due=0, primary source falls back to vocab
        assert result.primary_source.kind == SourceKind.vocab
        # After dedup: phase[0]=guided_recall(words), phase[1] was vocab_drill(words dup)
        # → substituted to grammar_practice(grammar) to avoid duplicate category
        learn_phase = result.phases[1]
        assert learn_phase.mode == "grammar_practice"

    @patch(f"{ASSEMBLER_MOD}._find_weak_grammar_topic", return_value=None)
    @patch(f"{ASSEMBLER_MOD}._count_grammar_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=20)
    def test_srs_only_recall_phase_uses_srs_review_mode(self, _srs, _gram, _topic):
        from app.daily_plan.assembler import assemble_repair_mission
        from app.daily_plan.models import PhaseKind
        from app.daily_plan.repair_pressure import RepairBreakdown

        breakdown = RepairBreakdown(
            overdue_srs_count=20, overdue_srs_score=0.8,
            grammar_weak_count=0, grammar_weak_score=0.0,
            failure_cluster_count=0, failure_cluster_score=0.0,
            total_score=0.4,
        )

        result = assemble_repair_mission(1, breakdown)

        assert result is not None
        recall = result.phases[0]
        assert recall.phase == PhaseKind.recall
        assert recall.mode == "srs_review"


# ---------------------------------------------------------------------------
# assemble_reading_mission
# ---------------------------------------------------------------------------


class TestAssembleReadingMission:
    """Tests for assemble_reading_mission() — book reading track."""

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_none_when_no_book(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission

        mock_book.return_value = None
        result = assemble_reading_mission(1)
        assert result is None

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_3_phases_when_no_srs(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission
        from app.daily_plan.models import MissionType, SourceKind, PhaseKind

        mock_book.return_value = {'id': 3, 'title': 'Alice in Wonderland'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert result.mission.type == MissionType.reading
        assert 3 <= len(result.phases) <= 4
        assert result.phases[0].phase == PhaseKind.recall
        assert result.phases[1].phase == PhaseKind.read
        assert result.phases[2].phase == PhaseKind.use
        assert result.primary_source.kind == SourceKind.books
        assert result.primary_source.id == '3'

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=5)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_returns_4_phases_when_srs_due(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission
        from app.daily_plan.models import PhaseKind

        mock_book.return_value = {'id': 3, 'title': 'Alice in Wonderland'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert 4 <= len(result.phases) <= 5
        check = next(p for p in result.phases if p.phase == PhaseKind.check)
        assert check.required is False
        # Recall mode uses book_vocab_recall when SRS > 0
        assert result.phases[0].mode == "book_vocab_recall"

    @patch(f"{ASSEMBLER_MOD}._count_srs_due", return_value=0)
    @patch(f"{ASSEMBLER_MOD}._find_next_book")
    def test_legacy_block_contains_book(self, mock_book, _srs):
        from app.daily_plan.assembler import assemble_reading_mission

        mock_book.return_value = {'id': 7, 'title': 'Crime and Punishment'}
        result = assemble_reading_mission(1)

        assert result is not None
        assert result.legacy == {'book_to_read': {'id': 7, 'title': 'Crime and Punishment'}}


def _mock_module(module_id: int = 10, number: int = 1) -> MagicMock:
    m = MagicMock()
    m.id = module_id
    m.number = number
    return m


def _mock_lesson(lesson_id: int = 42, module_id: int = 10, title: str = "Lesson 1") -> MagicMock:
    lesson = MagicMock()
    lesson.id = lesson_id
    lesson.module_id = module_id
    lesson.title = title
    lesson.type = "vocabulary"
    lesson.number = 1
    return lesson


# ---------------------------------------------------------------------------
# _find_next_lesson is covered by tests/curriculum/test_navigation.py which
# exercises the canonical implementation in app.curriculum.navigation via
# a real DB. The assembler function is now a thin dict-wrapper over it.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# _find_next_book_course_lesson — empty lessons warning
# ---------------------------------------------------------------------------


class TestFindNextBookCourseLessonEmptyWarning:
    def test_no_enrollment_returns_none(self):
        """When user has no active book course enrollment, returns None immediately."""
        from app.daily_plan.assembler import _find_next_book_course_lesson

        with patch(f"{ASSEMBLER_MOD}.BookCourseEnrollment") as mock_bce:
            mock_bce.query.filter_by.return_value.first.return_value = None
            result = _find_next_book_course_lesson(user_id=1)

        assert result is None

    def test_empty_lessons_logs_warning(self, caplog):
        """When enrollment exists but course has no lessons, a warning is logged."""
        import logging
        from app.daily_plan.assembler import _find_next_book_course_lesson

        mock_enrollment = MagicMock()
        mock_enrollment.id = 99
        mock_enrollment.course_id = 5

        # Mock db.session.query() chain used for completed_ids
        mock_db = MagicMock()
        mock_db.session.query.return_value.filter.return_value.all.return_value = []

        with (
            patch(f"{ASSEMBLER_MOD}.BookCourseEnrollment") as mock_bce,
            patch(f"{ASSEMBLER_MOD}.DailyLesson") as mock_dl,
            patch(f"{ASSEMBLER_MOD}.BookCourseModule"),
            patch(f"{ASSEMBLER_MOD}.db", mock_db),
        ):
            mock_bce.query.filter_by.return_value.first.return_value = mock_enrollment

            # Empty lesson list
            mock_dl.query.join.return_value.filter.return_value.order_by.return_value.all.return_value = []

            with caplog.at_level(logging.WARNING, logger="app.daily_plan.assembler"):
                result = _find_next_book_course_lesson(user_id=1)

            assert result is None
            assert any("no lessons found" in r.message for r in caplog.records)
