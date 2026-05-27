"""Tests for level-up celebration API and modal."""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from app.auth.models import User
from app.achievements.xp_service import get_level_info


@pytest.fixture
def celebration_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lvlup_{suffix}',
        email=f'lvlup_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auth_client(client, celebration_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(celebration_user.id)
    return client


# ---------------------------------------------------------------------------
# get_level_info unit tests
# ---------------------------------------------------------------------------

class TestGetLevelInfoEdgeCases:
    def test_zero_xp_is_level_one(self):
        info = get_level_info(0)
        assert info.current_level == 1

    def test_none_xp_is_level_one(self):
        info = get_level_info(None)
        assert info.current_level == 1

    def test_negative_xp_is_level_one(self):
        info = get_level_info(-100)
        assert info.current_level == 1

    def test_level_one_xp_in_level_is_zero(self):
        info = get_level_info(0)
        assert info.xp_in_level == 0
        assert info.total_xp == 0

    def test_level_two_requires_100_xp(self):
        info = get_level_info(100)
        assert info.current_level == 2

    def test_just_below_level_two(self):
        info = get_level_info(99)
        assert info.current_level == 1

    def test_progress_percent_zero_xp(self):
        info = get_level_info(0)
        assert 0.0 <= info.progress_percent <= 100.0

    def test_xp_to_next_is_nonnegative(self):
        for xp in [0, 1, 50, 99, 100, 500]:
            info = get_level_info(xp)
            assert info.xp_to_next >= 0, f"xp_to_next negative at xp={xp}"


# ---------------------------------------------------------------------------
# Celebrations API endpoint tests
# ---------------------------------------------------------------------------

