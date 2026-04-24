"""
Tests for curriculum service layer: module access, lesson ordering, CEFR level calculation.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
from app.curriculum.service import complete_lesson, get_next_lesson
from app.curriculum.security import check_lesson_access, check_module_access
from app.daily_plan.level_utils import get_user_current_cefr_level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_level(db_session, order=1):
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name=f'Level {order}', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level, number=1):
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {number}',
        raw_content={},
        min_score_required=70,
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module, number=1, order=0, lesson_type='vocabulary'):
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'Lesson {number}',
        type=lesson_type,
        order=order,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete_lesson(db_session, user, lesson, score=90.0):
    progress = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=score,
    )
    db_session.add(progress)
    db_session.commit()
    return progress


# ---------------------------------------------------------------------------
# Module access check logic
# ---------------------------------------------------------------------------

class TestCheckModuleAccess:
    """Tests for check_module_access() in curriculum/security.py"""

    def test_unauthenticated_user_denied(self, app, db_session, test_module):
        """Unauthenticated current_user cannot access any module."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = False
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(test_module.id) is False

    def test_admin_always_granted(self, app, db_session, test_module):
        """Admin user has access to any module."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = True
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(test_module.id) is True

    def test_nonexistent_module_denied(self, app, db_session, test_user):
        """Non-existent module returns False."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(999999) is False

    def test_first_module_in_level_always_accessible(self, app, db_session, test_user, test_level):
        """First module in a level is always accessible to authenticated users."""
        with app.app_context():
            module = _make_module(db_session, test_level, number=1)
            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(module.id) is True

    def test_second_module_blocked_without_first_completion(self, app, db_session, test_user, test_level):
        """Second module is not accessible if user hasn't completed enough of first module."""
        with app.app_context():
            module1 = _make_module(db_session, test_level, number=1)
            module2 = _make_module(db_session, test_level, number=2)

            # Add a lesson to module1 but do NOT complete it
            lesson1 = _make_lesson(db_session, module1, number=1)

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(module2.id) is False

    def test_second_module_unlocked_after_first_module_completion(self, app, db_session, test_user, test_level):
        """Second module is accessible after user completes 80%+ of first module."""
        with app.app_context():
            module1 = _make_module(db_session, test_level, number=1)
            module2 = _make_module(db_session, test_level, number=2)

            lesson1 = _make_lesson(db_session, module1, number=1)
            _complete_lesson(db_session, test_user, lesson1, score=85.0)

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(module2.id) is True

    def test_user_with_existing_progress_can_access_module(self, app, db_session, test_user, test_level):
        """User with any lesson progress in a module can access it."""
        with app.app_context():
            module1 = _make_module(db_session, test_level, number=1)
            module2 = _make_module(db_session, test_level, number=2)

            lesson2 = _make_lesson(db_session, module2, number=1)

            # User has in-progress (not completed) lesson in module2
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=lesson2.id,
                status='in_progress',
                score=0.0,
            )
            db_session.add(progress)
            db_session.commit()

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_module_access(module2.id) is True


class TestCheckLessonAccess:
    """Tests for check_lesson_access() in curriculum/security.py"""

    def test_unauthenticated_denied(self, app, db_session, test_lesson_vocabulary):
        """Unauthenticated user cannot access any lesson."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = False
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(test_lesson_vocabulary.id) is False

    def test_admin_always_granted(self, app, db_session, test_lesson_vocabulary):
        """Admin always has lesson access."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = True
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(test_lesson_vocabulary.id) is True

    def test_nonexistent_lesson_denied(self, app, db_session, test_user):
        """Non-existent lesson returns False."""
        with app.app_context():
            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(999999) is False

    def test_completed_lesson_always_accessible(self, app, db_session, test_user, test_lesson_vocabulary):
        """A lesson the user already completed is always accessible (for review)."""
        with app.app_context():
            _complete_lesson(db_session, test_user, test_lesson_vocabulary)

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(test_lesson_vocabulary.id) is True

    def test_second_lesson_blocked_when_first_not_completed(self, app, db_session, test_user, test_module):
        """Second lesson in a module is blocked until first is completed."""
        with app.app_context():
            lesson1 = _make_lesson(db_session, test_module, number=10, order=10)
            lesson2 = _make_lesson(db_session, test_module, number=11, order=11)

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(lesson2.id) is False

    def test_second_lesson_accessible_after_first_completed(self, app, db_session, test_user, test_module):
        """Second lesson becomes accessible after completing the first."""
        with app.app_context():
            lesson1 = _make_lesson(db_session, test_module, number=20, order=20)
            lesson2 = _make_lesson(db_session, test_module, number=21, order=21)
            _complete_lesson(db_session, test_user, lesson1)

            mock_user = MagicMock()
            mock_user.is_authenticated = True
            mock_user.is_admin = False
            mock_user.id = test_user.id
            with patch('app.curriculum.security.current_user', mock_user):
                assert check_lesson_access(lesson2.id) is True


