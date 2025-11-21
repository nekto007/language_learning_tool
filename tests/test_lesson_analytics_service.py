"""Tests for LessonAnalyticsService"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from app.curriculum.services.lesson_analytics_service import LessonAnalyticsService


@pytest.fixture
def mock_lesson():
    """Create mock lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.type = 'quiz'
    lesson.title = 'Test Lesson'
    return lesson


@pytest.fixture
def mock_module():
    """Create mock module"""
    module = Mock()
    module.id = 1
    module.title = 'Test Module'
    return module


class TestGetLessonStats:
    """Test get_lesson_stats method"""

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    def test_lesson_not_found(self, mock_session, mock_lessons):
        """Test with non-existent lesson"""
        mock_lessons.query.get.return_value = None

        result = LessonAnalyticsService.get_lesson_stats(999)

        assert result == {}

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    @patch.object(LessonAnalyticsService, '_analyze_common_mistakes')
    def test_lesson_with_no_attempts(self, mock_mistakes, mock_session, mock_lessons, mock_lesson):
        """Test lesson with zero attempts"""
        mock_lessons.query.get.return_value = mock_lesson
        mock_mistakes.return_value = []

        # Mock stats query
        stats = Mock()
        stats.total_attempts = 0
        stats.unique_users = 0
        stats.avg_score = None
        stats.avg_time = None
        stats.passed_count = 0

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = stats
        mock_session.query.return_value = mock_query

        # Mock retry stats
        mock_query.filter.return_value.group_by.return_value.having.return_value.all.return_value = []

        result = LessonAnalyticsService.get_lesson_stats(1)

        assert result['total_attempts'] == 0
        assert result['unique_users'] == 0
        assert result['avg_score'] == 0.0
        assert result['pass_rate'] == 0.0

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    @patch.object(LessonAnalyticsService, '_analyze_common_mistakes')
    def test_lesson_with_attempts(self, mock_mistakes, mock_session, mock_lessons, mock_lesson):
        """Test lesson with attempts"""
        mock_lessons.query.get.return_value = mock_lesson
        mock_mistakes.return_value = []

        # Mock stats
        stats = Mock()
        stats.total_attempts = 10
        stats.unique_users = 5
        stats.avg_score = 85.5
        stats.avg_time = 300  # 5 minutes
        stats.passed_count = 8

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = stats
        mock_session.query.return_value = mock_query

        # Mock retry stats
        mock_query.filter.return_value.group_by.return_value.having.return_value.all.return_value = [
            (1, 2), (2, 3)  # 2 users with retries
        ]

        result = LessonAnalyticsService.get_lesson_stats(1)

        assert result['total_attempts'] == 10
        assert result['unique_users'] == 5
        assert result['avg_score'] == 85.5
        assert result['avg_time_minutes'] == 5.0
        assert result['pass_rate'] == 80.0
        assert result['retry_rate'] == 40.0  # 2/5 * 100
        assert result['avg_attempts_per_user'] == 2.0  # 10/5

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    def test_handles_exceptions(self, mock_session, mock_lessons):
        """Test exception handling"""
        mock_lessons.query.get.side_effect = Exception('Database error')

        result = LessonAnalyticsService.get_lesson_stats(1)

        assert result == {}


class TestAnalyzeCommonMistakes:
    """Test _analyze_common_mistakes method"""

    @patch('app.curriculum.services.lesson_analytics_service.LessonAttempt')
    def test_no_attempts(self, mock_attempt):
        """Test with no attempts"""
        mock_attempt.query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = LessonAnalyticsService._analyze_common_mistakes(1, limit=5)

        assert result == []

    @patch('app.curriculum.services.lesson_analytics_service.LessonAttempt')
    def test_analyzes_mistakes(self, mock_attempt):
        """Test mistake analysis"""
        # Create mock attempts with mistakes
        attempt1 = Mock()
        attempt1.mistakes = [
            {'question_id': 'q1', 'question_text': 'Question 1'},
            {'question_id': 'q2', 'question_text': 'Question 2'}
        ]

        attempt2 = Mock()
        attempt2.mistakes = [
            {'question_id': 'q1', 'question_text': 'Question 1'},
            {'question_id': 'q1', 'question_text': 'Question 1'}
        ]

        mock_attempt.query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            attempt1, attempt2
        ]

        result = LessonAnalyticsService._analyze_common_mistakes(1, limit=5)

        assert len(result) == 2
        # q1 should be first (3 mistakes)
        assert result[0]['question_id'] == 'q1'
        assert result[0]['count'] == 3

    @patch('app.curriculum.services.lesson_analytics_service.LessonAttempt')
    def test_handles_none_mistakes(self, mock_attempt):
        """Test with None mistakes"""
        attempt = Mock()
        attempt.mistakes = None

        mock_attempt.query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [attempt]

        result = LessonAnalyticsService._analyze_common_mistakes(1)

        assert result == []


