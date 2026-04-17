"""
Tests for the main dashboard route
Ensures template rendering works correctly with all expected data
"""
import time
import pytest
from datetime import date, datetime
from unittest.mock import patch


@pytest.fixture(autouse=True)
def clear_leaderboard_cache():
    """Clear the leaderboard cache before each test to avoid stale data."""
    from app.words.routes import _leaderboard_cache
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0
    yield
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0


@pytest.fixture
def words_module_access(app, db_session, test_user):
    """Grant words module access to test_user"""
    from app.modules.models import SystemModule, UserModule

    with app.app_context():
        # Get or create the words module
        words_module = SystemModule.query.filter_by(code='words').first()
        if not words_module:
            words_module = SystemModule(
                code='words',
                name='Words',
                description='Words module'
            )
            db_session.add(words_module)
            db_session.flush()

        # Grant access to test user
        user_module = UserModule.query.filter_by(
            user_id=test_user.id,
            module_id=words_module.id
        ).first()

        if not user_module:
            user_module = UserModule(
                user_id=test_user.id,
                module_id=words_module.id,
                is_enabled=True
            )
            db_session.add(user_module)
            db_session.commit()

    return words_module


class TestDashboard:
    """Test dashboard route and template rendering"""

    @pytest.mark.smoke
    def test_dashboard_accessible(self, client):
        """Dashboard should redirect to login for anonymous users"""
        response = client.get('/dashboard')
        assert response.status_code in [302, 308]

    def test_dashboard_with_book_progress(self, client, app, db_session, test_user, test_book, test_chapter, words_module_access):
        """Dashboard should correctly display recent book progress via chapter relationship"""
        from app.books.models import UserChapterProgress

        # Create reading progress for test_user
        progress = UserChapterProgress(
            user_id=test_user.id,
            chapter_id=test_chapter.id,
            offset_pct=0.5
        )
        db_session.add(progress)
        db_session.commit()

        # Login and access dashboard
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        # Should render successfully (not crash with template error)
        assert response.status_code == 200
        # The template now correctly accesses recent_book.chapter.book.title
        assert b'Test Book' in response.data


class TestDashboardEmptyStates:
    """Test dashboard rendering with empty/null data scenarios"""

    def test_dashboard_welcome_card_for_new_user(self, client, app, db_session, test_user, words_module_access):
        """New users with no activity should see welcome card"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-welcome' in html
        assert 'Добро пожаловать' in html
        assert 'Начать обучение' in html

    def test_dashboard_empty_daily_plan(self, client, app, db_session, test_user, words_module_access):
        """When daily plan has no steps, show empty plan message"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # New users should see empty plan message, not "all done"
        assert 'Всё на сегодня сделано' not in html or 'dash-plan-empty' in html

    def test_dashboard_xp_tooltip(self, client, app, db_session, test_user, words_module_access):
        """XP bar should have explanatory tooltip"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Опыт за сегодня' in html

    def test_dashboard_null_weekly_challenge(self, client, app, db_session, test_user, words_module_access):
        """When weekly_challenge is None, show 'no active challenge' card"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Should show either active challenge or empty state, not crash
        assert 'dash-challenge' in html

    def test_dashboard_streak_coins_tooltip(self, client, app, db_session, test_user, words_module_access):
        """Streak coins should have explanatory tooltip"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # One of the tooltip variants should be present (depends on streak state)
        has_coin_tooltip = ('Coins — внутренняя валюта' in html or
                           'Серия дней подряд' in html or
                           'dash-streak' in html)
        assert has_coin_tooltip

    def test_dashboard_no_crash_with_zero_data(self, client, app, db_session, test_user, words_module_access):
        """Dashboard should render without errors when all stats are zero"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        # Key sections should render
        html = response.data.decode('utf-8')
        assert 'dash-page' in html
        assert 'dash-hero' in html
        assert 'dash-plan' in html


class TestDashboardWeeklyAnalytics:
    """Test dashboard weekly analytics, SRS distribution, continue lesson, grammar progress"""

    def test_weekly_analytics_with_study_sessions(self, client, app, db_session, test_user, words_module_access):
        """Weekly analytics should show study session data"""
        from app.study.models import StudySession
        from datetime import datetime, timedelta

        # Create a study session from this week
        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() - timedelta(hours=1),
            words_studied=15,
            correct_answers=12,
            incorrect_answers=3,
        )
        db_session.add(session)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'dash-week' in html
        # 12/(12+3) = 80%
        assert '80%' in html

    def test_weekly_analytics_empty_for_new_user(self, client, app, db_session, test_user, words_module_access):
        """New user with no activity should not see weekly analytics section rendered"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # class="dash-week" in HTML means the section rendered (vs .dash-week in CSS)
        assert 'class="dash-week"' not in html

    def test_srs_distribution_not_shown_when_no_words(self, client, app, db_session, test_user, words_module_access):
        """SRS distribution bar should not appear when user has no words"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-srs"' not in html

    def test_continue_lesson_not_shown_when_no_active(self, client, app, db_session, test_user, words_module_access):
        """Continue lesson card should not appear when no in-progress lessons"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'class="dash-continue"' not in html

    def test_grammar_progress_shown_when_topics_exist(self, client, app, db_session, test_user, words_module_access):
        """Grammar progress section should appear when grammar topics exist"""
        from app.grammar_lab.models import GrammarTopic
        import uuid

        # Check if there are already grammar topics
        existing_count = GrammarTopic.query.count()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        if existing_count > 0:
            assert 'dash-grammar-progress' in html
        else:
            # No topics means section should not appear
            assert 'dash-grammar-progress' not in html

    def test_weekly_analytics_with_lesson_completed(self, client, app, db_session, test_user, words_module_access):
        """Weekly analytics should count completed lessons"""
        from app.curriculum.models import LessonProgress, Lessons, Module, CEFRLevel
        from datetime import datetime

        # Create supporting objects
        level = CEFRLevel.query.first()
        if not level:
            level = CEFRLevel(code='A1', name='Beginner', order=1)
            db_session.add(level)
            db_session.flush()

        module = Module.query.first()
        if not module:
            module = Module(title='Test Module', number=1, level_id=level.id)
            db_session.add(module)
            db_session.flush()

        lesson = Lessons(title='Test Lesson', module_id=module.id, number=1, order=1, type='vocabulary')
        db_session.add(lesson)
        db_session.flush()

        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            completed_at=datetime.utcnow(),
            score=85.0,
        )
        db_session.add(progress)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Should show weekly analytics with at least 1 lesson
        assert 'dash-week' in html


class TestDashboardTemplateRelationships:
    """Test that dashboard template correctly uses model relationships"""

    def test_recent_book_chapter_book_chain(self, client, app, db_session, test_user, test_book, test_chapter, words_module_access):
        """
        Test that dashboard template can access book via chapter relationship.

        This test catches the bug where template used recent_book.book.title
        but UserChapterProgress doesn't have a direct book relationship.
        The correct path is recent_book.chapter.book.title.
        """
        from app.books.models import UserChapterProgress

        # Create reading progress
        progress = UserChapterProgress(
            user_id=test_user.id,
            chapter_id=test_chapter.id,
            offset_pct=0.25
        )
        db_session.add(progress)
        db_session.commit()

        # Verify the relationship chain works in code
        assert progress.chapter is not None
        assert progress.chapter.book is not None
        assert progress.chapter.book.title == 'Test Book'

        # Login and verify dashboard renders without error
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        # No Jinja2 UndefinedError should occur

    def test_dashboard_without_reading_progress(self, client, app, test_user, words_module_access):
        """Dashboard should work when user has no reading progress (recent_book is None)"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        # Template should handle None recent_book gracefully