# ---------------------------------------------------------------------------
# Lesson ordering and availability
# ---------------------------------------------------------------------------

class TestLessonOrdering:
    """Tests for get_next_lesson() — lesson ordering within a module."""

    @pytest.mark.smoke
    def test_returns_next_lesson_by_order(self, app, db_session, test_module):
        """get_next_lesson returns the lesson with the next higher order."""
        with app.app_context():
            l1 = _make_lesson(db_session, test_module, number=30, order=30)
            l2 = _make_lesson(db_session, test_module, number=31, order=31)

            result = get_next_lesson(l1.id)
            assert result is not None
            assert result.id == l2.id

    def test_returns_none_for_last_lesson(self, app, db_session, test_module):
        """get_next_lesson returns None when there is no following lesson."""
        with app.app_context():
            last = _make_lesson(db_session, test_module, number=40, order=400)
            result = get_next_lesson(last.id)
            assert result is None

    def test_returns_none_for_invalid_lesson_id(self, app, db_session):
        """get_next_lesson returns None for a lesson that does not exist."""
        with app.app_context():
            assert get_next_lesson(999999) is None

    def test_fallback_to_number_when_order_is_none(self, app, db_session, test_module):
        """When order is None, get_next_lesson falls back to Lessons.number."""
        with app.app_context():
            l1 = _make_lesson(db_session, test_module, number=50, order=None)
            l2 = _make_lesson(db_session, test_module, number=51, order=None)

            # Patch order to None after creation (model default may set it)
            l1.order = None
            l2.order = None
            db_session.commit()

            result = get_next_lesson(l1.id)
            assert result is not None
            assert result.id == l2.id

    def test_next_lesson_is_in_same_module(self, app, db_session, test_level):
        """get_next_lesson never crosses module boundaries."""
        with app.app_context():
            m1 = _make_module(db_session, test_level, number=10)
            m2 = _make_module(db_session, test_level, number=11)

            l_m1 = _make_lesson(db_session, m1, number=1, order=0)
            l_m2 = _make_lesson(db_session, m2, number=1, order=0)  # same order, different module

            result = get_next_lesson(l_m1.id)
            # Should return None or only a lesson within m1
            assert result is None or result.module_id == m1.id


# ---------------------------------------------------------------------------
# CEFR level calculation
# ---------------------------------------------------------------------------

class TestGetUserCurrentCEFRLevel:
    """Tests for get_user_current_cefr_level() in daily_plan/level_utils.py."""

    def test_returns_a0_for_new_user_no_onboarding(self, app, db_session, test_user):
        """New user with no progress and no onboarding_level returns 'A0'."""
        with app.app_context():
            from app.utils.db import db as _db
            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == 'A0'

    def test_returns_onboarding_level_when_no_progress(self, app, db_session, test_user):
        """User with onboarding_level but no lesson progress returns onboarding level."""
        with app.app_context():
            from app.utils.db import db as _db

            # Create a known CEFR level and set user's onboarding_level
            level_code = uuid.uuid4().hex[:2].upper()
            level = CEFRLevel(code=level_code, name='Test Level', order=3)
            db_session.add(level)
            test_user.onboarding_level = level_code
            db_session.commit()

            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == level_code

    def test_returns_progress_based_level_when_lessons_completed(self, app, db_session, test_user, test_level):
        """Returns the highest CEFR level from completed lessons."""
        with app.app_context():
            from app.utils.db import db as _db

            module = _make_module(db_session, test_level, number=60)
            lesson = _make_lesson(db_session, module, number=60)
            _complete_lesson(db_session, test_user, lesson)

            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == test_level.code

    def test_returns_higher_of_progress_vs_onboarding(self, app, db_session, test_user):
        """Returns whichever level (progress vs onboarding) has higher CEFRLevel.order."""
        with app.app_context():
            from app.utils.db import db as _db

            low_code = uuid.uuid4().hex[:2].upper()
            high_code = uuid.uuid4().hex[:2].upper()
            low_level = CEFRLevel(code=low_code, name='Low', order=1)
            high_level = CEFRLevel(code=high_code, name='High', order=5)
            db_session.add_all([low_level, high_level])
            db_session.commit()

            # User has completed a lesson at the low level
            module = _make_module(db_session, low_level, number=70)
            lesson = _make_lesson(db_session, module, number=70)
            _complete_lesson(db_session, test_user, lesson)

            # User's onboarding_level is the high level
            test_user.onboarding_level = high_code
            db_session.commit()

            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == high_code

    def test_progress_wins_over_lower_onboarding(self, app, db_session, test_user):
        """Progress-based level wins when it has a higher order than onboarding_level."""
        with app.app_context():
            from app.utils.db import db as _db

            low_code = uuid.uuid4().hex[:2].upper()
            high_code = uuid.uuid4().hex[:2].upper()
            low_level = CEFRLevel(code=low_code, name='Low2', order=1)
            high_level = CEFRLevel(code=high_code, name='High2', order=5)
            db_session.add_all([low_level, high_level])
            db_session.commit()

            # User completed a lesson at high level
            module = _make_module(db_session, high_level, number=80)
            lesson = _make_lesson(db_session, module, number=80)
            _complete_lesson(db_session, test_user, lesson)

            # Onboarding level is lower
            test_user.onboarding_level = low_code
            db_session.commit()

            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == high_code

    def test_nonexistent_onboarding_level_falls_back_to_a0(self, app, db_session, test_user):
        """If onboarding_level references a non-existent CEFRLevel, falls back to 'A0'."""
        with app.app_context():
            from app.utils.db import db as _db

            test_user.onboarding_level = 'ZZ'  # does not exist in DB
            db_session.commit()

            result = get_user_current_cefr_level(test_user.id, _db)
            assert result == 'A0'


