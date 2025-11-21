"""Tests for ProgressService"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from app.curriculum.services.progress_service_unified import ProgressService


@pytest.fixture
def mock_lesson():
    """Create mock lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.type = 'quiz'
    lesson.title = 'Test Quiz'
    return lesson


class TestAwardLessonXP:
    """Test award_lesson_xp method"""

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_excellent_score_multiplier(self, mock_session, mock_user_xp, mock_lesson):
        """Test XP award with excellent score (90-100)"""
        user_xp = Mock()
        user_xp.total_xp = 100
        mock_user_xp.get_or_create.return_value = user_xp

        mock_lesson.type = 'quiz'
        xp_earned = ProgressService.award_lesson_xp(1, mock_lesson, 95)

        # quiz = 20 base XP, excellent = 2.0 multiplier = 40 XP
        assert xp_earned == 40
        assert user_xp.total_xp == 140

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_good_score_multiplier(self, mock_session, mock_user_xp, mock_lesson):
        """Test XP award with good score (80-89)"""
        user_xp = Mock()
        user_xp.total_xp = 100
        mock_user_xp.get_or_create.return_value = user_xp

        mock_lesson.type = 'quiz'
        xp_earned = ProgressService.award_lesson_xp(1, mock_lesson, 85)

        # quiz = 20 base XP, good = 1.5 multiplier = 30 XP
        assert xp_earned == 30

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_pass_score_multiplier(self, mock_session, mock_user_xp, mock_lesson):
        """Test XP award with passing score (70-79)"""
        user_xp = Mock()
        user_xp.total_xp = 100
        mock_user_xp.get_or_create.return_value = user_xp

        mock_lesson.type = 'quiz'
        xp_earned = ProgressService.award_lesson_xp(1, mock_lesson, 75)

        # quiz = 20 base XP, pass = 1.0 multiplier = 20 XP
        assert xp_earned == 20

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_retry_score_multiplier(self, mock_session, mock_user_xp, mock_lesson):
        """Test XP award with retry score (<70)"""
        user_xp = Mock()
        user_xp.total_xp = 100
        mock_user_xp.get_or_create.return_value = user_xp

        mock_lesson.type = 'quiz'
        xp_earned = ProgressService.award_lesson_xp(1, mock_lesson, 50)

        # quiz = 20 base XP, retry = 0.5 multiplier = 10 XP
        assert xp_earned == 10

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_different_lesson_types(self, mock_session, mock_user_xp, mock_lesson):
        """Test different base XP for different lesson types"""
        user_xp = Mock()
        user_xp.total_xp = 0
        mock_user_xp.get_or_create.return_value = user_xp

        # Test vocabulary (10 base XP)
        mock_lesson.type = 'vocabulary'
        assert ProgressService.award_lesson_xp(1, mock_lesson, 90) == 20  # 10 * 2.0

        # Test grammar (15 base XP)
        mock_lesson.type = 'grammar'
        assert ProgressService.award_lesson_xp(1, mock_lesson, 90) == 30  # 15 * 2.0

        # Test final_test (50 base XP)
        mock_lesson.type = 'final_test'
        assert ProgressService.award_lesson_xp(1, mock_lesson, 90) == 100  # 50 * 2.0

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_handles_exceptions(self, mock_session, mock_user_xp, mock_lesson):
        """Test exception handling"""
        mock_user_xp.get_or_create.side_effect = Exception('Database error')

        xp_earned = ProgressService.award_lesson_xp(1, mock_lesson, 90)

        assert xp_earned == 0
        mock_session.rollback.assert_called_once()


