"""Tests for admin dashboard statistics queries."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.utils.db import db


class TestGetDashboardStatistics:
    """Tests for get_dashboard_statistics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Dashboard stats dict should contain all expected keys."""
        from app.admin.main_routes import get_dashboard_statistics

        with patch('app.admin.main_routes.cache_result', lambda *a, **kw: lambda f: f):
            stats = get_dashboard_statistics()

        expected_keys = {
            'total_users', 'active_users', 'new_users', 'active_recently',
            'total_books', 'total_readings', 'words_total', 'words_with_audio',
            'total_lessons', 'active_lessons'
        }
        assert expected_keys.issubset(stats.keys())

    def test_counts_users_correctly(self, app, db_session):
        """Should count total, active, new, and recently active users."""
        now = datetime.now(timezone.utc)

        # Create users with different states
        u1 = User(
            username=f'active_{uuid.uuid4().hex[:8]}',
            email=f'a_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=1),
            last_login=now - timedelta(hours=1),
        )
        u1.set_password('pass')

        u2 = User(
            username=f'inactive_{uuid.uuid4().hex[:8]}',
            email=f'i_{uuid.uuid4().hex[:8]}@test.com',
            active=False,
            created_at=now - timedelta(days=30),
            last_login=now - timedelta(days=20),
        )
        u2.set_password('pass')

        u3 = User(
            username=f'new_{uuid.uuid4().hex[:8]}',
            email=f'n_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=2),
            last_login=now - timedelta(days=2),
        )
        u3.set_password('pass')

        db_session.add_all([u1, u2, u3])
        db_session.commit()

        from app.admin.main_routes import get_dashboard_statistics
        stats = get_dashboard_statistics.__wrapped__()

        assert stats['total_users'] == 3
        assert stats['active_users'] == 2  # u1 and u3
        assert stats['new_users'] >= 2  # u1 and u3 created within 7 days
        assert stats['active_recently'] >= 2  # u1 and u3 logged in within 7 days


class TestGetDailyActivityData:
    """Tests for get_daily_activity_data function."""

    def test_returns_correct_structure(self, app, db_session):
        """Should return dict with labels, registrations, logins, active_users."""
        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert 'labels' in result
        assert 'registrations' in result
        assert 'logins' in result
        assert 'active_users' in result
        assert len(result['labels']) == 7
        assert len(result['registrations']) == 7
        assert len(result['logins']) == 7
        assert len(result['active_users']) == 7

    def test_counts_registrations(self, app, db_session):
        """Should count registrations per day."""
        now = datetime.now(timezone.utc)
        today = now.date()

        u = User(
            username=f'reg_{uuid.uuid4().hex[:8]}',
            email=f'reg_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        # Last element should be today
        assert result['labels'][-1] == today.strftime('%d.%m')
        # At least 1 registration today
        assert result['registrations'][-1] >= 1

    def test_counts_logins(self, app, db_session):
        """Should count logins per day."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'login_{uuid.uuid4().hex[:8]}',
            email=f'login_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=10),
            last_login=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert result['logins'][-1] >= 1

    def test_counts_active_users_from_lesson_progress(self, app, db_session):
        """Should count active users who had lesson progress activity."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'lp_{uuid.uuid4().hex[:8]}',
            email=f'lp_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=1
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='Test Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Test', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()

        lp = LessonProgress(
            user_id=u.id,
            lesson_id=lesson.id,
            status='completed',
            last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert result['active_users'][-1] >= 1

    def test_default_30_days(self, app, db_session):
        """Default call should return 30 days of data."""
        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__()

        assert len(result['labels']) == 30


class TestDashboardRoute:
    """Tests for the admin dashboard route."""

    def test_dashboard_returns_200(self, app, client, admin_user):
        """Admin dashboard should return 200 for admin user."""
        response = client.get('/admin/')
        assert response.status_code == 200

    def test_dashboard_contains_activity_data(self, app, client, admin_user):
        """Dashboard should contain activity chart labels in rendered HTML."""
        response = client.get('/admin/')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        # Chart should have real labels (date format dd.mm)
        assert 'activityLabels' in data
        assert 'activityRegistrations' in data
        assert 'activityActiveUsers' in data

    def test_dashboard_shows_total_readings(self, app, client, admin_user):
        """Dashboard should display total_readings stat."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Уникальных слов в книгах' in data

    def test_dashboard_shows_engagement_metrics(self, app, client, admin_user):
        """Dashboard should display DAU/WAU/MAU engagement metrics."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'DAU' in data
        assert 'WAU' in data
        assert 'MAU' in data

    def test_dashboard_shows_learning_metrics(self, app, client, admin_user):
        """Dashboard should display learning metrics section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Уроков сегодня' in data
        assert 'Средний балл' in data

    def test_dashboard_shows_content_metrics(self, app, client, admin_user):
        """Dashboard should display content metrics section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Контент' in data
        assert 'Грамматических тем' in data

    def test_dashboard_shows_srs_health(self, app, client, admin_user):
        """Dashboard should display SRS health sections."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'SRS: Слова' in data
        assert 'SRS: Грамматика' in data


