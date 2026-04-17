"""Tests for profile page enhancements: learning stats, settings, referral stats."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.auth.routes import _get_profile_stats, TIMEZONE_CHOICES
from app.utils.db import db


@pytest.fixture
def profile_user(db_session):
    """Create a user for profile tests."""
    username = f'profile_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
        last_login=datetime.now(timezone.utc),
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auth_client(app, client, profile_user):
    """Authenticated client for profile_user."""
    from flask_login import login_user
    with app.test_request_context():
        login_user(profile_user)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(profile_user.id)
            sess['_fresh'] = True
    return client


class TestGetProfileStats:
    """Test _get_profile_stats aggregation."""

    def test_empty_user_stats(self, app, db_session, profile_user):
        """User with no activity returns zeros."""
        with app.app_context():
            with patch('app.telegram.queries.get_current_streak', return_value=0):
                stats = _get_profile_stats(profile_user.id)

        assert stats['total_words'] == 0
        assert stats['lessons_completed'] == 0
        assert stats['xp_level'] == 1
        assert stats['total_xp'] == 0
        assert stats['current_streak'] == 0
        assert stats['longest_streak'] == 0

    def test_stats_with_words_and_lessons(self, app, db_session, profile_user):
        """User with words and completed lessons gets correct counts."""
        from app.study.models import UserWord
        from app.curriculum.models import LessonProgress, Lessons, Module, CEFRLevel

        # Create a lesson and mark it completed
        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db_session.add(level)
        db_session.flush()

        module = Module(
            title='Test Module', number=1, level_id=level.id,
        )
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(
            title='Test Lesson', type='vocabulary',
            number=1, order=1, module_id=module.id
        )
        db_session.add(lesson)
        db_session.flush()

        lp = LessonProgress(
            user_id=profile_user.id, lesson_id=lesson.id,
            status='completed', score=85.0,
            completed_at=datetime.now(timezone.utc)
        )
        db_session.add(lp)
        db_session.flush()

        # Add a word
        from app.words.models import CollectionWords
        word = CollectionWords(
            english_word=f'test_{uuid.uuid4().hex[:6]}',
            russian_word='тест', level='A1'
        )
        db_session.add(word)
        db_session.flush()

        uw = UserWord(user_id=profile_user.id, word_id=word.id)
        uw.status = 'learning'
        db_session.add(uw)
        db_session.commit()

        with app.app_context():
            with patch('app.telegram.queries.get_current_streak', return_value=5):
                stats = _get_profile_stats(profile_user.id)

        assert stats['total_words'] == 1
        assert stats['lessons_completed'] == 1
        assert stats['current_streak'] == 5

    def test_streak_record_uses_max(self, app, db_session, profile_user):
        """longest_streak returns max of UserStatistics and current streak."""
        from app.achievements.models import UserStatistics

        user_stats = UserStatistics(
            user_id=profile_user.id,
            longest_streak_days=20,
            current_streak_days=5,
        )
        db_session.add(user_stats)
        db_session.commit()

        with app.app_context():
            with patch('app.telegram.queries.get_current_streak', return_value=3):
                stats = _get_profile_stats(profile_user.id)

        assert stats['longest_streak'] == 20  # max(20, 3)

    def test_streak_record_current_higher(self, app, db_session, profile_user):
        """If current streak exceeds stored record, use current."""
        from app.achievements.models import UserStatistics

        user_stats = UserStatistics(
            user_id=profile_user.id,
            longest_streak_days=5,
        )
        db_session.add(user_stats)
        db_session.commit()

        with app.app_context():
            with patch('app.telegram.queries.get_current_streak', return_value=10):
                stats = _get_profile_stats(profile_user.id)

        assert stats['longest_streak'] == 10


class TestProfileRoute:
    """Test profile page rendering."""

    def test_profile_renders_stats(self, app, auth_client, profile_user):
        """Profile page renders learning stats."""
        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Статистика обучения' in html or 'stats' in html.lower()
        assert 'Аккаунт' in html

    def test_profile_renders_account_info(self, app, auth_client, profile_user):
        """Profile page shows registration date and last login."""
        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        html = resp.data.decode()
        assert 'Дата регистрации' in html
        assert 'Последний вход' in html
        assert 'Возраст аккаунта' in html

    def test_profile_renders_settings(self, app, auth_client, profile_user):
        """Profile page shows timezone and daily goal settings."""
        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        html = resp.data.decode()
        assert 'Часовой пояс' in html or 'timezone' in html.lower()
        assert 'daily_goal_minutes' in html

    def test_profile_renders_notifications(self, app, auth_client, profile_user):
        """Profile page shows notification preferences."""
        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        html = resp.data.decode()
        assert 'Уведомления' in html
        assert 'notify_email_reminders' in html


class TestProfileRankSection:
    """Profile page shows the rank badge, progress bar, and history timeline."""

    def test_rank_section_present_for_new_user(self, app, auth_client, profile_user):
        """A user with no completions still sees the Novice badge."""
        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Звание' in html
        assert 'pf-rank' in html
        assert 'Новичок' in html

    def test_rank_section_shows_current_rank_and_days(
        self, app, db_session, auth_client, profile_user,
    ):
        """Current rank and days-at-rank are rendered from StreakEvents."""
        from datetime import date, timedelta

        from app.achievements.models import StreakEvent, UserStatistics

        db_session.add(UserStatistics(
            user_id=profile_user.id,
            plans_completed_total=8,
            current_rank='explorer',
        ))
        db_session.add(StreakEvent(
            user_id=profile_user.id,
            event_type='plan_completed',
            coins_delta=0,
            event_date=date.today() - timedelta(days=3),
            details={'plans_completed_total': 7, 'rank_code': 'explorer'},
        ))
        db_session.flush()

        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        assert resp.status_code == 200
        html = resp.data.decode()

        assert 'Исследователь' in html
        assert 'data-rank-days="3"' in html
        # progress text: 8 / 21 to student
        assert '8/21' in html
        assert 'Ученик' in html  # next rank display

    def test_rank_section_shows_history_timeline(
        self, app, db_session, auth_client, profile_user,
    ):
        """Rank history timeline lists every distinct promotion."""
        from datetime import date, timedelta

        from app.achievements.models import StreakEvent, UserStatistics

        today = date.today()
        db_session.add(UserStatistics(
            user_id=profile_user.id,
            plans_completed_total=21,
            current_rank='student',
        ))
        for offset, total, code in [
            (-10, 1, 'novice'),
            (-5, 7, 'explorer'),
            (-1, 21, 'student'),
        ]:
            db_session.add(StreakEvent(
                user_id=profile_user.id,
                event_type='plan_completed',
                coins_delta=0,
                event_date=today + timedelta(days=offset),
                details={'plans_completed_total': total, 'rank_code': code},
            ))
        db_session.flush()

        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        html = resp.data.decode()
        assert 'История званий' in html
        assert 'pf-rank__timeline' in html
        assert 'Новичок' in html
        assert 'Исследователь' in html
        assert 'Ученик' in html
        assert (today - timedelta(days=10)).strftime('%d.%m.%Y') in html

    def test_rank_section_hides_progress_for_grandmaster(
        self, app, db_session, auth_client, profile_user,
    ):
        """When a user maxes out, we show the max-rank hint instead of a bar."""
        from app.achievements.models import UserStatistics

        db_session.add(UserStatistics(
            user_id=profile_user.id,
            plans_completed_total=400,
            current_rank='grandmaster',
        ))
        db_session.flush()

        with patch('app.telegram.queries.get_current_streak', return_value=0):
            resp = auth_client.get('/profile')
        html = resp.data.decode()
        assert 'Грандмастер' in html
        assert 'Максимальное звание достигнуто' in html


class TestProfileSettingsSave:
    """Test saving profile settings via POST."""

    def test_save_timezone(self, app, auth_client, profile_user):
        """Saving timezone updates user model."""
        resp = auth_client.post('/profile', data={
            'section': 'settings',
            'timezone': 'Europe/London',
            'daily_goal_minutes': '30',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            user = db.session.get(User, profile_user.id)
            assert user.timezone == 'Europe/London'
            assert user.daily_goal_minutes == 30

    def test_invalid_timezone_rejected(self, app, auth_client, profile_user):
        """Invalid timezone is not saved."""
        auth_client.post('/profile', data={
            'section': 'settings',
            'timezone': 'Invalid/Zone',
            'daily_goal_minutes': '15',
        }, follow_redirects=True)

        with app.app_context():
            user = db.session.get(User, profile_user.id)
            # Should not have changed to invalid timezone
            assert user.timezone != 'Invalid/Zone'

    def test_daily_goal_out_of_range(self, app, auth_client, profile_user):
        """Daily goal outside 5-120 is not saved."""
        original = profile_user.daily_goal_minutes
        auth_client.post('/profile', data={
            'section': 'settings',
            'timezone': 'UTC',
            'daily_goal_minutes': '999',
        }, follow_redirects=True)

        with app.app_context():
            user = db.session.get(User, profile_user.id)
            assert user.daily_goal_minutes != 999

    def test_save_notification_prefs(self, app, auth_client, profile_user):
        """Saving notification preferences toggles correctly."""
        # Uncheck all
        resp = auth_client.post('/profile', data={
            'section': 'notifications',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            user = db.session.get(User, profile_user.id)
            assert user.notify_email_reminders is False
            assert user.notify_in_app_achievements is False
            assert user.notify_in_app_streaks is False
            assert user.notify_in_app_weekly is False

    def test_save_notification_prefs_checked(self, app, auth_client, profile_user):
        """Saving with checkboxes checked sets True."""
        resp = auth_client.post('/profile', data={
            'section': 'notifications',
            'notify_email_reminders': 'on',
            'notify_in_app_achievements': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            user = db.session.get(User, profile_user.id)
            assert user.notify_email_reminders is True
            assert user.notify_in_app_achievements is True
            assert user.notify_in_app_streaks is False
            assert user.notify_in_app_weekly is False


class TestReferralStats:
    """Test referral stats on referrals page."""

    def test_referrals_page_with_no_referrals(self, app, auth_client, profile_user):
        """Referrals page renders with 0 referrals."""
        resp = auth_client.get('/referrals')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Активных' in html or 'active_referred' in html.lower()

    def test_referrals_with_active_users(self, app, db_session, auth_client, profile_user):
        """Active referred users are counted correctly."""
        # Ensure referral code exists
        profile_user.ensure_referral_code()

        # Create referred users
        active_user = User(
            username=f'ref_active_{uuid.uuid4().hex[:8]}',
            email=f'ref_active_{uuid.uuid4().hex[:8]}@example.com',
            active=True,
            referred_by_id=profile_user.id,
            last_login=datetime.now(timezone.utc) - timedelta(days=5),
        )
        active_user.set_password('pass123')

        inactive_user = User(
            username=f'ref_inactive_{uuid.uuid4().hex[:8]}',
            email=f'ref_inactive_{uuid.uuid4().hex[:8]}@example.com',
            active=True,
            referred_by_id=profile_user.id,
            last_login=datetime.now(timezone.utc) - timedelta(days=60),
        )
        inactive_user.set_password('pass123')

        db_session.add_all([active_user, inactive_user])
        db_session.commit()

        resp = auth_client.get('/referrals')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Should show 2 total, 1 active, 200 XP
        assert '200' in html  # total XP

    def test_referrals_xp_calculation(self, app, db_session, auth_client, profile_user):
        """XP earned from referrals = count * 100."""
        profile_user.ensure_referral_code()

        for i in range(3):
            u = User(
                username=f'ref_{i}_{uuid.uuid4().hex[:8]}',
                email=f'ref_{i}_{uuid.uuid4().hex[:8]}@example.com',
                active=True,
                referred_by_id=profile_user.id,
            )
            u.set_password('pass123')
            db_session.add(u)
        db_session.commit()

        resp = auth_client.get('/referrals')
        html = resp.data.decode()
        assert '300' in html  # 3 * 100 XP
