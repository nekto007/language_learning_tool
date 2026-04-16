"""Tests for app/daily_plan/assembler.py — level-aware cold start and edge cases."""
from unittest.mock import MagicMock, patch, ANY

import pytest

ASSEMBLER_MOD = "app.daily_plan.assembler"


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
# _find_next_lesson — cold start behaviour
# ---------------------------------------------------------------------------


class TestFindNextLessonColdStart:
    """Tests that verify _find_next_lesson() uses level-aware module selection
    when the user has no completed lessons (cold start)."""

    def _run(
        self,
        user_id: int,
        level_code: str,
        level_order: int,
        expected_lesson_id: int = 42,
    ) -> dict:
        """Helper: configure mocks and call _find_next_lesson."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_module = _mock_module(module_id=10)
        mock_lesson = _mock_lesson(lesson_id=expected_lesson_id, module_id=10)

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value=level_code) as mock_gcl,
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=level_order) as mock_cto,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
        ):
            # Cold start: no completed lesson
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = None

            # Module cold-start query chain: .join().filter().order_by().first()
            q = MagicMock()
            mock_module_cls.query.join.return_value = q
            q.filter.return_value.order_by.return_value.first.return_value = mock_module
            # Support the no-filter path (when order == -1, CEFR code not found)
            q.order_by.return_value.first.return_value = mock_module

            # Module.query.get for module metadata
            mock_module_cls.query.get.return_value = mock_module

            # Lesson query
            mock_lessons_cls.query.filter_by.return_value.order_by.return_value.first.return_value = mock_lesson

            result = _find_next_lesson(user_id=user_id)

            return {
                "result": result,
                "mock_gcl": mock_gcl,
                "mock_cto": mock_cto,
            }

    def test_cold_start_b1_onboarding_calls_level_utils(self):
        """Cold start with onboarding B1 → get_user_current_cefr_level called,
        and module query uses the returned level order."""
        out = self._run(user_id=7, level_code="B1", level_order=4)
        out["mock_gcl"].assert_called_once_with(7, ANY)
        out["mock_cto"].assert_called_once_with("B1", ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42

    def test_cold_start_no_onboarding_returns_a0_lesson(self):
        """Cold start with no onboarding → level_code='A0', order=0,
        still returns a lesson."""
        out = self._run(user_id=1, level_code="A0", level_order=0)
        out["mock_gcl"].assert_called_once_with(1, ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42

    def test_cold_start_c1_onboarding_returns_lesson(self):
        """Cold start with C1 onboarding → level_code='C1', order=6,
        returns a lesson from the C1+ module."""
        out = self._run(user_id=3, level_code="C1", level_order=6)
        out["mock_gcl"].assert_called_once_with(3, ANY)
        out["mock_cto"].assert_called_once_with("C1", ANY)
        assert out["result"] is not None

    def test_cold_start_unknown_level_skips_cefr_filter(self):
        """When _cefr_code_to_order returns -1 (e.g. 'A0' not in DB), filter is
        skipped and the unfiltered module query is used."""
        out = self._run(user_id=2, level_code="A0", level_order=-1)
        out["mock_gcl"].assert_called_once_with(2, ANY)
        out["mock_cto"].assert_called_once_with("A0", ANY)
        assert out["result"] is not None
        assert out["result"]["lesson_id"] == 42

    def test_cold_start_returns_none_when_no_module_found(self):
        """Cold start → no module found at user's level → returns None."""
        from app.daily_plan.assembler import _find_next_lesson

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level", return_value="C2"),
            patch(f"{ASSEMBLER_MOD}._cefr_code_to_order", return_value=7),
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = None
            q = MagicMock()
            mock_module_cls.query.join.return_value = q
            q.filter.return_value.order_by.return_value.first.return_value = None

            result = _find_next_lesson(user_id=5)
            assert result is None


class TestFindNextLessonWithProgress:
    """Tests for _find_next_lesson() when user has prior lesson progress."""

    def test_returns_none_when_all_lessons_completed(self):
        """User has completed lessons but no next lesson exists (all curriculum done).
        Must return None — NOT fall through to cold start."""
        from app.daily_plan.assembler import _find_next_lesson

        mock_last = MagicMock()
        mock_last.lesson_id = 99
        mock_lesson = _mock_lesson(lesson_id=99, module_id=10)
        mock_lesson.number = 1
        mock_module = _mock_module(module_id=10, number=5)
        mock_module.level_id = 3

        with (
            patch(f"{ASSEMBLER_MOD}.LessonProgress") as mock_lp,
            patch(f"{ASSEMBLER_MOD}.Lessons") as mock_lessons_cls,
            patch(f"{ASSEMBLER_MOD}.Module") as mock_module_cls,
            patch(f"{ASSEMBLER_MOD}.CEFRLevel") as mock_cefr_cls,
            patch(f"{ASSEMBLER_MOD}.get_user_current_cefr_level") as mock_gcl,
        ):
            mock_lp.query.filter.return_value.order_by.return_value.first.return_value = mock_last
            mock_lessons_cls.query.get.return_value = mock_lesson
            mock_module_cls.query.get.return_value = mock_module

            # Column comparisons (Lessons.number > x, CEFRLevel.order > x) are evaluated
            # before .filter() is called; configure __gt__ on mock columns to avoid TypeError.
            mock_lessons_cls.number.__gt__ = MagicMock(return_value=MagicMock())
            mock_cefr_cls.order.__gt__ = MagicMock(return_value=MagicMock())

            # No next lesson in same module
            mock_lessons_cls.query.filter.return_value.order_by.return_value.first.return_value = None
            # No next module in same level
            mock_module_cls.query.filter.return_value.first.return_value = None
            # No next CEFR level
            mock_current_level = MagicMock()
            mock_current_level.order = 6
            mock_cefr_cls.query.get.return_value = mock_current_level
            mock_cefr_cls.query.filter.return_value.order_by.return_value.first.return_value = None

            result = _find_next_lesson(user_id=42)

            assert result is None
            # Cold start must NOT be entered — get_user_current_cefr_level should not be called
            mock_gcl.assert_not_called()


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