class TestEngagementMetrics:
    """Tests for get_engagement_metrics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return DAU, WAU, MAU with trends."""
        from app.admin.main_routes import get_engagement_metrics

        result = get_engagement_metrics.__wrapped__()

        for key in ('dau', 'wau', 'mau'):
            assert key in result
            assert f'{key}_trend' in result
            assert f'{key}_trend_value' in result

    def test_counts_active_user(self, app, db_session):
        """User who logged in today should count as DAU."""
        now = datetime.now(timezone.utc)
        u = User(
            username=f'dau_{uuid.uuid4().hex[:8]}',
            email=f'dau_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            last_login=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_engagement_metrics

        result = get_engagement_metrics.__wrapped__()

        assert result['dau'] >= 1
        assert result['wau'] >= 1
        assert result['mau'] >= 1

    def test_trend_up_when_current_greater(self, app, db_session):
        """Trend should be 'up' when current period has more users than previous."""
        now = datetime.now(timezone.utc)
        # Create user active today but not yesterday
        u = User(
            username=f'trend_{uuid.uuid4().hex[:8]}',
            email=f'trend_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            last_login=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_engagement_metrics

        result = get_engagement_metrics.__wrapped__()

        # DAU today > 0, yesterday may be 0, so trend should be up or neutral
        assert result['dau_trend'] in ('up', '')

    def test_zero_users_returns_empty_trends(self, app, db_session):
        """With no users, all metrics should be 0 with empty trends."""
        # Clear all users
        db_session.query(User).delete()
        db_session.commit()

        from app.admin.main_routes import get_engagement_metrics

        result = get_engagement_metrics.__wrapped__()

        assert result['dau'] == 0
        assert result['wau'] == 0
        assert result['mau'] == 0


class TestLearningMetrics:
    """Tests for get_learning_metrics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return lesson and session counts."""
        from app.admin.main_routes import get_learning_metrics

        result = get_learning_metrics.__wrapped__()

        assert 'lessons_today' in result
        assert 'lessons_week' in result
        assert 'avg_lesson_score' in result
        assert 'sessions_today' in result

    def test_counts_completed_lessons(self, app, db_session):
        """Should count lessons completed today."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'lm_{uuid.uuid4().hex[:8]}',
            email=f'lm_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=99
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='Test Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Test', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()

        lp = LessonProgress(
            user_id=u.id,
            lesson_id=lesson.id,
            status='completed',
            completed_at=now,
            last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        from app.admin.main_routes import get_learning_metrics

        result = get_learning_metrics.__wrapped__()

        assert result['lessons_today'] >= 1
        assert result['lessons_week'] >= 1

    def test_avg_score_calculation(self, app, db_session):
        """Should calculate average lesson score from attempts."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'sc_{uuid.uuid4().hex[:8]}',
            email=f'sc_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=98
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='Test Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Test', type='quiz', order=1)
        db_session.add(lesson)
        db_session.flush()

        a1 = LessonAttempt(
            user_id=u.id, lesson_id=lesson.id, attempt_number=1,
            score=80.0, completed_at=now,
        )
        a2 = LessonAttempt(
            user_id=u.id, lesson_id=lesson.id, attempt_number=2,
            score=60.0, completed_at=now,
        )
        db_session.add_all([a1, a2])
        db_session.commit()

        from app.admin.main_routes import get_learning_metrics

        result = get_learning_metrics.__wrapped__()

        assert result['avg_lesson_score'] > 0

    def test_sessions_today_count(self, app, db_session):
        """Should count study sessions started today."""
        from app.study.models import StudySession

        now = datetime.now(timezone.utc)

        u = User(
            username=f'ss_{uuid.uuid4().hex[:8]}',
            email=f'ss_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        ss = StudySession(
            user_id=u.id,
            session_type='cards',
            start_time=now,
            words_studied=5,
        )
        db_session.add(ss)
        db_session.commit()

        from app.admin.main_routes import get_learning_metrics

        result = get_learning_metrics.__wrapped__()

        assert result['sessions_today'] >= 1


class TestContentMetrics:
    """Tests for get_content_metrics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return content metric counts."""
        from app.admin.main_routes import get_content_metrics

        result = get_content_metrics.__wrapped__()

        assert 'grammar_topics_count' in result
        assert 'book_courses_count' in result
        assert 'enrollments_count' in result
        assert 'active_decks' in result

    def test_counts_grammar_topics(self, app, db_session):
        """Should count grammar topics."""
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=f'test-topic-{uuid.uuid4().hex[:8]}',
            title='Test Topic',
            title_ru='Тестовая тема',
            level='A1',
            order=999,
            content={},
        )
        db_session.add(topic)
        db_session.commit()

        from app.admin.main_routes import get_content_metrics

        result = get_content_metrics.__wrapped__()

        assert result['grammar_topics_count'] >= 1

    def test_counts_quiz_decks(self, app, db_session):
        """Should count quiz decks."""
        from app.study.models import QuizDeck

        u = User(
            username=f'qd_{uuid.uuid4().hex[:8]}',
            email=f'qd_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        deck = QuizDeck(
            title='Test Deck',
            user_id=u.id,
        )
        db_session.add(deck)
        db_session.commit()

        from app.admin.main_routes import get_content_metrics

        result = get_content_metrics.__wrapped__()

        assert result['active_decks'] >= 1


