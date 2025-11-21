"""Tests for ProgressService"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from app.curriculum.services.progress_service import ProgressService


@pytest.fixture
def mock_level():
    """Create mock CEFR level"""
    level = Mock()
    level.id = 1
    level.code = 'A1'
    level.order = 1
    return level


@pytest.fixture
def mock_module():
    """Create mock module"""
    module = Mock()
    module.id = 1
    module.number = 1
    module.level_id = 1
    return module


@pytest.fixture
def mock_lesson():
    """Create mock lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.module_id = 1
    lesson.order = 1
    lesson.number = 1
    return lesson


class TestGetUserLevelProgress:
    """Test get_user_level_progress method"""

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.CEFRLevel')
    @patch('app.curriculum.services.progress_service.Module')
    def test_no_lessons_returns_zero_progress(self, mock_module_model, mock_level_model, mock_session, mock_level):
        """Test with no lessons"""
        mock_level_model.query.order_by.return_value.all.return_value = [mock_level]
        mock_module_model.query.filter_by.return_value.all.return_value = []

        result = ProgressService.get_user_level_progress(1)

        assert result[1]['total_lessons'] == 0
        assert result[1]['completed_lessons'] == 0
        assert result[1]['percentage'] == 0

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.CEFRLevel')
    @patch('app.curriculum.services.progress_service.Module')
    def test_calculates_progress_percentage(self, mock_module_model, mock_level_model, mock_session, mock_level, mock_module):
        """Test percentage calculation"""
        mock_level_model.query.order_by.return_value.all.return_value = [mock_level]
        mock_module_model.query.filter_by.return_value.all.return_value = [mock_module]

        # Mock stats: 10 total, 7 completed, 2 in_progress
        stats = Mock(total=10, completed=7, in_progress=2)
        mock_session.query.return_value.select_from.return_value.outerjoin.return_value.filter.return_value.first.return_value = stats

        result = ProgressService.get_user_level_progress(1)

        assert result[1]['total_lessons'] == 10
        assert result[1]['completed_lessons'] == 7
        assert result[1]['in_progress_lessons'] == 2
        assert result[1]['percentage'] == 70

    @patch('app.curriculum.services.progress_service.CEFRLevel')
    def test_handles_exceptions(self, mock_level_model):
        """Test exception handling"""
        mock_level_model.query.order_by.side_effect = Exception('Database error')

        result = ProgressService.get_user_level_progress(1)

        assert result == {}


class TestGetActiveLessons:
    """Test get_active_lessons method"""

    @patch('app.curriculum.services.progress_service.db.session')
    def test_returns_active_lessons(self, mock_session):
        """Test returns lessons in progress"""
        progress = Mock()
        progress.lesson = Mock(id=1)
        progress.lesson.module = Mock(id=1)
        progress.lesson.module.level = Mock(code='A1')
        progress.last_activity = datetime.now(UTC)
        progress.score = 75.0

        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [progress]

        result = ProgressService.get_active_lessons(1, limit=5)

        assert len(result) == 1
        assert result[0]['lesson'] == progress.lesson
        assert result[0]['score'] == 75.0

    @patch('app.curriculum.services.progress_service.db.session')
    def test_respects_limit(self, mock_session):
        """Test limit parameter"""
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        ProgressService.get_active_lessons(1, limit=3)

        mock_query.filter.return_value.order_by.return_value.limit.assert_called_with(3)

    @patch('app.curriculum.services.progress_service.db.session')
    def test_handles_exceptions(self, mock_session):
        """Test exception handling"""
        mock_session.query.side_effect = Exception('Database error')

        result = ProgressService.get_active_lessons(1)

        assert result == []


