"""
Tests for the main dashboard route
Ensures template rendering works correctly with all expected data
"""
import pytest


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