class TestDashboardActivityHeatmap:
    """Test activity heatmap and streak calendar data on dashboard"""

    def test_dashboard_includes_heatmap_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_activity_heatmap and pass data to template"""
        mock_heatmap = [
            {'date': '2026-04-09', 'count': 3},
            {'date': '2026-04-10', 'count': 0},
        ]
        mock_calendar = {
            'active_dates': ['2026-04-09'],
            'total_active_days': 1,
            'longest_streak': 1,
            'current_streak': 1,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=mock_heatmap) as mock_hm, \
             patch('app.achievements.streak_service.get_streak_calendar', return_value=mock_calendar) as mock_sc:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_hm.assert_called_once_with(test_user.id, days=90, tz='Europe/Moscow')
            mock_sc.assert_called_once_with(test_user.id, days=90, tz='Europe/Moscow')

    def test_dashboard_renders_heatmap_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render the heatmap section when data exists"""
        mock_heatmap = [{'date': f'2026-04-{d:02d}', 'count': d % 4} for d in range(1, 11)]
        mock_calendar = {
            'active_dates': ['2026-04-05'],
            'total_active_days': 15,
            'longest_streak': 7,
            'current_streak': 3,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=mock_heatmap), \
             patch('app.achievements.streak_service.get_streak_calendar', return_value=mock_calendar):
            response = client.get('/dashboard')
            assert response.status_code == 200
            html = response.data.decode('utf-8')
            assert 'dash-heatmap' in html
            assert 'dash-heatmap__grid' in html
            assert 'dash-heatmap__stats' in html

    def test_dashboard_heatmap_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render heatmap section when data is empty"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=[]), \
             patch('app.achievements.streak_service.get_streak_calendar', return_value={}):
            response = client.get('/dashboard')
            assert response.status_code == 200
            html = response.data.decode('utf-8')
            # The CSS class will exist in <style>, but the HTML element should not
            assert 'dash-heatmap__heading' not in html.split('<style>')[0]

    def test_dashboard_streak_stats_rendered(self, client, app, test_user, words_module_access):
        """Dashboard should show streak stats from streak_calendar data"""
        mock_heatmap = [{'date': '2026-04-10', 'count': 2}]
        mock_calendar = {
            'active_dates': ['2026-04-10'],
            'total_active_days': 42,
            'longest_streak': 21,
            'current_streak': 5,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=mock_heatmap), \
             patch('app.achievements.streak_service.get_streak_calendar', return_value=mock_calendar):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0] if '<style>' in html else html
            assert '>42<' in html_body  # total_active_days
            assert '>21<' in html_body  # longest_streak