# ---------------------------------------------------------------------------
# Module.check_prerequisites
# ---------------------------------------------------------------------------

class TestModuleCheckPrerequisites:
    """Tests for Module.check_prerequisites() — module-level prerequisite logic."""

    def test_no_prerequisites_always_accessible(self, app, db_session, test_user, test_level):
        """Module with no prerequisites is always accessible."""
        with app.app_context():
            module = _make_module(db_session, test_level, number=90)
            module.prerequisites = None
            db_session.commit()

            accessible, reasons = module.check_prerequisites(test_user.id)
            assert accessible is True
            assert reasons == []

    def test_prerequisites_met_when_prereq_module_completed(self, app, db_session, test_user, test_level):
        """Prerequisites are met when user has completed the required module."""
        with app.app_context():
            prereq_module = _make_module(db_session, test_level, number=91)
            target_module = _make_module(db_session, test_level, number=92)

            prereq_lesson = _make_lesson(db_session, prereq_module, number=91)
            _complete_lesson(db_session, test_user, prereq_lesson, score=80.0)

            target_module.prerequisites = [
                {'type': 'module', 'id': prereq_module.id, 'min_score': 70}
            ]
            db_session.commit()

            accessible, reasons = target_module.check_prerequisites(test_user.id)
            assert accessible is True
            assert reasons == []

    def test_prerequisites_not_met_when_prereq_module_incomplete(self, app, db_session, test_user, test_level):
        """Prerequisites are not met if user hasn't completed the required module."""
        with app.app_context():
            prereq_module = _make_module(db_session, test_level, number=93)
            target_module = _make_module(db_session, test_level, number=94)

            # Add a lesson to prereq_module but don't complete it
            _make_lesson(db_session, prereq_module, number=93)

            target_module.prerequisites = [
                {'type': 'module', 'id': prereq_module.id, 'min_score': 70}
            ]
            db_session.commit()

            accessible, reasons = target_module.check_prerequisites(test_user.id)
            assert accessible is False
            assert len(reasons) > 0

    def test_prerequisites_not_met_when_score_below_threshold(self, app, db_session, test_user, test_level):
        """Prerequisites are not met if completed score is below min_score."""
        with app.app_context():
            prereq_module = _make_module(db_session, test_level, number=95)
            target_module = _make_module(db_session, test_level, number=96)

            prereq_lesson = _make_lesson(db_session, prereq_module, number=95)
            _complete_lesson(db_session, test_user, prereq_lesson, score=50.0)  # below 70

            target_module.prerequisites = [
                {'type': 'module', 'id': prereq_module.id, 'min_score': 70}
            ]
            db_session.commit()

            accessible, reasons = target_module.check_prerequisites(test_user.id)
            assert accessible is False
            assert len(reasons) > 0


# ---------------------------------------------------------------------------
# complete_lesson XP idempotency (Task 7 integration)
# ---------------------------------------------------------------------------

class TestCompleteLessonXPIdempotent:
    """Calling complete_lesson twice on the same day must not duplicate XP."""

    def test_second_same_day_call_does_not_duplicate_xp(
        self, app, db_session, test_user, test_lesson_vocabulary
    ):
        from datetime import date as _date

        from app.achievements.models import StreakEvent, UserStatistics
        from app.curriculum.xp import CURRICULUM_LESSON_EVENT_TYPE

        with app.app_context():
            progress1 = complete_lesson(test_user.id, test_lesson_vocabulary.id, score=90.0)
            assert progress1 is not None

            stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
            assert stats is not None
            xp_after_first = int(stats.total_xp or 0)
            assert xp_after_first > 0

            progress2 = complete_lesson(test_user.id, test_lesson_vocabulary.id, score=95.0)
            assert progress2 is not None

            db_session.refresh(stats)
            assert int(stats.total_xp or 0) == xp_after_first

            events = (
                StreakEvent.query.filter_by(
                    user_id=test_user.id,
                    event_type=CURRICULUM_LESSON_EVENT_TYPE,
                    event_date=_date.today(),
                )
                .filter(
                    StreakEvent.details['lesson_id'].astext
                    == str(test_lesson_vocabulary.id)
                )
                .all()
            )
            assert len(events) == 1