class TestUpdateLessonProgress:
    """Test update_lesson_progress method"""

    @patch('app.curriculum.services.progress_service_unified.Lessons')
    @patch('app.curriculum.services.progress_service_unified.LessonProgress')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_create_new_progress(self, mock_session, mock_progress_cls, mock_lessons):
        """Test creating new progress record"""
        mock_progress_cls.query.filter_by.return_value.first.return_value = None

        result = ProgressService.update_lesson_progress(1, 1, 'in_progress')

        assert result is not None
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch('app.curriculum.services.progress_service_unified.Lessons')
    @patch('app.curriculum.services.progress_service_unified.LessonProgress')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_update_existing_progress(self, mock_session, mock_progress_cls, mock_lessons):
        """Test updating existing progress"""
        existing_progress = Mock()
        existing_progress.status = 'in_progress'
        existing_progress.score = None
        mock_progress_cls.query.filter_by.return_value.first.return_value = existing_progress

        result = ProgressService.update_lesson_progress(1, 1, 'completed', score=85.0)

        assert result.status == 'completed'
        existing_progress.set_score.assert_called_with(85.0)

    @patch.object(ProgressService, 'award_lesson_xp')
    @patch('app.curriculum.services.progress_service_unified.Lessons')
    @patch('app.curriculum.services.progress_service_unified.LessonProgress')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_awards_xp_on_completion(self, mock_session, mock_progress_cls, mock_lessons, mock_award_xp):
        """Test XP is awarded when lesson is completed"""
        existing_progress = Mock()
        existing_progress.status = 'in_progress'
        existing_progress.score = 90.0
        existing_progress.data = {}
        mock_progress_cls.query.filter_by.return_value.first.return_value = existing_progress

        lesson = Mock()
        lesson.id = 1
        mock_lessons.query.get.return_value = lesson
        mock_award_xp.return_value = 40

        result = ProgressService.update_lesson_progress(1, 1, 'completed', score=90.0)

        mock_award_xp.assert_called_once_with(1, lesson, 90.0)
        assert result.data['xp_earned'] == 40

    @patch('app.curriculum.services.progress_service_unified.Lessons')
    @patch('app.curriculum.services.progress_service_unified.LessonProgress')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_no_xp_on_re_completion(self, mock_session, mock_progress_cls, mock_lessons):
        """Test XP is not awarded when already completed"""
        existing_progress = Mock()
        existing_progress.status = 'completed'  # Already completed
        existing_progress.score = 80.0
        mock_progress_cls.query.filter_by.return_value.first.return_value = existing_progress

        result = ProgressService.update_lesson_progress(1, 1, 'completed', score=90.0)

        # Should not have completed_at updated again
        assert not hasattr(result, 'completed_at') or result.completed_at is None


class TestGetUserStats:
    """Test get_user_stats method"""

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    @patch.object(ProgressService, '_calculate_streak')
    @patch.object(ProgressService, '_get_record_streak')
    def test_user_stats(self, mock_record, mock_streak, mock_session, mock_user_xp):
        """Test getting comprehensive user stats"""
        user_xp = Mock()
        user_xp.total_xp = 250
        user_xp.level = 3
        mock_user_xp.get_or_create.return_value = user_xp

        # Mock lesson stats
        stats = Mock()
        stats.total_lessons = 10
        stats.completed_lessons = 7
        stats.avg_score = 85.5
        mock_session.query.return_value.filter.return_value.first.return_value = stats

        mock_streak.return_value = 5
        mock_record.return_value = 10

        result = ProgressService.get_user_stats(1)

        assert result['xp']['total'] == 250
        assert result['xp']['level'] == 3
        assert result['lessons']['total_started'] == 10
        assert result['lessons']['completed'] == 7
        assert result['lessons']['completion_rate'] == 70.0
        assert result['streak']['current'] == 5
        assert result['streak']['record'] == 10

    @patch('app.curriculum.services.progress_service_unified.UserXP')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_handles_exceptions_gracefully(self, mock_session, mock_user_xp):
        """Test returns default stats on error"""
        mock_user_xp.get_or_create.side_effect = Exception('Database error')

        result = ProgressService.get_user_stats(1)

        # Should return default values, not crash
        assert result['xp']['total'] == 0
        assert result['xp']['level'] == 1
        assert result['lessons']['completed'] == 0