class TestGetModuleStats:
    """Test get_module_stats method"""

    @patch('app.curriculum.services.lesson_analytics_service.Module')
    def test_module_not_found(self, mock_module_cls):
        """Test with non-existent module"""
        mock_module_cls.query.get.return_value = None

        result = LessonAnalyticsService.get_module_stats(999)

        assert result == {}

    @patch('app.curriculum.services.lesson_analytics_service.Module')
    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    @patch.object(LessonAnalyticsService, '_find_drop_off_points')
    def test_module_stats(self, mock_drop_off, mock_session, mock_lessons_cls, mock_module_cls, mock_module):
        """Test module statistics"""
        mock_module_cls.query.get.return_value = mock_module

        # Mock lessons
        lesson1 = Mock()
        lesson1.id = 1
        lesson2 = Mock()
        lesson2.id = 2
        mock_lessons_cls.query.filter_by.return_value.all.return_value = [lesson1, lesson2]

        # Mock stats
        stats = Mock()
        stats.total_attempts = 20
        stats.unique_users = 10
        stats.avg_score = 80.0
        stats.avg_time = 600

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = stats
        mock_session.query.return_value = mock_query

        # Mock completion
        mock_query.join.return_value.filter.return_value.group_by.return_value.having.return_value.scalar.return_value = 5

        mock_drop_off.return_value = []

        result = LessonAnalyticsService.get_module_stats(1)

        assert result['total_lessons'] == 2
        assert result['total_attempts'] == 20
        assert result['unique_users'] == 10
        assert result['completion_rate'] == 50.0  # 5/10


class TestGetUserPerformance:
    """Test get_user_performance method"""

    @patch('app.curriculum.services.lesson_analytics_service.LessonAttempt')
    def test_no_attempts(self, mock_attempt):
        """Test user with no attempts"""
        mock_attempt.query.filter.return_value.all.return_value = []

        result = LessonAnalyticsService.get_user_performance(1)

        assert result['total_attempts'] == 0
        assert result['avg_score'] == 0
        assert result['pass_rate'] == 0

    @patch('app.curriculum.services.lesson_analytics_service.LessonAttempt')
    def test_user_performance(self, mock_attempt):
        """Test user performance calculation"""
        # Create mock attempts
        attempt1 = Mock()
        attempt1.passed = True
        attempt1.score = 90
        attempt1.time_spent_seconds = 300
        attempt1.lesson = Mock(type='quiz')

        attempt2 = Mock()
        attempt2.passed = False
        attempt2.score = 60
        attempt2.time_spent_seconds = 200
        attempt2.lesson = Mock(type='vocabulary')

        mock_attempt.query.filter.return_value.all.return_value = [attempt1, attempt2]

        result = LessonAnalyticsService.get_user_performance(1)

        assert result['total_attempts'] == 2
        assert result['avg_score'] == 75.0  # (90 + 60) / 2
        assert result['pass_rate'] == 50.0  # 1/2 * 100
        assert result['avg_time_minutes'] == 4.2  # (300 + 200) / 2 / 60
        assert 'by_type' in result


class TestGetSystemHealth:
    """Test get_system_health method"""

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    @patch('app.curriculum.services.lesson_analytics_service.datetime')
    def test_system_health(self, mock_datetime, mock_session, mock_lessons):
        """Test system health metrics"""
        # Mock current time
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        # Mock recent attempts stats
        recent_stats = Mock()
        recent_stats.total = 100
        recent_stats.active_users = 20
        recent_stats.avg_score = 75.0
        recent_stats.passed = 80

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = recent_stats
        mock_session.query.return_value = mock_query

        # Mock problematic lessons
        problem_row = Mock()
        problem_row.lesson_id = 1
        problem_row.attempts = 10
        problem_row.avg_score = 40.0
        problem_row.passed = 3

        mock_query.filter.return_value.group_by.return_value.having.return_value.all.return_value = [problem_row]
        mock_lessons.query.get.return_value = Mock(id=1, title='Problem Lesson')

        result = LessonAnalyticsService.get_system_health()

        assert result['last_7_days']['total_attempts'] == 100
        assert result['last_7_days']['active_users'] == 20
        assert result['last_7_days']['pass_rate'] == 80.0
        assert len(result['problem_lessons']) == 1