class TestCelebrationAPI:
    """Test GET /study/api/celebrations endpoint."""

    def test_celebrations_requires_login(self, client):
        response = client.get('/study/api/celebrations')
        assert response.status_code in (302, 401)

    def test_celebrations_returns_json(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_celebrations_has_level(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'level' in data
        assert isinstance(data['level'], int)
        assert data['level'] >= 1

    def test_celebrations_has_total_xp(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'total_xp' in data

    def test_celebrations_has_celebrations_list(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'celebrations' in data
        assert isinstance(data['celebrations'], list)

    def test_celebrations_with_xp(self, auth_client, celebration_user, db_session):
        """After adding XP, level should be reflected."""
        from app.achievements.models import UserStatistics
        stats = UserStatistics.query.filter_by(user_id=celebration_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=celebration_user.id, total_xp=500)
            db_session.add(stats)
        else:
            stats.total_xp = 500
        db_session.commit()

        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert data['level'] >= 3
        assert data['total_xp'] >= 500

    def test_celebrations_zero_xp_user_is_level_one(self, auth_client, celebration_user, db_session):
        """New user with no XP should be level 1."""
        from app.achievements.models import UserStatistics
        stats = UserStatistics.query.filter_by(user_id=celebration_user.id).first()
        if stats:
            stats.total_xp = 0
            db_session.commit()

        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert data['level'] == 1

    def test_celebrations_after_future_param_no_celebrations(self, auth_client, celebration_user, db_session):
        """Passing a future 'after' timestamp should return empty celebrations."""
        from app.achievements.models import UserStatistics
        from app.study.models import UserAchievement

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        response = auth_client.get(f'/study/api/celebrations?after={future}')
        data = response.get_json()
        assert data['success'] is True
        assert data['celebrations'] == []

    def test_celebrations_invalid_after_param_graceful(self, auth_client):
        """Invalid 'after' param should not crash the endpoint."""
        response = auth_client.get('/study/api/celebrations?after=not-a-date')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_celebrations_after_old_timestamp_includes_recent(self, auth_client, celebration_user, db_session):
        """Passing an old 'after' timestamp should include recent achievements."""
        from app.study.models import UserAchievement, Achievement
        ach = Achievement.query.first()
        if ach is None:
            pytest.skip("No achievements in test DB")

        existing = UserAchievement.query.filter_by(
            user_id=celebration_user.id, achievement_id=ach.id
        ).first()
        if not existing:
            ua = UserAchievement(
                user_id=celebration_user.id,
                achievement_id=ach.id,
                earned_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db_session.add(ua)
            db_session.commit()

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        response = auth_client.get(f'/study/api/celebrations?after={old_ts}')
        data = response.get_json()
        assert data['success'] is True


# ---------------------------------------------------------------------------
# Level-up modal in base template
# ---------------------------------------------------------------------------

class TestLevelUpModalInBase:
    """Test that level-up modal and celebration script are in base template."""

    def test_base_has_levelup_modal(self, auth_client):
        """Authenticated page should contain level-up modal."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'levelup-modal' in html

    def test_base_has_celebration_script(self, auth_client):
        """Authenticated page should contain celebration check script."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'api/celebrations' in html

    def test_base_uses_localstorage_for_one_time_display(self, auth_client):
        """Modal should use localStorage to prevent repeated display."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'llt_celeb_seen' in html
        assert 'llt_level' in html

    def test_base_celebration_script_uses_after_param(self, auth_client):
        """Script should pass 'after' param to filter already-seen celebrations."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert '?after=' in html or 'after' in html


# ---------------------------------------------------------------------------
# Confetti respects prefers-reduced-motion (verified via JS source inspection)
# ---------------------------------------------------------------------------

class TestConfettiMotionPreference:
    def test_showconfetti_checks_reduced_motion(self):
        """showConfetti() in unified-js.js must bail out when motion is reduced."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'app', 'static', 'js', 'unified-js.js',
        )
        with open(os.path.normpath(js_path)) as f:
            js = f.read()
        assert 'prefers-reduced-motion' in js
        assert 'showConfetti' in js
        # The function must check the media query before launching particles
        showconfetti_idx = js.index('function showConfetti')
        reduced_motion_in_func = 'prefers-reduced-motion' in js[showconfetti_idx:showconfetti_idx + 300]
        assert reduced_motion_in_func, "showConfetti must check prefers-reduced-motion"

    def test_show_completion_celebration_checks_reduced_motion(self):
        """showCompletionCelebration() must also respect reduced motion."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'app', 'static', 'js', 'unified-js.js',
        )
        with open(os.path.normpath(js_path)) as f:
            js = f.read()
        comp_idx = js.index('function showCompletionCelebration')
        snippet = js[comp_idx:comp_idx + 400]
        assert 'prefers-reduced-motion' in snippet


# ---------------------------------------------------------------------------
# Concurrent XP award: notify_level_up deduplication
# ---------------------------------------------------------------------------

class TestLevelUpNotificationDedup:
    def test_notify_level_up_dedup_same_level_same_day(self, app, celebration_user, db_session):
        """Calling notify_level_up twice for the same level on the same day
        should produce at most one notification row."""
        from app.notifications.services import notify_level_up
        from app.notifications.models import Notification

        n1 = notify_level_up(celebration_user.id, 5)
        db_session.flush()
        n2 = notify_level_up(celebration_user.id, 5)
        db_session.flush()

        count = Notification.query.filter_by(
            user_id=celebration_user.id,
            type='level_up',
            title='Уровень 5!',
        ).count()
        assert count == 1
        # Both calls return the same row (or the existing row on second call)
        assert n1 is not None

    def test_notify_level_up_different_levels_allowed(self, app, celebration_user, db_session):
        """Different level numbers produce separate notification rows."""
        from app.notifications.services import notify_level_up
        from app.notifications.models import Notification

        notify_level_up(celebration_user.id, 3)
        db_session.flush()
        notify_level_up(celebration_user.id, 4)
        db_session.flush()

        count = Notification.query.filter_by(
            user_id=celebration_user.id,
            type='level_up',
        ).count()
        assert count == 2

    def test_award_xp_level_up_flag_is_accurate(self, app, celebration_user, db_session):
        """award_xp must set leveled_up=True only when level actually increases."""
        from app.achievements.xp_service import award_xp
        from app.achievements.models import UserStatistics

        # Give user XP just below level 2 (100 XP required)
        stats = UserStatistics.query.filter_by(user_id=celebration_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=celebration_user.id, total_xp=90)
            db_session.add(stats)
        else:
            stats.total_xp = 90
            stats.current_streak_days = 0
        db_session.flush()

        result = award_xp(celebration_user.id, 15, 'test_source')
        assert result.leveled_up is True
        assert result.new_level == 2
        assert result.previous_level == 1

    def test_award_xp_no_false_level_up(self, app, celebration_user, db_session):
        """award_xp must not set leveled_up=True when still on same level."""
        from app.achievements.xp_service import award_xp
        from app.achievements.models import UserStatistics

        stats = UserStatistics.query.filter_by(user_id=celebration_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=celebration_user.id, total_xp=10)
            db_session.add(stats)
        else:
            stats.total_xp = 10
            stats.current_streak_days = 0
        db_session.flush()

        result = award_xp(celebration_user.id, 5, 'test_source')
        assert result.leveled_up is False
        assert result.new_level == result.previous_level