class TestGetRecommendedLevel:
    """Test get_recommended_level method"""

    @patch('app.curriculum.services.progress_service.ProgressService.get_user_level_progress')
    @patch('app.curriculum.services.progress_service.CEFRLevel')
    def test_returns_first_incomplete_level(self, mock_level_model, mock_get_progress):
        """Test returns level with <80% completion"""
        level1 = Mock(id=1, code='A1', order=1)
        level2 = Mock(id=2, code='A2', order=2)
        mock_level_model.query.order_by.return_value.all.return_value = [level1, level2]

        mock_get_progress.return_value = {
            1: {'percentage': 95},  # A1 completed
            2: {'percentage': 60}   # A2 incomplete
        }

        result = ProgressService.get_recommended_level(1)

        assert result == level2

    @patch('app.curriculum.services.progress_service.ProgressService.get_user_level_progress')
    @patch('app.curriculum.services.progress_service.CEFRLevel')
    def test_returns_highest_level_when_all_complete(self, mock_level_model, mock_get_progress):
        """Test returns last level when all completed"""
        level1 = Mock(id=1, code='A1', order=1)
        level2 = Mock(id=2, code='A2', order=2)
        mock_level_model.query.order_by.return_value.all.return_value = [level1, level2]

        mock_get_progress.return_value = {
            1: {'percentage': 100},
            2: {'percentage': 90}
        }

        result = ProgressService.get_recommended_level(1)

        assert result == level2


class TestCreateOrUpdateProgress:
    """Test create_or_update_progress method"""

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.LessonProgress')
    def test_creates_new_progress(self, mock_progress_model, mock_session):
        """Test creating new progress record"""
        mock_progress_model.query.filter_by.return_value.first.return_value = None

        new_progress = Mock()
        mock_progress_model.return_value = new_progress

        result = ProgressService.create_or_update_progress(
            user_id=1,
            lesson_id=1,
            status='in_progress',
            score=85.0
        )

        assert result == new_progress
        mock_session.add.assert_called_once_with(new_progress)
        mock_session.commit.assert_called_once()

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.LessonProgress')
    def test_updates_existing_progress(self, mock_progress_model, mock_session):
        """Test updating existing progress"""
        existing_progress = Mock()
        existing_progress.completed_at = None
        mock_progress_model.query.filter_by.return_value.first.return_value = existing_progress

        result = ProgressService.create_or_update_progress(
            user_id=1,
            lesson_id=1,
            status='completed',
            score=92.5
        )

        assert existing_progress.status == 'completed'
        assert existing_progress.score == 92.5
        assert existing_progress.completed_at is not None

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.LessonProgress')
    def test_handles_data_parameter(self, mock_progress_model, mock_session):
        """Test storing additional data"""
        existing_progress = Mock()
        mock_progress_model.query.filter_by.return_value.first.return_value = existing_progress

        data = {'answers': {0: 1, 1: 2}, 'time_spent': 120}

        ProgressService.create_or_update_progress(
            user_id=1,
            lesson_id=1,
            data=data
        )

        assert existing_progress.data == data

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.LessonProgress')
    def test_rolls_back_on_error(self, mock_progress_model, mock_session):
        """Test rollback on database error"""
        mock_progress_model.query.filter_by.return_value.first.return_value = None
        mock_session.commit.side_effect = Exception('Database error')

        with pytest.raises(Exception):
            ProgressService.create_or_update_progress(1, 1)

        mock_session.rollback.assert_called_once()


class TestGetModuleProgress:
    """Test get_module_progress method"""

    @patch('app.curriculum.services.progress_service.db.session')
    def test_calculates_module_statistics(self, mock_session):
        """Test module progress calculation"""
        lesson1 = Mock()
        progress1 = Mock(status='completed', score=90.0)

        lesson2 = Mock()
        progress2 = Mock(status='completed', score=80.0)

        lesson3 = Mock()
        progress3 = Mock(status='in_progress', score=None)

        mock_session.query.return_value.outerjoin.return_value.filter.return_value.order_by.return_value.all.return_value = [
            (lesson1, progress1),
            (lesson2, progress2),
            (lesson3, progress3)
        ]

        result = ProgressService.get_module_progress(1, 1)

        assert result['total_lessons'] == 3
        assert result['completed_lessons'] == 2
        assert result['in_progress_lessons'] == 1
        assert result['percentage'] == 67  # 2/3 * 100
        assert result['average_score'] == 85.0  # (90 + 80) / 2

    @patch('app.curriculum.services.progress_service.db.session')
    def test_handles_no_progress(self, mock_session):
        """Test with no progress data"""
        lesson1 = Mock()
        lesson2 = Mock()

        mock_session.query.return_value.outerjoin.return_value.filter.return_value.order_by.return_value.all.return_value = [
            (lesson1, None),
            (lesson2, None)
        ]

        result = ProgressService.get_module_progress(1, 1)

        assert result['total_lessons'] == 2
        assert result['completed_lessons'] == 0
        assert result['average_score'] == 0


