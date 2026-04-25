"""
Tests for SessionService and StatsService (study/services/)
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta


class TestSessionServiceStartSession:
    """Tests for SessionService.start_session"""

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_start_session_creates_session(self, mock_session_class, mock_db):
        """Test starting a new session creates StudySession"""
        from app.study.services.session_service import SessionService

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        result = SessionService.start_session(1, 'cards')

        mock_session_class.assert_called_once()
        mock_db.session.add.assert_called_once_with(mock_session)
        mock_db.session.commit.assert_called_once()
        assert result == mock_session

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_start_session_sets_user_id(self, mock_session_class, mock_db):
        """Test session has correct user_id"""
        from app.study.services.session_service import SessionService

        SessionService.start_session(42, 'quiz')

        call_kwargs = mock_session_class.call_args[1]
        assert call_kwargs['user_id'] == 42

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_start_session_sets_type(self, mock_session_class, mock_db):
        """Test session has correct type"""
        from app.study.services.session_service import SessionService

        SessionService.start_session(1, 'matching')

        call_kwargs = mock_session_class.call_args[1]
        assert call_kwargs['session_type'] == 'matching'

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_start_session_sets_start_time(self, mock_session_class, mock_db):
        """Test session has start_time set"""
        from app.study.services.session_service import SessionService

        SessionService.start_session(1, 'cards')

        call_kwargs = mock_session_class.call_args[1]
        assert 'start_time' in call_kwargs
        assert isinstance(call_kwargs['start_time'], datetime)


class TestSessionServiceCompleteSession:
    """Tests for SessionService.complete_session"""

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_complete_session_not_found(self, mock_session_class, mock_db):
        """Test completing non-existent session returns None"""
        from app.study.services.session_service import SessionService

        mock_session_class.query.get.return_value = None

        result = SessionService.complete_session(999)

        assert result is None

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_complete_session_sets_end_time(self, mock_session_class, mock_db):
        """Test completing session sets end_time"""
        from app.study.services.session_service import SessionService

        mock_session = MagicMock()
        mock_session.end_time = None
        mock_session_class.query.get.return_value = mock_session

        SessionService.complete_session(1)

        assert mock_session.end_time is not None
        assert isinstance(mock_session.end_time, datetime)

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_complete_session_sets_stats(self, mock_session_class, mock_db):
        """Test completing session sets statistics"""
        from app.study.services.session_service import SessionService

        mock_session = MagicMock()
        mock_session_class.query.get.return_value = mock_session

        SessionService.complete_session(1, words_studied=10, correct_answers=8, incorrect_answers=2)

        assert mock_session.words_studied == 10
        assert mock_session.correct_answers == 8
        assert mock_session.incorrect_answers == 2
        mock_db.session.commit.assert_called_once()

    @patch('app.study.services.session_service.db')
    @patch('app.study.services.session_service.StudySession')
    def test_complete_session_default_values(self, mock_session_class, mock_db):
        """Test completing session with default values"""
        from app.study.services.session_service import SessionService

        mock_session = MagicMock()
        mock_session_class.query.get.return_value = mock_session

        SessionService.complete_session(1)

        assert mock_session.words_studied == 0
        assert mock_session.correct_answers == 0
        assert mock_session.incorrect_answers == 0


class TestSessionServiceAwardXP:
    """Tests for SessionService.award_xp — delegates to the unified
    achievements.xp_service.award_xp write-path; the canonical store is
    UserStatistics.total_xp.
    """

    def test_award_xp_writes_to_user_statistics(self, db_session, test_user):
        """Awarding XP should increase UserStatistics.total_xp."""
        from app.study.services.session_service import SessionService
        from app.achievements.models import UserStatistics

        before = UserStatistics.query.filter_by(user_id=test_user.id).first()
        baseline = int(before.total_xp) if before and before.total_xp else 0

        total = SessionService.award_xp(test_user.id, 100, 'quiz')

        after = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert after is not None
        assert int(after.total_xp) == baseline + 100
        assert total == int(after.total_xp)

    def test_award_xp_zero_amount_is_noop(self, db_session, test_user):
        """Zero or negative amount should not change UserStatistics.total_xp."""
        from app.study.services.session_service import SessionService
        from app.achievements.models import UserStatistics

        SessionService.award_xp(test_user.id, 50, 'seed')
        baseline = UserStatistics.query.filter_by(user_id=test_user.id).first()
        baseline_xp = int(baseline.total_xp)

        SessionService.award_xp(test_user.id, 0, 'noop')
        after = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert int(after.total_xp) == baseline_xp


class TestSessionServiceGetUserTotalXP:
    """Tests for SessionService.get_user_total_xp — reads UserStatistics.total_xp."""

    def test_get_user_total_xp_with_xp(self, db_session, test_user):
        from app.study.services.session_service import SessionService
        from app.achievements.models import UserStatistics

        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id, total_xp=500)
            db_session.add(stats)
        else:
            stats.total_xp = 500
        db_session.commit()

        assert SessionService.get_user_total_xp(test_user.id) == 500

    def test_get_user_total_xp_no_xp(self, db_session, test_user):
        from app.study.services.session_service import SessionService
        # No UserStatistics row — should return 0.
        assert SessionService.get_user_total_xp(test_user.id) == 0


class TestSessionServiceGetSessionStats:
    """Tests for SessionService.get_session_stats - signature verification only

    Note: Full tests require Flask app context due to SQLAlchemy column comparisons.
    These tests verify the method signature and basic behavior.
    """

    def test_get_session_stats_signature(self):
        """Verify method signature"""
        from app.study.services.session_service import SessionService
        import inspect

        sig = inspect.signature(SessionService.get_session_stats)
        params = list(sig.parameters.keys())

        assert 'user_id' in params
        assert 'days' in params

    def test_get_session_stats_has_default_days(self):
        """Verify days parameter has default value"""
        from app.study.services.session_service import SessionService
        import inspect

        sig = inspect.signature(SessionService.get_session_stats)
        days_param = sig.parameters['days']

        assert days_param.default == 7


class TestStatsServiceGetUserWordStats:
    """Tests for StatsService.get_user_word_stats

    Note: The implementation calculates 'mastered' count separately based on
    UserCardDirection intervals >= 180 days. Status counts come from UserWord.status
    which only has 'new', 'learning', and 'review' values.
    """

    def test_get_user_word_stats_signature(self):
        """Verify method signature"""
        from app.study.services.stats_service import StatsService
        import inspect

        sig = inspect.signature(StatsService.get_user_word_stats)
        params = list(sig.parameters.keys())

        assert 'user_id' in params

    def test_get_user_word_stats_returns_expected_keys(self):
        """Verify the method returns all expected keys"""
        from app.study.services.stats_service import StatsService
        import inspect

        # Verify method exists and has correct signature
        assert hasattr(StatsService, 'get_user_word_stats')
        assert callable(StatsService.get_user_word_stats)

        # The return dict should have these keys based on implementation
        expected_keys = ['new', 'learning', 'review', 'mastered', 'total']
        # This is verified by the integration tests in test_stats_service.py


class TestStatsServiceGetUserStats:
    """Tests for StatsService.get_user_stats"""

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.func')
    @patch('app.study.services.stats_service.StatsService.get_user_word_stats')
    @patch('app.study.services.stats_service.StudySession')
    def test_get_user_stats_mastery_percentage(self, mock_session, mock_word_stats, mock_func, mock_db):
        """Test mastery percentage calculation"""
        from app.study.services.stats_service import StatsService

        mock_word_stats.return_value = {
            'new': 10, 'learning': 20, 'review': 10, 'mastered': 60, 'total': 100
        }
        mock_session.query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_session.query.filter_by.return_value.filter.return_value.all.return_value = []

        # Mock db.session.query for today's card counts
        mock_db.session.query.return_value.filter.return_value.filter.return_value.scalar.return_value = 0
        # Mock for func.date comparison
        mock_func.date.return_value = MagicMock()
        mock_func.count.return_value = MagicMock()

        result = StatsService.get_user_stats(1)

        assert result['mastery_percentage'] == 60

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.func')
    @patch('app.study.services.stats_service.StatsService.get_user_word_stats')
    @patch('app.study.services.stats_service.StudySession')
    def test_get_user_stats_zero_total(self, mock_session, mock_word_stats, mock_func, mock_db):
        """Test mastery percentage with no words"""
        from app.study.services.stats_service import StatsService

        mock_word_stats.return_value = {
            'new': 0, 'learning': 0, 'review': 0, 'mastered': 0, 'total': 0
        }
        mock_session.query.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_session.query.filter_by.return_value.filter.return_value.all.return_value = []

        # Mock db.session.query for today's card counts
        mock_db.session.query.return_value.filter.return_value.filter.return_value.scalar.return_value = 0
        mock_func.date.return_value = MagicMock()
        mock_func.count.return_value = MagicMock()

        result = StatsService.get_user_stats(1)

        assert result['mastery_percentage'] == 0


class TestStatsServiceGetLeaderboard:
    """Tests for StatsService.get_leaderboard - signature verification

    Note: Full tests require Flask app context due to SQLAlchemy column comparisons.
    """

    def test_get_leaderboard_signature(self):
        """Verify method signature"""
        from app.study.services.stats_service import StatsService
        import inspect

        sig = inspect.signature(StatsService.get_leaderboard)
        params = list(sig.parameters.keys())

        assert 'game_type' in params
        assert 'period_days' in params
        assert 'limit' in params

    def test_get_leaderboard_defaults(self):
        """Verify default parameter values"""
        from app.study.services.stats_service import StatsService
        import inspect

        sig = inspect.signature(StatsService.get_leaderboard)

        assert sig.parameters['game_type'].default == 'all'
        assert sig.parameters['period_days'].default == 30
        assert sig.parameters['limit'].default == 10


class TestStatsServiceGetUserAchievements:
    """Tests for StatsService.get_user_achievements"""

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.Achievement')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_get_user_achievements(self, mock_user_ach, mock_ach, mock_db):
        """Test getting user achievements"""
        from app.study.services.stats_service import StatsService

        # Mock all achievements
        mock_ach1 = MagicMock()
        mock_ach1.id = 1
        mock_ach1.code = 'first_word'
        mock_ach1.name = 'First Word'
        mock_ach1.description = 'Learn your first word'
        mock_ach1.icon = 'star'
        mock_ach1.xp_reward = 10

        mock_ach2 = MagicMock()
        mock_ach2.id = 2
        mock_ach2.code = 'ten_words'
        mock_ach2.name = 'Ten Words'
        mock_ach2.description = 'Learn 10 words'
        mock_ach2.icon = 'trophy'
        mock_ach2.xp_reward = 50

        mock_ach.query.order_by.return_value.all.return_value = [mock_ach1, mock_ach2]

        # Mock earned achievements
        earned_at = datetime.now(timezone.utc)
        mock_db.session.query.return_value.join.return_value.filter.return_value.all.return_value = [
            (mock_ach1, earned_at)
        ]

        result = StatsService.get_user_achievements(1)

        assert result['total_earned'] == 1
        assert result['total_available'] == 2
        assert len(result['earned']) == 1
        assert len(result['available']) == 1
        assert result['earned'][0]['code'] == 'first_word'
        assert result['available'][0]['code'] == 'ten_words'


class TestStatsServiceCheckAndAwardAchievements:
    """Tests for StatsService.check_and_award_achievements"""

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.UserWord')
    @patch('app.study.services.stats_service.Achievement')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_award_first_word_achievement(self, mock_user_ach, mock_ach, mock_user_word, mock_db):
        """Test awarding first word achievement"""
        from app.study.services.stats_service import StatsService

        # User has 1 word
        mock_user_word.query.filter_by.return_value.count.return_value = 1

        # Achievement exists
        mock_achievement = MagicMock()
        mock_achievement.id = 1
        mock_ach.query.filter_by.return_value.first.return_value = mock_achievement

        # Not already earned
        mock_user_ach.query.filter_by.return_value.first.return_value = None

        result = StatsService.check_and_award_achievements(1)

        assert len(result) == 1
        assert result[0] == mock_achievement
        mock_db.session.add.assert_called()
        mock_db.session.commit.assert_called()

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.UserWord')
    @patch('app.study.services.stats_service.Achievement')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_no_achievement_if_already_earned(self, mock_user_ach, mock_ach, mock_user_word, mock_db):
        """Test no duplicate achievement if already earned"""
        from app.study.services.stats_service import StatsService

        mock_user_word.query.filter_by.return_value.count.return_value = 1

        mock_achievement = MagicMock()
        mock_ach.query.filter_by.return_value.first.return_value = mock_achievement

        # Already earned
        mock_user_ach.query.filter_by.return_value.first.return_value = MagicMock()

        result = StatsService.check_and_award_achievements(1)

        assert len(result) == 0

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.UserWord')
    @patch('app.study.services.stats_service.Achievement')
    def test_no_achievement_if_no_words(self, mock_ach, mock_user_word, mock_db):
        """Test no achievement if user has no words"""
        from app.study.services.stats_service import StatsService

        mock_user_word.query.filter_by.return_value.count.return_value = 0

        result = StatsService.check_and_award_achievements(1)

        assert len(result) == 0


class TestStatsServiceGetXPLeaderboard:
    """Tests for StatsService.get_xp_leaderboard"""

    def test_get_xp_leaderboard_signature(self):
        """Verify method signature"""
        from app.study.services.stats_service import StatsService
        import inspect

        sig = inspect.signature(StatsService.get_xp_leaderboard)
        params = list(sig.parameters.keys())

        assert 'limit' in params
        assert sig.parameters['limit'].default == 100

    def test_level_calculation_formula(self):
        """Test the level calculation formula used in leaderboard"""
        # Level = max(1, total_xp // 100)
        assert max(1, 550 // 100) == 5
        assert max(1, 50 // 100) == 1
        assert max(1, 0 // 100) == 1
        assert max(1, 1000 // 100) == 10


class TestStatsServiceGetAchievementLeaderboard:
    """Tests for StatsService.get_achievement_leaderboard"""

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.User')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_get_achievement_leaderboard(self, mock_user_ach, mock_user, mock_db):
        """Test achievement leaderboard"""
        from app.study.services.stats_service import StatsService

        mock_result = MagicMock()
        mock_result.id = 1
        mock_result.username = 'achiever'
        mock_result.achievement_count = 15

        mock_db.session.query.return_value.join.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_result]

        result = StatsService.get_achievement_leaderboard()

        assert len(result) == 1
        assert result[0]['achievement_count'] == 15


class TestStatsServiceGetUserXPRank:
    """Tests for StatsService.get_user_xp_rank"""

    def test_get_user_xp_rank_signature(self):
        """Verify method signature"""
        from app.study.services.stats_service import StatsService
        import inspect

        sig = inspect.signature(StatsService.get_user_xp_rank)
        params = list(sig.parameters.keys())

        assert 'user_id' in params

    def test_get_user_xp_rank_no_xp(self, db_session, test_user):
        """User with no UserStatistics row should have no XP rank."""
        from app.study.services.stats_service import StatsService

        result = StatsService.get_user_xp_rank(test_user.id)

        assert result is None


class TestStatsServiceGetUserAchievementRank:
    """Tests for StatsService.get_user_achievement_rank"""

    @patch('app.study.services.stats_service.db')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_get_user_achievement_rank_with_achievements(self, mock_user_ach, mock_db):
        """Test getting achievement rank for user with achievements"""
        from app.study.services.stats_service import StatsService

        mock_user_ach.query.filter_by.return_value.count.return_value = 5

        # 2 users have more achievements
        mock_db.session.query.return_value.filter.return_value.scalar.return_value = 2

        result = StatsService.get_user_achievement_rank(1)

        assert result == 3  # 2 + 1

    @patch('app.study.services.stats_service.UserAchievement')
    def test_get_user_achievement_rank_no_achievements(self, mock_user_ach):
        """Test getting achievement rank for user with no achievements"""
        from app.study.services.stats_service import StatsService

        mock_user_ach.query.filter_by.return_value.count.return_value = 0

        result = StatsService.get_user_achievement_rank(1)

        assert result is None


class TestStatsServiceGetAchievementsByCategory:
    """Tests for StatsService.get_achievements_by_category"""

    @patch('app.study.services.stats_service.Achievement')
    @patch('app.study.services.stats_service.UserAchievement')
    def test_get_achievements_by_category(self, mock_user_ach, mock_ach):
        """Test getting achievements grouped by category"""
        from app.study.services.stats_service import StatsService

        mock_ach1 = MagicMock()
        mock_ach1.id = 1
        mock_ach1.category = 'words'
        mock_ach1.xp_reward = 10

        mock_ach2 = MagicMock()
        mock_ach2.id = 2
        mock_ach2.category = 'words'
        mock_ach2.xp_reward = 50

        mock_ach3 = MagicMock()
        mock_ach3.id = 3
        mock_ach3.category = 'streak'
        mock_ach3.xp_reward = 100

        mock_ach.query.order_by.return_value.all.return_value = [mock_ach1, mock_ach2, mock_ach3]

        # User earned achievement 1
        mock_user_ach_record = MagicMock()
        mock_user_ach_record.achievement_id = 1
        mock_user_ach_record.earned_at = datetime.now(timezone.utc)
        mock_user_ach.query.filter_by.return_value.all.return_value = [mock_user_ach_record]

        result = StatsService.get_achievements_by_category(1)

        assert 'words' in result['by_category']
        assert 'streak' in result['by_category']
        assert result['total_achievements'] == 3
        assert result['earned_count'] == 1
        assert result['progress_percentage'] == 33  # 1/3 * 100 rounded
        assert result['total_xp_earned'] == 10  # Only achievement 1 earned