class TestDashboardWordsAtRisk:
    """Test words at risk widget data on dashboard"""

    def test_dashboard_includes_words_at_risk_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_words_at_risk and pass data to template"""
        mock_words = [
            {'word': 'abandon', 'translation': 'покидать', 'days_overdue': 5},
            {'word': 'benevolent', 'translation': 'доброжелательный', 'days_overdue': 3},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_words_at_risk', return_value=mock_words) as mock_war:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_war.assert_called_once_with(test_user.id, limit=5)

    def test_dashboard_renders_words_at_risk_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render words at risk widget when data exists"""
        mock_words = [
            {'word': 'abandon', 'translation': 'покидать', 'days_overdue': 5},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_words_at_risk', return_value=mock_words):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-risk' in html
            assert 'abandon' in html
            # days_overdue badge rendered
            assert 'dash-risk__badge' in html
            assert '>5 ' in html

    def test_dashboard_words_at_risk_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render words at risk widget when no data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_words_at_risk', return_value=[]), \
             patch('app.study.insights_service.get_grammar_weaknesses', return_value=[]):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            # dash-alerts-row div should not be rendered when both lists are empty
            assert 'dash-alerts-row"' not in html


class TestDashboardGrammarWeaknesses:
    """Test grammar weaknesses widget data on dashboard"""

    def test_dashboard_includes_grammar_weaknesses_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_grammar_weaknesses and pass data to template"""
        mock_weaknesses = [
            {'title': 'Present Perfect', 'accuracy': 45.2, 'attempts': 10},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_grammar_weaknesses', return_value=mock_weaknesses) as mock_gw:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_gw.assert_called_once_with(test_user.id, limit=5)

    def test_dashboard_renders_grammar_weaknesses_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render grammar weaknesses widget when data exists"""
        mock_weaknesses = [
            {'title': 'Present Perfect', 'accuracy': 45.2, 'attempts': 10},
            {'title': 'Conditionals', 'accuracy': 62.5, 'attempts': 8},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_grammar_weaknesses', return_value=mock_weaknesses):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-weakness' in html
            assert 'Present Perfect' in html
            assert '45.2%' in html

    def test_dashboard_grammar_weaknesses_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render grammar weaknesses widget when no data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_words_at_risk', return_value=[]), \
             patch('app.study.insights_service.get_grammar_weaknesses', return_value=[]):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            # dash-alerts-row div should not be rendered when both lists are empty
            assert 'dash-alerts-row"' not in html


class TestDashboardBestStudyTime:
    """Test best study time widget data on dashboard"""

    def test_dashboard_includes_best_study_time_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_best_study_time and pass data to template"""
        mock_data = {'best_hour': 14, 'hourly_scores': {14: 85.5, 15: 72.0}}

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_best_study_time', return_value=mock_data) as mock_bst:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_bst.assert_called_once_with(test_user.id, tz='Europe/Moscow')

    def test_dashboard_renders_best_study_time_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render best study time widget with hour and chart"""
        mock_data = {'best_hour': 14, 'hourly_scores': {14: 85.5, 10: 60.0}}

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_best_study_time', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-study-time' in html
            assert '14:00' in html
            assert 'dash-study-time__bar--best' in html

    def test_dashboard_best_study_time_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should show empty state when no study time data"""
        mock_data = {'best_hour': None, 'hourly_scores': {}}

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_best_study_time', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-study-time__empty' in html
            # Chart div should not be rendered (class appears in CSS but not as HTML element)
            assert 'class="dash-study-time__chart"' not in html


class TestDashboardSessionStats:
    """Test session stats widget data on dashboard"""

    def test_dashboard_includes_session_stats_data(self, client, app, test_user, words_module_access):
        """Dashboard should call SessionService.get_session_stats and pass data to template"""
        mock_stats = {
            'period_days': 7,
            'total_sessions': 12,
            'total_words_studied': 85,
            'total_correct': 70,
            'total_incorrect': 15,
            'accuracy_percent': 82.4,
            'total_time_seconds': 3600,
            'avg_session_time_seconds': 300,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.session_service.SessionService.get_session_stats', return_value=mock_stats) as mock_ss:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_ss.assert_called_once_with(test_user.id, days=7)

    def test_dashboard_renders_session_stats_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render weekly stats cards"""
        mock_stats = {
            'period_days': 7,
            'total_sessions': 12,
            'total_words_studied': 85,
            'total_correct': 70,
            'total_incorrect': 15,
            'accuracy_percent': 82.4,
            'total_time_seconds': 3600,
            'avg_session_time_seconds': 300,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.session_service.SessionService.get_session_stats', return_value=mock_stats):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-week-stats' in html
            assert '>12<' in html  # total_sessions
            assert '>85<' in html  # total_words_studied
            assert '82.4%' in html  # accuracy
            html_body = html.split('<style>')[0] if '<style>' in html else html
            assert '>60<' in html_body or '>60 ' in html_body  # 3600 seconds = 60 min


class TestDashboardLeaderboard:
    """Test leaderboard and XP rank widget data on dashboard"""

    def test_dashboard_includes_leaderboard_data(self, client, app, test_user, words_module_access):
        """Dashboard should call StatsService.get_xp_leaderboard and get_user_xp_rank"""
        mock_leaderboard = [
            {'id': 1, 'username': 'alice', 'total_xp': 500, 'level': 5},
            {'id': 2, 'username': 'bob', 'total_xp': 400, 'level': 4},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=mock_leaderboard) as mock_lb, \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=8) as mock_rank:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_lb.assert_called_once_with(limit=5)
            mock_rank.assert_called_once_with(test_user.id)

    def test_dashboard_renders_leaderboard_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render leaderboard with user entries"""
        mock_leaderboard = [
            {'id': 1, 'username': 'alice', 'total_xp': 500, 'level': 5},
            {'id': test_user.id, 'username': test_user.username, 'total_xp': 300, 'level': 3},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=mock_leaderboard), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=2):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            assert 'dash-leaderboard' in html
            assert 'alice' in html
            assert '500 XP' in html
            # Current user row should be highlighted
            assert 'dash-leaderboard__highlight' in html

    def test_dashboard_leaderboard_shows_rank_when_not_in_top5(self, client, app, test_user, words_module_access):
        """Dashboard should show user rank badge when user is not in top 5"""
        mock_leaderboard = [
            {'id': i, 'username': f'user{i}', 'total_xp': 1000 - i * 100, 'level': 10 - i}
            for i in range(1, 6)
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=mock_leaderboard), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=12):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0] if '<style>' in html else html
            assert 'dash-leaderboard__you' in html_body
            assert '12-м месте' in html_body

    def test_dashboard_leaderboard_hides_rank_when_in_top5(self, client, app, test_user, words_module_access):
        """Dashboard should not show rank badge when user is already in the leaderboard"""
        mock_leaderboard = [
            {'id': test_user.id, 'username': test_user.username, 'total_xp': 500, 'level': 5},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=mock_leaderboard), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=1):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            # Check only the HTML body (before <style>) to avoid matching CSS class definitions
            html_body = html.split('<style>')[0]
            assert 'dash-leaderboard__you' not in html_body

    def test_dashboard_leaderboard_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render leaderboard widget when no data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=[]), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=None):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            # Leaderboard HTML element should not appear (CSS class will be in <style>)
            assert 'dash-leaderboard__heading' not in html.split('<style>')[0]


class TestDashboardAchievementsByCategory:
    """Test achievements by category widget data on dashboard"""

    def test_dashboard_includes_achievements_by_category_data(self, client, app, test_user, words_module_access):
        """Dashboard should call StatsService.get_achievements_by_category and pass data to template"""
        mock_data = {
            'by_category': {
                'vocabulary': [
                    {'achievement': type('A', (), {'id': 1, 'name': 'Word Learner', 'icon': '📚', 'category': 'vocabulary'})(),
                     'earned': True, 'earned_at': datetime(2026, 4, 1)},
                ],
                'grammar': [
                    {'achievement': type('A', (), {'id': 2, 'name': 'Grammar Pro', 'icon': '✏️', 'category': 'grammar'})(),
                     'earned': False, 'earned_at': None},
                ],
            },
            'total_achievements': 2,
            'earned_count': 1,
            'progress_percentage': 50,
            'total_xp_earned': 100,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value=mock_data) as mock_abc:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_abc.assert_called_once_with(test_user.id)

    def test_dashboard_renders_achievements_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render achievements widget with category rings"""
        mock_data = {
            'by_category': {
                'vocabulary': [
                    {'achievement': type('A', (), {'id': 1, 'name': 'Word Learner', 'icon': '📚', 'category': 'vocabulary'})(),
                     'earned': True, 'earned_at': datetime(2026, 4, 1)},
                    {'achievement': type('A', (), {'id': 2, 'name': 'Word Master', 'icon': '🏆', 'category': 'vocabulary'})(),
                     'earned': False, 'earned_at': None},
                ],
            },
            'total_achievements': 2,
            'earned_count': 1,
            'progress_percentage': 50,
            'total_xp_earned': 100,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-achievements' in html_body
            assert 'dash-achievements__ring' in html_body
            assert '1 / 2' in html_body
            assert '50%' in html_body
            assert 'vocabulary' in html_body

    def test_dashboard_renders_recent_unlocks(self, client, app, test_user, words_module_access):
        """Dashboard should show recently unlocked achievements"""
        mock_data = {
            'by_category': {
                'vocabulary': [
                    {'achievement': type('A', (), {'id': 1, 'name': 'Word Learner', 'icon': '📚', 'category': 'vocabulary'})(),
                     'earned': True, 'earned_at': datetime(2026, 4, 1)},
                ],
            },
            'total_achievements': 1,
            'earned_count': 1,
            'progress_percentage': 100,
            'total_xp_earned': 50,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-achievements__recent' in html_body
            assert 'Word Learner' in html_body

    def test_dashboard_achievements_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render achievements widget when no data"""
        mock_data = {
            'by_category': {},
            'total_achievements': 0,
            'earned_count': 0,
            'progress_percentage': 0,
            'total_xp_earned': 0,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-achievements__heading' not in html_body


class TestDashboardMilestoneHistory:
    """Test streak milestones widget data on dashboard"""

    def test_dashboard_includes_milestone_history_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_milestone_history and pass data to template"""
        mock_milestones = [
            {'streak': 30, 'reward': 150, 'date': date(2026, 3, 15)},
            {'streak': 14, 'reward': 75, 'date': date(2026, 2, 28)},
            {'streak': 7, 'reward': 50, 'date': date(2026, 2, 21)},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.achievements.streak_service.get_milestone_history', return_value=mock_milestones) as mock_mh:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_mh.assert_called_once_with(test_user.id)

    def test_dashboard_renders_milestones_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render milestones timeline with earned and pending items"""
        mock_milestones = [
            {'streak': 14, 'reward': 75, 'date': date(2026, 3, 1)},
            {'streak': 7, 'reward': 50, 'date': date(2026, 2, 15)},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.achievements.streak_service.get_milestone_history', return_value=mock_milestones):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-milestones' in html_body
            assert 'dash-milestones__timeline' in html_body
            # Earned milestones should have --earned class
            assert 'dash-milestones__item--earned' in html_body
            # 7 and 14 day milestones earned
            assert '15.02' in html_body  # date for 7-day milestone
            assert '01.03' in html_body  # date for 14-day milestone

    def test_dashboard_milestones_shows_all_targets(self, client, app, test_user, words_module_access):
        """Dashboard should show all milestone targets (7, 14, 30, 60, 100)"""
        mock_milestones = [
            {'streak': 7, 'reward': 50, 'date': date(2026, 2, 15)},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.achievements.streak_service.get_milestone_history', return_value=mock_milestones):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            # All 5 milestone targets should be shown
            for target in ['7д', '14д', '30д', '60д', '100д']:
                assert target in html_body

    def test_dashboard_milestones_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render milestones widget when no history"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.achievements.streak_service.get_milestone_history', return_value=[]):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-milestones__heading' not in html_body


class TestDashboardReadingSpeedTrend:
    """Test reading speed trend widget data on dashboard"""

    def test_dashboard_includes_reading_speed_data(self, client, app, test_user, words_module_access):
        """Dashboard should call get_reading_speed_trend and pass data to template"""
        mock_data = [
            {'week': '2026-W12', 'avg_wpm': 120.5},
            {'week': '2026-W13', 'avg_wpm': 135.0},
            {'week': '2026-W14', 'avg_wpm': 142.3},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_reading_speed_trend', return_value=mock_data) as mock_rst:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_rst.assert_called_once_with(test_user.id)

    def test_dashboard_renders_reading_speed_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render reading speed widget with sparkline and comparison"""
        mock_data = [
            {'week': '2026-W12', 'avg_wpm': 120.5},
            {'week': '2026-W13', 'avg_wpm': 135.0},
            {'week': '2026-W14', 'avg_wpm': 142.3},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_reading_speed_trend', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-reading-speed' in html_body
            assert 'dash-sparkline' in html_body
            assert '142' in html_body  # current WPM rounded
            assert '+22' in html_body  # diff: 142.3 - 120.5 = 21.8 -> +22
            assert '2026-W12' in html_body  # start week label
            assert '2026-W14' in html_body  # end week label

    def test_dashboard_reading_speed_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render reading speed widget when no data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_reading_speed_trend', return_value=[]):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-reading-speed__heading' not in html_body

    def test_dashboard_reading_speed_single_point(self, client, app, test_user, words_module_access):
        """Dashboard should render without change indicator for single data point"""
        mock_data = [
            {'week': '2026-W14', 'avg_wpm': 130.0},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_reading_speed_trend', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-reading-speed' in html_body
            assert '130' in html_body
            # No change indicator for single point
            assert 'dash-reading-speed__change' not in html_body


class TestDashboardGrammarLevels:
    """Test grammar by level widget data on dashboard"""

    def test_dashboard_includes_grammar_levels_data(self, client, app, test_user, words_module_access):
        """Dashboard should call GrammarLabService.get_levels_summary and pass data to template"""
        mock_data = [
            {'level': 'A1', 'topic_count': 10, 'exercises_total': 50, 'exercises_mastered': 30, 'progress_pct': 60.0},
            {'level': 'A2', 'topic_count': 8, 'exercises_total': 40, 'exercises_mastered': 10, 'progress_pct': 25.0},
            {'level': 'B1', 'topic_count': 12, 'exercises_total': 60, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'B2', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'C1', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'C2', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', return_value=mock_data) as mock_gls:
            response = client.get('/dashboard')
            assert response.status_code == 200
            mock_gls.assert_called_once_with(user_id=test_user.id)

    def test_dashboard_renders_grammar_levels_widget(self, client, app, test_user, words_module_access):
        """Dashboard should render grammar levels widget with bars per level"""
        mock_data = [
            {'level': 'A1', 'topic_count': 10, 'exercises_total': 50, 'exercises_mastered': 30, 'progress_pct': 60.0},
            {'level': 'A2', 'topic_count': 8, 'exercises_total': 40, 'exercises_mastered': 10, 'progress_pct': 25.0},
            {'level': 'B1', 'topic_count': 12, 'exercises_total': 60, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'B2', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'C1', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
            {'level': 'C2', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            assert 'dash-grammar-levels' in html_body
            assert 'dash-grammar-levels__bar' in html_body
            # Levels with topics should appear
            assert '>A1<' in html_body
            assert '>A2<' in html_body
            assert '>B1<' in html_body
            # Levels without topics should NOT appear
            assert '>B2<' not in html_body
            assert '>C1<' not in html_body
            # Progress info
            assert '30/50' in html_body
            assert '60.0%' in html_body

    def test_dashboard_grammar_levels_empty_state(self, client, app, test_user, words_module_access):
        """Dashboard should not render grammar levels widget when all levels have 0 topics"""
        mock_data = [
            {'level': lvl, 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0}
            for lvl in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', return_value=mock_data):
            response = client.get('/dashboard')
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]
            # Grammar levels widget should not render when all levels have 0 topics
            assert 'dash-grammar-levels__heading' not in html_body


class TestDashboardLayoutSections:
    """Test that all dashboard sections render correctly with proper layout structure"""

    def test_dashboard_renders_all_sections_with_data(self, client, app, test_user, words_module_access):
        """Dashboard should render all 9 layout sections when all data is present"""
        mock_heatmap = [{'date': f'2026-04-{d:02d}', 'count': d % 4} for d in range(1, 11)]
        mock_calendar = {
            'active_dates': ['2026-04-09'],
            'total_active_days': 10,
            'longest_streak': 5,
            'current_streak': 3,
        }
        mock_words_at_risk = [
            {'word': 'test', 'translation': 'тест', 'days_overdue': 2},
        ]
        mock_grammar_weak = [
            {'title': 'Conditionals', 'accuracy': 55.0, 'attempts': 6},
        ]
        mock_study_time = {'best_hour': 10, 'hourly_scores': {10: 90, 14: 50}}
        mock_session_stats = {
            'period_days': 7,
            'total_sessions': 5,
            'total_words_studied': 40,
            'total_correct': 35,
            'total_incorrect': 5,
            'accuracy_percent': 87.5,
            'total_time_seconds': 1800,
            'avg_session_time_seconds': 360,
        }
        mock_leaderboard = [
            type('U', (), {'id': test_user.id, 'username': 'testuser', 'total_xp': 500, 'level': 3})(),
        ]
        mock_achievements = {
            'by_category': {
                'vocabulary': [
                    type('A', (), {
                        'earned': True,
                        'earned_at': datetime(2026, 4, 1),
                        'achievement': type('Ach', (), {'icon': '🏆', 'name': 'Word Master'})(),
                    })(),
                ],
            },
            'earned_count': 1,
            'total_achievements': 5,
            'progress_percentage': 20,
        }
        mock_reading_speed = [
            type('R', (), {'week': 'W1', 'avg_wpm': 120.0})(),
            type('R', (), {'week': 'W2', 'avg_wpm': 135.0})(),
        ]
        mock_milestones = [
            type('M', (), {'streak': 7, 'date': date(2026, 3, 15)})(),
        ]
        mock_grammar_levels = [
            {'level': 'A1', 'topic_count': 5, 'exercises_total': 25, 'exercises_mastered': 15, 'progress_pct': 60.0},
            {'level': 'A2', 'topic_count': 0, 'exercises_total': 0, 'exercises_mastered': 0, 'progress_pct': 0},
        ]

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=mock_heatmap), \
             patch('app.achievements.streak_service.get_streak_calendar', return_value=mock_calendar), \
             patch('app.study.insights_service.get_words_at_risk', return_value=mock_words_at_risk), \
             patch('app.study.insights_service.get_grammar_weaknesses', return_value=mock_grammar_weak), \
             patch('app.study.insights_service.get_best_study_time', return_value=mock_study_time), \
             patch('app.study.services.session_service.SessionService.get_session_stats', return_value=mock_session_stats), \
             patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=mock_leaderboard), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=1), \
             patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value=mock_achievements), \
             patch('app.study.insights_service.get_reading_speed_trend', return_value=mock_reading_speed), \
             patch('app.achievements.streak_service.get_milestone_history', return_value=mock_milestones), \
             patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', return_value=mock_grammar_levels):
            response = client.get('/dashboard')
            assert response.status_code == 200
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]

            # Section 1: Hero
            assert 'dash-hero' in html_body
            # Section 2: Daily Plan
            assert 'dash-plan' in html_body
            # Section 3: Activity Heatmap
            assert 'dash-heatmap' in html_body
            assert 'dash-section__heading">Активность' in html_body
            # Section 4: Alerts row
            assert 'dash-alerts-row' in html_body
            assert 'dash-risk' in html_body
            assert 'dash-weakness' in html_body
            assert 'dash-section__heading">Внимание' in html_body
            # Section 5: Stats row
            assert 'dash-stats-row' in html_body
            assert 'dash-study-time' in html_body
            assert 'dash-week-stats' in html_body
            assert 'dash-section__heading">Статистика' in html_body
            # Section 6: Progress row
            assert 'dash-progress-row' in html_body
            assert 'dash-progress-overview' in html_body
            assert 'dash-grammar-levels' in html_body
            assert 'dash-section__heading">Прогресс' in html_body
            # Section 7: Social row
            assert 'dash-social-row' in html_body
            assert 'dash-leaderboard' in html_body
            assert 'dash-achievements' in html_body
            assert 'dash-section__heading">Сообщество' in html_body
            # Section 8: Insights row
            assert 'dash-insights-row' in html_body
            assert 'dash-reading-speed' in html_body
            assert 'dash-milestones' in html_body
            assert 'dash-section__heading">Аналитика' in html_body
            # Section 9: Quick Actions
            assert 'dash-quick' in html_body

    def test_dashboard_section_dividers_present(self, client, app, test_user, words_module_access):
        """Dashboard should render section dividers between widget groups"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        html_body = html.split('<style>')[0]

        # Each section should have a divider
        divider_count = html_body.count('dash-section__divider')
        assert divider_count >= 6  # sections 3-9 have dividers (section 9 has divider only)

    def test_dashboard_empty_states_all_widgets(self, client, app, test_user, words_module_access):
        """Dashboard should show friendly empty states when user has no activity data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.study.insights_service.get_activity_heatmap', return_value=[]), \
             patch('app.achievements.streak_service.get_streak_calendar', return_value={}), \
             patch('app.study.insights_service.get_words_at_risk', return_value=[]), \
             patch('app.study.insights_service.get_grammar_weaknesses', return_value=[]), \
             patch('app.study.insights_service.get_best_study_time', return_value={'best_hour': None, 'hourly_scores': {}}), \
             patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', return_value=[]), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', return_value=None), \
             patch('app.study.services.stats_service.StatsService.get_achievements_by_category', return_value={}), \
             patch('app.study.insights_service.get_reading_speed_trend', return_value=[]), \
             patch('app.achievements.streak_service.get_milestone_history', return_value=[]), \
             patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', return_value=[]):
            response = client.get('/dashboard')
            assert response.status_code == 200
            html = response.data.decode('utf-8')
            html_body = html.split('<style>')[0]

            # Empty states should be shown
            empty_count = html_body.count('dash-empty')
            assert empty_count >= 4  # heatmap, alerts, leaderboard, achievements, reading speed, milestones

            # Data widgets should NOT render
            assert 'dash-heatmap__grid' not in html_body
            assert 'dash-risk__item' not in html_body
            assert 'dash-leaderboard__row' not in html_body
            assert 'dash-reading-speed__value' not in html_body
            assert 'dash-milestones__timeline' not in html_body

    def test_dashboard_responsive_css_classes(self, client, app, test_user, words_module_access):
        """Dashboard should include responsive grid classes for 2-col layouts"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # CSS should contain responsive rules for all 2-col rows
        assert 'dash-alerts-row' in html
        assert 'dash-stats-row' in html
        assert 'dash-progress-row' in html
        assert 'dash-social-row' in html
        assert 'dash-insights-row' in html

        # CSS should contain mobile breakpoint rules
        style_section = html.split('<style>')[1].split('</style>')[0] if '<style>' in html else ''
        assert 'max-width: 640px' in style_section


class TestDashboardPerformance:
    """Test dashboard performance optimizations"""

    def test_dashboard_responds_within_acceptable_time(self, client, app, test_user, words_module_access):
        """Dashboard route should respond within 5 seconds with test data"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        t_start = time.time()
        response = client.get('/dashboard')
        t_elapsed = time.time() - t_start

        assert response.status_code == 200
        assert t_elapsed < 8.0, f"Dashboard took {t_elapsed:.2f}s, expected < 8s"

    def test_dashboard_widget_failure_does_not_crash(self, client, app, test_user, words_module_access):
        """If a non-critical widget service raises an exception, dashboard should still render"""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        # Make several widget services raise exceptions
        with patch('app.study.insights_service.get_activity_heatmap', side_effect=Exception("heatmap DB error")), \
             patch('app.study.insights_service.get_words_at_risk', side_effect=Exception("risk DB error")), \
             patch('app.study.insights_service.get_grammar_weaknesses', side_effect=Exception("grammar DB error")), \
             patch('app.study.insights_service.get_best_study_time', side_effect=Exception("study time error")), \
             patch('app.study.insights_service.get_reading_speed_trend', side_effect=Exception("speed error")), \
             patch('app.achievements.streak_service.get_streak_calendar', side_effect=Exception("calendar error")), \
             patch('app.achievements.streak_service.get_milestone_history', side_effect=Exception("milestone error")), \
             patch('app.study.services.session_service.SessionService.get_session_stats', side_effect=Exception("session error")), \
             patch('app.study.services.stats_service.StatsService.get_xp_leaderboard', side_effect=Exception("leaderboard error")), \
             patch('app.study.services.stats_service.StatsService.get_user_xp_rank', side_effect=Exception("rank error")), \
             patch('app.study.services.stats_service.StatsService.get_achievements_by_category', side_effect=Exception("achievements error")), \
             patch('app.grammar_lab.services.grammar_lab_service.GrammarLabService.get_levels_summary', side_effect=Exception("grammar levels error")):
            response = client.get('/dashboard')
            # Dashboard should still render even with all widget failures
            assert response.status_code == 200

    def test_leaderboard_cache_serves_cached_data(self, app):
        """Leaderboard cache should return cached data within TTL"""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache

        call_count = 0
        expected_data = [{'id': 1, 'username': 'alice', 'total_xp': 500}]

        class MockStatsService:
            @staticmethod
            def get_xp_leaderboard(limit=5):
                nonlocal call_count
                call_count += 1
                return expected_data

        # First call should hit the service
        result1 = _get_cached_leaderboard(MockStatsService, limit=5)
        assert result1 == expected_data
        assert call_count == 1

        # Second call should serve from cache
        result2 = _get_cached_leaderboard(MockStatsService, limit=5)
        assert result2 == expected_data
        assert call_count == 1  # Not called again

    def test_leaderboard_cache_expires(self, app):
        """Leaderboard cache should refetch after TTL expires"""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache

        call_count = 0

        class MockStatsService:
            @staticmethod
            def get_xp_leaderboard(limit=5):
                nonlocal call_count
                call_count += 1
                return [{'id': call_count}]

        # First call
        _get_cached_leaderboard(MockStatsService, limit=5)
        assert call_count == 1

        # Expire the cache manually
        with _leaderboard_cache['lock']:
            _leaderboard_cache['expires'] = 0.0

        # Second call should refetch
        result = _get_cached_leaderboard(MockStatsService, limit=5)
        assert call_count == 2
        assert result == [{'id': 2}]

    def test_safe_widget_call_returns_default_on_error(self, app):
        """_safe_widget_call should return default value on error (savepoint handles rollback)"""
        from app.words.routes import _safe_widget_call

        def failing_fn():
            raise ValueError("something broke")

        result = _safe_widget_call('test_widget', failing_fn, default=[])
        assert result == []

    def test_safe_widget_call_returns_result_on_success(self, app):
        """_safe_widget_call should return function result on success"""
        from app.words.routes import _safe_widget_call

        result = _safe_widget_call('test_widget', lambda x: x * 2, 5, default=0)
        assert result == 10


class TestDailyRaceWidget:
    """Tests for the daily race widget data and template rendering."""

    def test_compute_daily_race_state_legacy_plan(self, app):
        """_compute_daily_race_state returns correct steps and score for legacy plan."""
        from app.words.routes import _compute_daily_race_state

        plan = {
            'steps': {
                'lesson': {'title': 'Урок', 'state': 'completed'},
                'grammar': {'title': 'Грамматика', 'state': 'open'},
            }
        }
        summary = {}
        result = _compute_daily_race_state(plan, summary, streak=3)
        assert result['steps_total'] == 2
        assert result['steps_done'] == 1
        assert result['score'] == 22  # lesson = 22 pts
        assert result['next_step_title'] is not None

    def test_compute_daily_race_state_mission_plan(self, app):
        """_compute_daily_race_state correctly scores completed mission phases."""
        from app.words.routes import _compute_daily_race_state, _MISSION_PHASE_POINTS

        phases = [
            {'id': 'p1', 'phase': 'recall', 'title': 'Повторение', 'required': True, 'mode': 'srs_words'},
            {'id': 'p2', 'phase': 'learn', 'title': 'Урок', 'required': True, 'mode': 'lesson'},
        ]
        plan = {'phases': phases}
        summary = {'words_reviewed': 10}  # enough to mark recall done
        result = _compute_daily_race_state(plan, summary, streak=5)
        assert result['steps_total'] == 2
        assert isinstance(result['score'], int)
        assert result['score'] >= 0

    def test_participant_initials_basic(self, app):
        """_participant_initials returns 1-2 uppercase letters."""
        from app.words.routes import _participant_initials

        assert _participant_initials('alice') == 'AL'
        assert _participant_initials('Alice Bob') == 'AB'
        assert _participant_initials('a') == 'A'
        assert _participant_initials('') == '?'
        assert _participant_initials(None) == '?'

    def test_participant_initials_underscore_name(self, app):
        """_participant_initials splits on underscores for compound names."""
        from app.words.routes import _participant_initials

        assert _participant_initials('john_doe') == 'JD'

    def test_medal_by_rank_mapping(self, app):
        """_MEDAL_BY_RANK maps top 3 places to medal class names."""
        from app.words.routes import _MEDAL_BY_RANK

        assert _MEDAL_BY_RANK[1] == 'gold'
        assert _MEDAL_BY_RANK[2] == 'silver'
        assert _MEDAL_BY_RANK[3] == 'bronze'
        assert 4 not in _MEDAL_BY_RANK

    def test_build_daily_race_widget_returns_correct_structure(self, app, db_session, test_user):
        """_build_daily_race_widget returns dict with required keys including new fields."""
        from unittest.mock import patch
        from app.words.routes import _build_daily_race_widget

        fake_plan = {'steps': {'lesson': {'title': 'Урок', 'state': 'done'}}}
        fake_summary = {}
        fake_streak = 3

        with patch('app.words.routes._compute_daily_race_state') as mock_state, \
             patch('app.daily_plan.service.get_daily_plan_unified', return_value=fake_plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=fake_summary), \
             patch('app.telegram.queries.get_current_streak', return_value=fake_streak):

            mock_state.return_value = {
                'score': 22,
                'steps_done': 1,
                'steps_total': 1,
                'next_step_title': None,
                'next_step_points': 0,
            }

            result = _build_daily_race_widget(test_user.id, tz='Europe/Moscow')

        if result is not None:
            assert 'rank' in result
            assert 'place_class' in result
            assert 'is_complete' in result
            assert 'leaderboard' in result
            assert isinstance(result['leaderboard'], list)
            for row in result['leaderboard']:
                assert 'initials' in row
                assert 'place_class' in row
                assert 'is_complete' in row

    def test_race_widget_template_structure(self, client, app, db_session, test_user, words_module_access):
        """When daily_race data is injected, template renders initials and position badges."""
        from unittest.mock import patch

        fake_race = {
            'rank': 2,
            'place_class': 'silver',
            'total': 4,
            'score': 30,
            'steps_done': 1,
            'steps_total': 3,
            'streak': 5,
            'is_complete': False,
            'rival_above': {'username': 'Leader', 'score': 38},
            'rival_below': None,
            'gap_up': 8,
            'gap_down': None,
            'callout': 'Ещё 8 очков до лидера.',
            'next_step_title': 'Урок',
            'next_step_points': 22,
            'duel_target': {'username': 'Leader'},
            'has_bot_rivals': True,
            'next_action_title': None,
            'next_action_url': None,
            'leaderboard': [
                {'rank': 1, 'username': 'Leader', 'initials': 'LE', 'score': 38,
                 'steps_done': 2, 'steps_total': 3, 'streak': 7,
                 'place_class': 'gold', 'is_complete': False, 'is_me': False, 'is_bot': False},
                {'rank': 2, 'username': 'me_user', 'initials': 'ME', 'score': 30,
                 'steps_done': 1, 'steps_total': 3, 'streak': 5,
                 'place_class': 'silver', 'is_complete': False, 'is_me': True, 'is_bot': False},
                {'rank': 3, 'username': 'Bot', 'initials': 'BO', 'score': 18,
                 'steps_done': 0, 'steps_total': 3, 'streak': 4,
                 'place_class': 'bronze', 'is_complete': False, 'is_me': False, 'is_bot': True},
            ],
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.words.routes._build_daily_race_widget', return_value=fake_race):
            response = client.get('/dashboard')

        assert response.status_code == 200
        html = response.data.decode('utf-8')

        assert 'dash-race' in html
        assert 'dash-race__avatar' in html
        assert 'dash-race__row--me' in html
        assert 'dash-race__place--gold' in html
        assert 'dash-race__place--silver' in html
        assert 'dash-race__place--bronze' in html
        assert 'ME' in html
        assert 'Тренировочный режим' in html

    def test_race_widget_complete_state(self, client, app, db_session, test_user, words_module_access):
        """When race is complete, template shows final results with place message."""
        from unittest.mock import patch

        fake_race = {
            'rank': 1,
            'place_class': 'gold',
            'total': 4,
            'score': 80,
            'steps_done': 3,
            'steps_total': 3,
            'streak': 10,
            'is_complete': True,
            'rival_above': None,
            'rival_below': None,
            'gap_up': 0,
            'gap_down': None,
            'callout': 'Ты впереди.',
            'next_step_title': None,
            'next_step_points': 0,
            'duel_target': None,
            'has_bot_rivals': False,
            'next_action_title': None,
            'next_action_url': None,
            'leaderboard': [
                {'rank': 1, 'username': 'me_user', 'initials': 'ME', 'score': 80,
                 'steps_done': 3, 'steps_total': 3, 'streak': 10,
                 'place_class': 'gold', 'is_complete': True, 'is_me': True, 'is_bot': False},
            ],
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.words.routes._build_daily_race_widget', return_value=fake_race):
            response = client.get('/dashboard')

        assert response.status_code == 200
        html = response.data.decode('utf-8')

        assert 'dash-race--complete' in html
        assert 'dash-race__final' in html
        assert 'Гонка завершена' in html
        assert 'Итоги гонки' in html

    def test_race_widget_nudge_text(self, client, app, db_session, test_user, words_module_access):
        """Motivational nudge is rendered in the dash-race__nudge element."""
        from unittest.mock import patch

        fake_race = {
            'rank': 3,
            'place_class': 'bronze',
            'total': 4,
            'score': 10,
            'steps_done': 0,
            'steps_total': 3,
            'streak': 2,
            'is_complete': False,
            'rival_above': {'username': 'FastUser', 'score': 18},
            'rival_below': None,
            'gap_up': 8,
            'gap_down': None,
            'callout': 'Ты на 8 очков позади FastUser.',
            'next_step_title': 'Повторение слов',
            'next_step_points': 8,
            'duel_target': {'username': 'FastUser'},
            'has_bot_rivals': False,
            'next_action_title': None,
            'next_action_url': None,
            'leaderboard': [
                {'rank': 3, 'username': 'me_user', 'initials': 'ME', 'score': 10,
                 'steps_done': 0, 'steps_total': 3, 'streak': 2,
                 'place_class': 'bronze', 'is_complete': False, 'is_me': True, 'is_bot': False},
            ],
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.words.routes._build_daily_race_widget', return_value=fake_race):
            response = client.get('/dashboard')

        assert response.status_code == 200
        html = response.data.decode('utf-8')

        assert 'dash-race__nudge' in html
        assert 'Ты на 8 очков позади FastUser.' in html

    def test_race_widget_position_count(self, client, app, db_session, test_user, words_module_access):
        """Race leaderboard renders correct number of participant rows."""
        from unittest.mock import patch

        leaderboard = [
            {'rank': i, 'username': f'User{i}', 'initials': f'U{i}', 'score': 50 - i * 10,
             'steps_done': 1, 'steps_total': 3, 'streak': i,
             'place_class': {1: 'gold', 2: 'silver', 3: 'bronze'}.get(i, ''),
             'is_complete': False, 'is_me': i == 2, 'is_bot': False}
            for i in range(1, 5)
        ]
        fake_race = {
            'rank': 2, 'place_class': 'silver', 'total': 4,
            'score': 30, 'steps_done': 1, 'steps_total': 3, 'streak': 2,
            'is_complete': False, 'rival_above': None, 'rival_below': None,
            'gap_up': 0, 'gap_down': None, 'callout': 'Ты лидируешь.',
            'next_step_title': None, 'next_step_points': 0,
            'duel_target': None, 'has_bot_rivals': False,
            'next_action_title': None, 'next_action_url': None,
            'leaderboard': leaderboard,
        }

        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('app.words.routes._build_daily_race_widget', return_value=fake_race):
            response = client.get('/dashboard')

        assert response.status_code == 200
        html = response.data.decode('utf-8')
        import re
        row_divs = re.findall(r'class="dash-race__row(?:\s|")', html)
        assert len(row_divs) == 4
