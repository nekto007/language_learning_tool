"""Tests for CurriculumCacheService"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from app.curriculum.services.curriculum_cache_service import CurriculumCacheService


@pytest.fixture
def mock_level():
    """Create mock CEFR level"""
    level = Mock()
    level.id = 1
    level.code = 'A1'
    level.order = 1
    level.modules = []
    return level


@pytest.fixture
def mock_module():
    """Create mock module"""
    module = Mock()
    module.id = 1
    module.number = 1
    module.lessons = []
    return module


@pytest.fixture
def mock_lesson():
    """Create mock lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.number = 1
    lesson.module = Mock()
    return lesson


class TestGetLevelsWithProgress:
    """Test get_levels_with_progress method"""

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_no_levels_returns_empty_list(self, mock_session):
        """Test with no levels in database"""
        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = []

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert result == []

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_basic_level_with_no_progress(self, mock_session, mock_level, mock_module, mock_lesson):
        """Test level without any user progress"""
        mock_lesson.id = 1
        mock_module.lessons = [mock_lesson]
        mock_module.number = 1
        mock_level.modules = [mock_module]

        # Mock query chain for levels
        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]

        # Mock progress query - no progress
        mock_session.query.return_value.filter.return_value.all.return_value = []

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert len(result) == 1
        assert result[0]['level'] == mock_level
        assert result[0]['total_lessons'] == 1
        assert result[0]['completed_lessons'] == 0
        assert result[0]['progress_percent'] == 0

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_level_with_completed_lessons(self, mock_session, mock_level, mock_module, mock_lesson):
        """Test level with completed lessons"""
        mock_lesson.id = 1
        mock_module.lessons = [mock_lesson]
        mock_module.number = 1
        mock_level.modules = [mock_module]

        # Mock query chain
        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]

        # Mock progress with completed status
        progress = Mock()
        progress.lesson_id = 1
        progress.status = 'completed'
        mock_session.query.return_value.filter.return_value.all.return_value = [progress]

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert result[0]['completed_lessons'] == 1
        assert result[0]['progress_percent'] == 100

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_module_availability_logic(self, mock_session, mock_level):
        """Test module availability based on previous module completion"""
        # Create two modules
        mod1 = Mock()
        mod1.id = 1
        mod1.number = 1
        lesson1 = Mock(id=1, number=1)
        mod1.lessons = [lesson1]

        mod2 = Mock()
        mod2.id = 2
        mod2.number = 2
        lesson2 = Mock(id=2, number=1)
        mod2.lessons = [lesson2]

        mock_level.modules = [mod1, mod2]

        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]

        # First module completed 50% - should lock second module
        progress = Mock()
        progress.lesson_id = 1
        progress.status = 'in_progress'
        mock_session.query.return_value.filter.return_value.all.return_value = [progress]

        result = CurriculumCacheService.get_levels_with_progress(1)

        # Second module should not be available (< 80% completion of first)
        assert result[0]['modules'][1]['is_available'] is False

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_lesson_status_determination(self, mock_session, mock_level, mock_module):
        """Test lesson status calculation"""
        lesson1 = Mock(id=1, number=1)
        lesson2 = Mock(id=2, number=2)
        lesson3 = Mock(id=3, number=3)

        mock_module.lessons = [lesson1, lesson2, lesson3]
        mock_module.number = 1
        mock_level.modules = [mock_module]

        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]

        # Lesson 1 completed, lesson 2 in progress, lesson 3 not started
        prog1 = Mock(lesson_id=1, status='completed')
        prog2 = Mock(lesson_id=2, status='in_progress')

        mock_session.query.return_value.filter.return_value.all.return_value = [prog1, prog2]

        result = CurriculumCacheService.get_levels_with_progress(1)

        lessons = result[0]['modules'][0]['lessons']
        assert lessons[0]['status'] == 'completed'
        assert lessons[1]['status'] == 'in_progress'
        assert lessons[2]['status'] == 'available'  # Next after in_progress

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_estimated_time_calculation(self, mock_session, mock_level, mock_module):
        """Test estimated time calculation"""
        # 10 lessons, 15 minutes each = 150 minutes = 2.5 hours
        lessons = [Mock(id=i, number=i) for i in range(1, 11)]
        mock_module.lessons = lessons
        mock_module.number = 1
        mock_level.modules = [mock_module]

        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]
        mock_session.query.return_value.filter.return_value.all.return_value = []

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert result[0]['estimated_hours'] == 2.5

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_next_lesson_identification(self, mock_session, mock_level, mock_module):
        """Test finding next available lesson"""
        lesson1 = Mock(id=1, number=1)
        lesson2 = Mock(id=2, number=2)
        lesson3 = Mock(id=3, number=3)

        mock_module.lessons = [lesson1, lesson2, lesson3]
        mock_module.number = 1
        mock_level.modules = [mock_module]

        mock_session.query.return_value.options.return_value.order_by.return_value.all.return_value = [mock_level]

        # First two lessons completed
        prog1 = Mock(lesson_id=1, status='completed')
        prog2 = Mock(lesson_id=2, status='completed')
        mock_session.query.return_value.filter.return_value.all.return_value = [prog1, prog2]

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert result[0]['next_lesson'] == lesson3

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_handles_exceptions(self, mock_session):
        """Test exception handling"""
        mock_session.query.side_effect = Exception('Database error')

        result = CurriculumCacheService.get_levels_with_progress(1)

        assert result == []