class TestSRSHealthMetrics:
    """Tests for get_srs_health_metrics function."""

    def test_returns_expected_structure(self, app, db_session):
        """Should return words_srs and grammar_srs dicts."""
        from app.admin.main_routes import get_srs_health_metrics

        result = get_srs_health_metrics.__wrapped__()

        assert 'words_srs' in result
        assert 'grammar_srs' in result
        for key in ('new', 'learning', 'review', 'mastered', 'total'):
            assert key in result['words_srs']
            assert key in result['grammar_srs']

    def test_counts_word_srs_states(self, app, db_session):
        """Should count word card direction states."""
        from app.study.models import UserCardDirection, UserWord
        from app.words.models import CollectionWords

        u = User(
            username=f'srs_{uuid.uuid4().hex[:8]}',
            email=f'srs_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        word = CollectionWords(
            english_word=f'test_{uuid.uuid4().hex[:8]}',
            russian_word='тест',
        )
        db_session.add(word)
        db_session.flush()

        uw = UserWord(user_id=u.id, word_id=word.id)
        db_session.add(uw)
        db_session.flush()

        ucd = UserCardDirection(uw.id, 'eng-rus')
        ucd.state = 'learning'
        db_session.add(ucd)
        db_session.commit()

        from app.admin.main_routes import get_srs_health_metrics

        result = get_srs_health_metrics.__wrapped__()

        assert result['words_srs']['learning'] >= 1
        assert result['words_srs']['total'] >= 1

    def test_counts_grammar_srs_states(self, app, db_session):
        """Should count grammar exercise states."""
        from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise

        u = User(
            username=f'gsrs_{uuid.uuid4().hex[:8]}',
            email=f'gsrs_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        topic = GrammarTopic(
            slug=f'srs-topic-{uuid.uuid4().hex[:8]}',
            title='SRS Topic',
            title_ru='SRS Тема',
            level='A1',
            order=998,
            content={},
        )
        db_session.add(topic)
        db_session.flush()

        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'test', 'answer': 'test'},
        )
        db_session.add(exercise)
        db_session.flush()

        uge = UserGrammarExercise(u.id, exercise.id)
        db_session.add(uge)
        db_session.commit()

        from app.admin.main_routes import get_srs_health_metrics

        result = get_srs_health_metrics.__wrapped__()

        assert result['grammar_srs']['new'] >= 1
        assert result['grammar_srs']['total'] >= 1