class TestGenerateAlerts:
    """Test generate_alerts method"""

    @patch.object(LessonAnalyticsService, 'get_system_health')
    def test_low_pass_rate_alert(self, mock_health):
        """Test alert for low pass rate"""
        mock_health.return_value = {
            'last_7_days': {
                'pass_rate': 50.0,
                'active_users': 10
            },
            'alert_count': 2,
            'problem_lessons': []
        }

        alerts = LessonAnalyticsService.generate_alerts()

        assert len(alerts) > 0
        assert any(a['type'] == 'low_pass_rate' for a in alerts)
        assert any(a['severity'] == 'high' for a in alerts)

    @patch.object(LessonAnalyticsService, 'get_system_health')
    def test_multiple_problem_lessons_alert(self, mock_health):
        """Test alert for multiple problem lessons"""
        mock_health.return_value = {
            'last_7_days': {
                'pass_rate': 80.0,
                'active_users': 10
            },
            'alert_count': 5,
            'problem_lessons': [
                {'lesson': Mock(), 'pass_rate': 30},
                {'lesson': Mock(), 'pass_rate': 40},
                {'lesson': Mock(), 'pass_rate': 45}
            ]
        }

        alerts = LessonAnalyticsService.generate_alerts()

        assert any(a['type'] == 'multiple_problem_lessons' for a in alerts)

    @patch.object(LessonAnalyticsService, 'get_system_health')
    def test_low_activity_alert(self, mock_health):
        """Test alert for low activity"""
        mock_health.return_value = {
            'last_7_days': {
                'pass_rate': 80.0,
                'active_users': 3
            },
            'alert_count': 0,
            'problem_lessons': []
        }

        alerts = LessonAnalyticsService.generate_alerts()

        assert any(a['type'] == 'low_activity' for a in alerts)
        assert any(a['severity'] == 'low' for a in alerts)

    @patch.object(LessonAnalyticsService, 'get_system_health')
    def test_no_alerts_when_healthy(self, mock_health):
        """Test no alerts when system is healthy"""
        mock_health.return_value = {
            'last_7_days': {
                'pass_rate': 85.0,
                'active_users': 50
            },
            'alert_count': 1,
            'problem_lessons': []
        }

        alerts = LessonAnalyticsService.generate_alerts()

        # Should have very few or no alerts
        assert len(alerts) <= 1

    @patch.object(LessonAnalyticsService, 'get_system_health')
    def test_handles_exceptions(self, mock_health):
        """Test exception handling in alert generation"""
        mock_health.side_effect = Exception('Database error')

        alerts = LessonAnalyticsService.generate_alerts()

        # Should return empty list instead of crashing
        assert alerts == []


class TestFindDropOffPoints:
    """Test _find_drop_off_points method"""

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    def test_finds_high_abandonment(self, mock_session, mock_lessons):
        """Test finding lessons with high abandonment"""
        lesson1 = Mock()
        lesson1.id = 1
        lesson1.title = 'Easy Lesson'

        lesson2 = Mock()
        lesson2.id = 2
        lesson2.title = 'Hard Lesson'

        mock_lessons.query.filter_by.return_value.order_by.return_value.all.return_value = [lesson1, lesson2]

        # Mock queries for lesson 1 (low abandonment)
        # Mock queries for lesson 2 (high abandonment)
        mock_query = MagicMock()
        mock_query.filter.return_value.scalar.side_effect = [
            10, 9,  # lesson 1: 10 started, 9 completed (10% abandonment)
            10, 5   # lesson 2: 10 started, 5 completed (50% abandonment)
        ]
        mock_session.query.return_value = mock_query

        result = LessonAnalyticsService._find_drop_off_points(1)

        # Should only return lesson 2 (>30% abandonment)
        assert len(result) == 1
        assert result[0]['abandonment_rate'] == 50.0

    @patch('app.curriculum.services.lesson_analytics_service.Lessons')
    @patch('app.curriculum.services.lesson_analytics_service.db.session')
    def test_handles_no_drop_offs(self, mock_session, mock_lessons):
        """Test when no lessons have high abandonment"""
        lesson = Mock()
        lesson.id = 1

        mock_lessons.query.filter_by.return_value.order_by.return_value.all.return_value = [lesson]

        mock_query = MagicMock()
        mock_query.filter.return_value.scalar.side_effect = [10, 9]  # 10% abandonment
        mock_session.query.return_value = mock_query

        result = LessonAnalyticsService._find_drop_off_points(1)

        assert result == []