class TestCanAccessNextModule:
    """Test can_access_next_module method"""

    @patch('app.curriculum.services.progress_service.ProgressService.get_module_progress')
    @patch('app.curriculum.services.progress_service.Module')
    def test_allows_access_with_80_percent(self, mock_module_model, mock_get_progress):
        """Test access allowed at 80% completion"""
        mock_module_model.query.get.return_value = Mock(id=1)
        mock_get_progress.return_value = {'percentage': 80}

        result = ProgressService.can_access_next_module(1, 1)

        assert result is True

    @patch('app.curriculum.services.progress_service.ProgressService.get_module_progress')
    @patch('app.curriculum.services.progress_service.Module')
    def test_denies_access_below_80_percent(self, mock_module_model, mock_get_progress):
        """Test access denied below 80%"""
        mock_module_model.query.get.return_value = Mock(id=1)
        mock_get_progress.return_value = {'percentage': 75}

        result = ProgressService.can_access_next_module(1, 1)

        assert result is False

    @patch('app.curriculum.services.progress_service.Module')
    def test_returns_false_for_nonexistent_module(self, mock_module_model):
        """Test with module not found"""
        mock_module_model.query.get.return_value = None

        result = ProgressService.can_access_next_module(1, 999)

        assert result is False


class TestGetLearningStreak:
    """Test get_learning_streak method"""

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.datetime')
    def test_calculates_consecutive_days(self, mock_datetime, mock_session):
        """Test streak calculation"""
        today = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC).date()
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        # 5 consecutive days including today
        dates = [
            (today,),
            (today - timedelta(days=1),),
            (today - timedelta(days=2),),
            (today - timedelta(days=3),),
            (today - timedelta(days=4),)
        ]
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = dates

        result = ProgressService.get_learning_streak(1)

        assert result == 5

    @patch('app.curriculum.services.progress_service.db.session')
    @patch('app.curriculum.services.progress_service.datetime')
    def test_broken_streak_returns_partial(self, mock_datetime, mock_session):
        """Test broken streak"""
        today = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC).date()
        mock_datetime.now.return_value = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        # Gap in dates - streak broken
        dates = [
            (today,),
            (today - timedelta(days=1),),
            (today - timedelta(days=3),),  # Gap!
            (today - timedelta(days=4),)
        ]
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = dates

        result = ProgressService.get_learning_streak(1)

        assert result == 2  # Only today and yesterday

    @patch('app.curriculum.services.progress_service.db.session')
    def test_no_activity_returns_zero(self, mock_session):
        """Test with no activity"""
        mock_session.query.return_value.filter.return_value.distinct.return_value.order_by.return_value.all.return_value = []

        result = ProgressService.get_learning_streak(1)

        assert result == 0


class TestGetNextLesson:
    """Test get_next_lesson method"""

    @patch('app.curriculum.services.progress_service.Lessons')
    def test_returns_none_for_nonexistent_lesson(self, mock_lessons_model):
        """Test with non-existent lesson"""
        mock_lessons_model.query.get.return_value = None

        result = ProgressService.get_next_lesson(999)

        assert result is None

    @patch('app.curriculum.services.progress_service.Lessons')
    def test_handles_exceptions(self, mock_lessons_model):
        """Test exception handling"""
        mock_lessons_model.query.get.side_effect = Exception('Database error')

        result = ProgressService.get_next_lesson(1)

        assert result is None