class TestGetLevelProgress:
    """Test get_level_progress method"""

    @patch('app.curriculum.services.progress_service_unified.CEFRLevel')
    def test_level_not_found(self, mock_level):
        """Test with non-existent level"""
        mock_level.query.get.return_value = None

        result = ProgressService.get_level_progress(1, 999)

        assert result == {}

    @patch('app.curriculum.services.progress_service_unified.CEFRLevel')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_level_with_no_lessons(self, mock_session, mock_level):
        """Test level with no lessons"""
        level = Mock()
        level.id = 1
        mock_level.query.get.return_value = level

        mock_session.query.return_value.join.return_value.filter.return_value.all.return_value = []

        result = ProgressService.get_level_progress(1, 1)

        assert result['total_lessons'] == 0
        assert result['progress_percent'] == 0

    @patch('app.curriculum.services.progress_service_unified.CEFRLevel')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_level_progress_calculation(self, mock_session, mock_level):
        """Test progress calculation for level"""
        level = Mock()
        level.id = 1
        mock_level.query.get.return_value = level

        # Mock lesson IDs
        mock_query = MagicMock()
        mock_query.join.return_value.filter.return_value.all.return_value = [(1,), (2,), (3,), (4,), (5,)]
        mock_session.query.return_value = mock_query

        # Mock progress stats
        progress_stats = Mock()
        progress_stats.completed = 3
        mock_query.filter.return_value.first.return_value = progress_stats

        result = ProgressService.get_level_progress(1, 1)

        assert result['total_lessons'] == 5
        assert result['completed_lessons'] == 3
        assert result['progress_percent'] == 60  # 3/5 * 100


class TestGetModuleProgress:
    """Test get_module_progress method"""

    @patch('app.curriculum.services.progress_service_unified.Module')
    def test_module_not_found(self, mock_module):
        """Test with non-existent module"""
        mock_module.query.get.return_value = None

        result = ProgressService.get_module_progress(1, 999)

        assert result == {}

    @patch('app.curriculum.services.progress_service_unified.Module')
    @patch('app.curriculum.services.progress_service_unified.Lessons')
    @patch('app.curriculum.services.progress_service_unified.db.session')
    def test_module_progress(self, mock_session, mock_lessons, mock_module_cls):
        """Test module progress calculation"""
        module = Mock()
        module.id = 1
        mock_module_cls.query.get.return_value = module

        # Mock lessons
        lesson1 = Mock(id=1)
        lesson2 = Mock(id=2)
        lesson3 = Mock(id=3)
        mock_lessons.query.filter_by.return_value.all.return_value = [lesson1, lesson2, lesson3]

        # Mock progress stats
        progress_stats = Mock()
        progress_stats.completed = 2
        mock_session.query.return_value.filter.return_value.first.return_value = progress_stats

        result = ProgressService.get_module_progress(1, 1)

        assert result['total_lessons'] == 3
        assert result['completed_lessons'] == 2
        assert result['progress_percent'] == 67  # 2/3 * 100 rounded


class TestCalculateStreak:
    """Test _calculate_streak method"""

    @patch('app.curriculum.services.progress_service_unified.db.session')
    @patch('app.curriculum.services.progress_service_unified.datetime')
    def test_no_activity(self, mock_datetime, mock_session):
        """Test streak with no activity"""
        now = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = []

        result = ProgressService._calculate_streak(1)

        assert result == 0

    @patch('app.curriculum.services.progress_service_unified.db.session')
    @patch('app.curriculum.services.progress_service_unified.datetime')
    def test_consecutive_days_streak(self, mock_datetime, mock_session):
        """Test streak with consecutive days"""
        current = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC).date()
        mock_datetime.now.return_value = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)

        # Mock activity for last 5 days
        dates = [
            (current,),
            (current - timedelta(days=1),),
            (current - timedelta(days=2),),
            (current - timedelta(days=3),),
            (current - timedelta(days=4),)
        ]
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = dates

        result = ProgressService._calculate_streak(1)

        assert result == 5

    @patch('app.curriculum.services.progress_service_unified.db.session')
    @patch('app.curriculum.services.progress_service_unified.datetime')
    def test_broken_streak(self, mock_datetime, mock_session):
        """Test streak with gap in activity"""
        current = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC).date()
        mock_datetime.now.return_value = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)

        # Mock activity with gap
        dates = [
            (current,),
            (current - timedelta(days=1),),
            # Gap here
            (current - timedelta(days=5),)
        ]
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = dates

        result = ProgressService._calculate_streak(1)

        assert result == 2  # Only counts consecutive days


class TestGetRecordStreak:
    """Test _get_record_streak method"""

    @patch.object(ProgressService, '_calculate_streak')
    def test_returns_current_streak(self, mock_calculate):
        """Test returns current streak (TODO: implement record tracking)"""
        mock_calculate.return_value = 7

        result = ProgressService._get_record_streak(1)

        assert result == 7
