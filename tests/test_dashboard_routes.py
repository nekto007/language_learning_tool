"""
Tests for the main dashboard route
Ensures template rendering works correctly with all expected data
"""
import pytest
from unittest.mock import patch


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
            mock_hm.assert_called_once_with(test_user.id, days=90)
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
            assert '42' in html  # total_active_days
            assert '21' in html  # longest_streak


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
            mock_bst.assert_called_once_with(test_user.id)

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
            assert '60 ' in html  # 3600 seconds = 60 min