class TestGetRecentActivity:
    """Test get_recent_activity method"""

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_no_activity_returns_empty_list(self, mock_session):
        """Test with no recent activity"""
        mock_session.query.return_value.options.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = CurriculumCacheService.get_recent_activity(1, limit=5)

        assert result == []

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_returns_recent_activity(self, mock_session):
        """Test returns recent activity with joined data"""
        # Create mock progress with nested relationships
        progress = Mock()
        progress.lesson = Mock()
        progress.lesson.module = Mock()
        progress.lesson.module.level = Mock()
        progress.status = 'completed'
        progress.score = 85.0
        progress.last_activity = datetime.now(UTC)

        mock_session.query.return_value.options.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [progress]

        result = CurriculumCacheService.get_recent_activity(1, limit=5)

        assert len(result) == 1
        assert result[0]['lesson'] == progress.lesson
        assert result[0]['status'] == 'completed'
        assert result[0]['score'] == 85.0

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_respects_limit_parameter(self, mock_session):
        """Test that limit parameter is used"""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.options.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        CurriculumCacheService.get_recent_activity(1, limit=3)

        # Verify limit was called with 3
        mock_query.options.return_value.filter.return_value.order_by.return_value.limit.assert_called_with(3)


class TestGetGamificationStats:
    """Test get_gamification_stats method"""

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    @patch('app.curriculum.services.curriculum_cache_service.datetime')
    def test_zero_activity_returns_defaults(self, mock_datetime, mock_session):
        """Test with no activity"""
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        # No activity dates
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = []

        # No completed lessons
        mock_session.query.return_value.filter.return_value.first.return_value = (0, 0)
        mock_session.query.return_value.filter.return_value.scalar.return_value = 0

        result = CurriculumCacheService.get_gamification_stats(1)

        assert result['streak'] == 0
        assert result['total_points'] == 0
        assert result['user_level'] == 1
        assert result['completed_lessons'] == 0

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    @patch('app.curriculum.services.curriculum_cache_service.datetime')
    def test_calculates_streak_correctly(self, mock_datetime, mock_session):
        """Test streak calculation"""
        current = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC).date()
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        # 5 consecutive days including today
        dates = [
            (current,),
            (current - timedelta(days=1),),
            (current - timedelta(days=2),),
            (current - timedelta(days=3),),
            (current - timedelta(days=4),)
        ]
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = dates

        mock_session.query.return_value.filter.return_value.first.return_value = (10, 80.0)
        mock_session.query.return_value.filter.return_value.scalar.return_value = 2

        result = CurriculumCacheService.get_gamification_stats(1)

        assert result['streak'] == 5

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    @patch('app.curriculum.services.curriculum_cache_service.datetime')
    def test_calculates_points_with_high_score(self, mock_datetime, mock_session):
        """Test points calculation with high average score"""
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = []

        # 10 completed lessons with 90% average
        mock_session.query.return_value.filter.return_value.first.return_value = (10, 90.0)
        mock_session.query.return_value.filter.return_value.scalar.return_value = 0

        result = CurriculumCacheService.get_gamification_stats(1)

        # 10 * 10 base + 10 * 5 bonus = 150 points
        assert result['total_points'] == 150
        assert result['user_level'] == 2  # 1 + (150 // 100)

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    @patch('app.curriculum.services.curriculum_cache_service.datetime')
    def test_daily_progress_tracking(self, mock_datetime, mock_session):
        """Test daily progress tracking"""
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = []
        mock_session.query.return_value.filter.return_value.first.return_value = (10, 80.0)

        # 2 lessons completed today
        mock_session.query.return_value.filter.return_value.scalar.return_value = 2

        result = CurriculumCacheService.get_gamification_stats(1)

        assert result['daily_progress'] == 2
        assert result['daily_goal'] == 3

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_handles_exceptions_gracefully(self, mock_session):
        """Test exception handling returns defaults"""
        mock_session.query.side_effect = Exception('Database error')

        result = CurriculumCacheService.get_gamification_stats(1)

        assert result['streak'] == 0
        assert result['total_points'] == 0
        assert result['user_level'] == 1


class TestGetLevelWithModules:
    """Test get_level_with_modules method"""

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_level_not_found_returns_none(self, mock_session):
        """Test with non-existent level"""
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = None

        result = CurriculumCacheService.get_level_with_modules(999, 1)

        assert result is None

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_returns_level_with_progress_map(self, mock_session, mock_level, mock_module, mock_lesson):
        """Test returns level data with progress map"""
        mock_lesson.id = 1
        mock_module.lessons = [mock_lesson]
        mock_level.modules = [mock_module]

        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_level

        # Progress for lesson
        progress = Mock(lesson_id=1, status='completed')
        mock_query_progress = MagicMock()
        mock_session.query.return_value = mock_query_progress
        mock_query_progress.filter.return_value.all.return_value = [progress]

        result = CurriculumCacheService.get_level_with_modules(1, 1)

        assert result['level'] == mock_level
        assert 1 in result['progress_map']
        assert result['progress_map'][1] == progress

    @patch('app.curriculum.services.curriculum_cache_service.db.session')
    def test_handles_exceptions(self, mock_session):
        """Test exception handling"""
        mock_session.query.side_effect = Exception('Database error')

        result = CurriculumCacheService.get_level_with_modules(1, 1)

        assert result is None