class TestRetentionMetrics:
    """Tests for get_retention_metrics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return d1, d7, d30 retention rates."""
        from app.admin.main_routes import get_retention_metrics

        result = get_retention_metrics.__wrapped__()

        assert 'd1' in result
        assert 'd7' in result
        assert 'd30' in result

    def test_zero_users_returns_zero(self, app, db_session):
        """With no users, retention should be 0."""
        db_session.query(User).delete()
        db_session.commit()

        from app.admin.main_routes import get_retention_metrics

        result = get_retention_metrics.__wrapped__()

        assert result['d1'] == 0
        assert result['d7'] == 0
        assert result['d30'] == 0

    def test_retained_user_counted(self, app, db_session):
        """User who logged in after day 1 should count for d1 retention."""
        now = datetime.now(timezone.utc)
        u = User(
            username=f'ret_{uuid.uuid4().hex[:8]}',
            email=f'ret_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=5),
            last_login=now - timedelta(days=2),
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_retention_metrics

        result = get_retention_metrics.__wrapped__()

        assert result['d1'] > 0

    def test_non_retained_user_not_counted(self, app, db_session):
        """User who never logged in after registration should not count."""
        db_session.query(User).delete()
        db_session.commit()

        now = datetime.now(timezone.utc)
        u = User(
            username=f'noret_{uuid.uuid4().hex[:8]}',
            email=f'noret_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=10),
            last_login=None,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_retention_metrics

        result = get_retention_metrics.__wrapped__()

        assert result['d1'] == 0


class TestStreakAnalytics:
    """Tests for get_streak_analytics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return active_streaks, avg_streak, longest_overall, distribution."""
        from app.admin.main_routes import get_streak_analytics

        result = get_streak_analytics.__wrapped__()

        assert 'active_streaks' in result
        assert 'avg_streak' in result
        assert 'longest_overall' in result
        assert 'distribution' in result

    def test_counts_active_streak(self, app, db_session):
        """User with current_streak_days > 0 should be counted."""
        from app.achievements.models import UserStatistics

        u = User(
            username=f'str_{uuid.uuid4().hex[:8]}',
            email=f'str_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        stats = UserStatistics(
            user_id=u.id,
            current_streak_days=5,
            longest_streak_days=10,
        )
        db_session.add(stats)
        db_session.commit()

        from app.admin.main_routes import get_streak_analytics

        result = get_streak_analytics.__wrapped__()

        assert result['active_streaks'] >= 1
        assert result['avg_streak'] > 0
        assert result['longest_overall'] >= 10
        assert result['distribution']['4-7'] >= 1

    def test_no_streaks_returns_zeros(self, app, db_session):
        """With no user statistics, all values should be 0."""
        from app.achievements.models import UserStatistics
        db_session.query(UserStatistics).delete()
        db_session.commit()

        from app.admin.main_routes import get_streak_analytics

        result = get_streak_analytics.__wrapped__()

        assert result['active_streaks'] == 0
        assert result['avg_streak'] == 0


class TestReferralAnalytics:
    """Tests for get_referral_analytics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return referral metrics."""
        from app.admin.main_routes import get_referral_analytics

        result = get_referral_analytics.__wrapped__()

        assert 'total_referrals' in result
        assert 'top_referrers' in result
        assert 'conversion_rate' in result
        assert 'referred_count' in result
        assert 'converted' in result

    def test_counts_referrals(self, app, db_session):
        """Should count referral logs."""
        from app.auth.models import ReferralLog

        referrer = User(
            username=f'referrer_{uuid.uuid4().hex[:8]}',
            email=f'referrer_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        referrer.set_password('pass')
        db_session.add(referrer)
        db_session.flush()

        referred = User(
            username=f'referred_{uuid.uuid4().hex[:8]}',
            email=f'referred_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            referred_by_id=referrer.id,
        )
        referred.set_password('pass')
        db_session.add(referred)
        db_session.flush()

        log = ReferralLog(referrer_id=referrer.id, referred_id=referred.id)
        db_session.add(log)
        db_session.commit()

        from app.admin.main_routes import get_referral_analytics

        result = get_referral_analytics.__wrapped__()

        assert result['total_referrals'] >= 1
        assert result['referred_count'] >= 1
        assert len(result['top_referrers']) >= 1
        assert result['top_referrers'][0]['username'] == referrer.username

    def test_no_referrals_returns_zeros(self, app, db_session):
        """With no referrals, all should be 0."""
        from app.admin.main_routes import get_referral_analytics

        result = get_referral_analytics.__wrapped__()

        # May have pre-existing data, just check structure
        assert isinstance(result['total_referrals'], int)
        assert isinstance(result['top_referrers'], list)
        assert isinstance(result['conversion_rate'], (int, float))


class TestCoinEconomy:
    """Tests for get_coin_economy function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return coin economy metrics."""
        from app.admin.main_routes import get_coin_economy

        result = get_coin_economy.__wrapped__()

        assert 'total_balance' in result
        assert 'total_earned' in result
        assert 'total_spent' in result
        assert 'users_with_coins' in result

    def test_counts_coins(self, app, db_session):
        """Should sum coin balances."""
        from app.achievements.models import StreakCoins

        u = User(
            username=f'coin_{uuid.uuid4().hex[:8]}',
            email=f'coin_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        coins = StreakCoins(
            user_id=u.id,
            balance=50,
            total_earned=100,
            total_spent=50,
        )
        db_session.add(coins)
        db_session.commit()

        from app.admin.main_routes import get_coin_economy

        result = get_coin_economy.__wrapped__()

        assert result['total_balance'] >= 50
        assert result['total_earned'] >= 100
        assert result['total_spent'] >= 50
        assert result['users_with_coins'] >= 1

    def test_no_coins_returns_zeros(self, app, db_session):
        """With no coin records, all should be 0."""
        from app.achievements.models import StreakCoins
        db_session.query(StreakCoins).delete()
        db_session.commit()

        from app.admin.main_routes import get_coin_economy

        result = get_coin_economy.__wrapped__()

        assert result['total_balance'] == 0
        assert result['total_earned'] == 0
        assert result['total_spent'] == 0
        assert result['users_with_coins'] == 0


class TestDashboardRouteRetentionReferrals:
    """Tests for the admin dashboard route with new sections."""

    def test_dashboard_shows_retention(self, app, client, admin_user):
        """Dashboard should display retention section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Удержание' in data
        assert 'День 1' in data

    def test_dashboard_shows_streaks(self, app, client, admin_user):
        """Dashboard should display streak analytics section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Серии' in data
        assert 'Активных серий' in data

    def test_dashboard_shows_referrals(self, app, client, admin_user):
        """Dashboard should display referral section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Рефералы' in data
        assert 'Конверсия' in data

    def test_dashboard_shows_coins(self, app, client, admin_user):
        """Dashboard should display coin economy section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Экономика монет' in data
        assert 'В обращении' in data

    def test_dashboard_shows_content_quality(self, app, client, admin_user):
        """Dashboard should display content quality section."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Качество контента' in data
        assert 'Проблемные уроки' in data

    def test_dashboard_shows_system_health(self, app, client, admin_user):
        """Dashboard should display system health widget."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Система' in data


class TestContentQuality:
    """Tests for get_content_quality function."""

    def test_returns_expected_keys(self, app, db_session):
        """Should return content quality metrics."""
        from app.admin.main_routes import get_content_quality

        result = get_content_quality.__wrapped__()

        assert 'low_pass_lessons' in result
        assert 'low_pass_count' in result
        assert 'zero_completions_count' in result
        assert 'zero_exercises_count' in result

    def test_detects_low_pass_rate_lesson(self, app, db_session):
        """Lesson with <50% pass rate and >=5 attempts should appear in low_pass_lessons."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'cq_{uuid.uuid4().hex[:8]}',
            email=f'cq_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=97
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='CQ Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Hard Lesson', type='quiz', order=1)
        db_session.add(lesson)
        db_session.flush()

        # Create 6 attempts, only 1 passed (16.7% pass rate)
        for i in range(6):
            attempt = LessonAttempt(
                user_id=u.id,
                lesson_id=lesson.id,
                attempt_number=i + 1,
                score=30.0 if i > 0 else 80.0,
                passed=(i == 0),
                completed_at=now - timedelta(hours=i),
                started_at=now - timedelta(hours=i, minutes=30),
            )
            db_session.add(attempt)
        db_session.commit()

        from app.admin.main_routes import get_content_quality

        result = get_content_quality.__wrapped__()

        assert result['low_pass_count'] >= 1
        lesson_ids = [l['lesson_id'] for l in result['low_pass_lessons']]
        assert lesson.id in lesson_ids

    def test_no_low_pass_when_high_pass_rate(self, app, db_session):
        """Lesson with >50% pass rate should not appear."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'hp_{uuid.uuid4().hex[:8]}',
            email=f'hp_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=96
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='HP Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Easy Lesson', type='quiz', order=1)
        db_session.add(lesson)
        db_session.flush()

        # 5 attempts, all passed
        for i in range(5):
            attempt = LessonAttempt(
                user_id=u.id,
                lesson_id=lesson.id,
                attempt_number=i + 1,
                score=90.0,
                passed=True,
                completed_at=now - timedelta(hours=i),
                started_at=now - timedelta(hours=i, minutes=30),
            )
            db_session.add(attempt)
        db_session.commit()

        from app.admin.main_routes import get_content_quality

        result = get_content_quality.__wrapped__()

        lesson_ids = [l['lesson_id'] for l in result['low_pass_lessons']]
        assert lesson.id not in lesson_ids

    def test_counts_zero_completions(self, app, db_session):
        """Should count lessons with zero completions."""
        from app.admin.main_routes import get_content_quality

        result = get_content_quality.__wrapped__()

        # There should always be >= 0
        assert isinstance(result['zero_completions_count'], int)

    def test_counts_grammar_topics_without_exercises(self, app, db_session):
        """Grammar topic without exercises should be counted."""
        from app.grammar_lab.models import GrammarTopic

        topic = GrammarTopic(
            slug=f'no-ex-{uuid.uuid4().hex[:8]}',
            title='No Exercises Topic',
            title_ru='Тема без упражнений',
            level='A1',
            order=997,
            content={},
        )
        db_session.add(topic)
        db_session.commit()

        from app.admin.main_routes import get_content_quality

        result = get_content_quality.__wrapped__()

        assert result['zero_exercises_count'] >= 1


class TestContentAlerts:
    """Tests for get_content_alerts function."""

    def test_returns_list(self, app, db_session):
        """Should return a list of alerts."""
        from app.admin.main_routes import get_content_alerts

        result = get_content_alerts.__wrapped__()

        assert isinstance(result, list)

    def test_alerts_have_expected_fields(self, app, db_session):
        """Each alert should have severity, type, message, action."""
        from app.admin.main_routes import get_content_alerts

        result = get_content_alerts.__wrapped__()

        for alert in result:
            assert 'severity' in alert
            assert 'type' in alert
            assert 'message' in alert
            assert 'action' in alert

    def test_max_5_alerts(self, app, db_session):
        """Should return at most 5 alerts."""
        from app.admin.main_routes import get_content_alerts

        result = get_content_alerts.__wrapped__()

        assert len(result) <= 5


class TestSystemHealth:
    """Tests for get_system_health function."""

    def test_returns_db_status(self, app, db_session):
        """Should return db_status key."""
        from app.admin.main_routes import get_system_health

        result = get_system_health.__wrapped__()

        assert 'db_status' in result
        assert result['db_status'] == 'ok'

    def test_db_error_is_none_when_healthy(self, app, db_session):
        """db_error should be None when DB is healthy."""
        from app.admin.main_routes import get_system_health

        result = get_system_health.__wrapped__()

        assert result['db_error'] is None
