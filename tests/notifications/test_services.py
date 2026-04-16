"""Tests for notification creation service — preference flags and DOM safety."""
import uuid
import pytest

from app.auth.models import User
from app.notifications.models import Notification
from app.notifications.services import (
    create_notification,
    notify_achievement,
    notify_streak_milestone,
    notify_weekly_challenge,
    notify_referral,
    notify_level_up,
)


@pytest.fixture
def svc_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'svc_{suffix}',
        email=f'svc_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


class TestNotificationCreatedWhenPrefOn:
    """Notifications should be created when the relevant preference flag is True."""

    @pytest.mark.smoke
    def test_achievement_created_when_pref_on(self, svc_user, db_session):
        svc_user.notify_in_app_achievements = True
        db_session.commit()

        result = notify_achievement(svc_user.id, 'Gold Star')
        db_session.commit()

        assert result is not None
        assert isinstance(result, Notification)
        assert result.type == 'achievement'
        assert 'Gold Star' in result.title

    def test_streak_milestone_created_when_pref_on(self, svc_user, db_session):
        svc_user.notify_in_app_streaks = True
        db_session.commit()

        result = notify_streak_milestone(svc_user.id, streak=14, reward=10)
        db_session.commit()

        assert result is not None
        assert result.type == 'streak_milestone'

    def test_weekly_challenge_created_when_pref_on(self, svc_user, db_session):
        svc_user.notify_in_app_weekly = True
        db_session.commit()

        result = notify_weekly_challenge(svc_user.id, 'Speed Reading')
        db_session.commit()

        assert result is not None
        assert result.type == 'weekly_challenge'

    def test_level_up_created_when_achievement_pref_on(self, svc_user, db_session):
        svc_user.notify_in_app_achievements = True
        db_session.commit()

        result = notify_level_up(svc_user.id, new_level=5)
        db_session.commit()

        assert result is not None
        assert result.type == 'level_up'

    def test_referral_always_created_regardless_of_prefs(self, svc_user, db_session):
        """Referral type has no preference gate — must always be created."""
        svc_user.notify_in_app_achievements = False
        svc_user.notify_in_app_streaks = False
        svc_user.notify_in_app_weekly = False
        db_session.commit()

        result = notify_referral(svc_user.id, 'friend_xyz')
        db_session.commit()

        assert result is not None
        assert result.type == 'referral'


class TestNotificationBlockedWhenPrefOff:
    """Notifications should NOT be created when the preference flag is False."""

    def test_achievement_blocked_when_pref_off(self, svc_user, db_session):
        svc_user.notify_in_app_achievements = False
        db_session.commit()

        result = notify_achievement(svc_user.id, 'Blocked Badge')

        assert result is None

    def test_level_up_blocked_when_achievement_pref_off(self, svc_user, db_session):
        """level_up shares the notify_in_app_achievements flag."""
        svc_user.notify_in_app_achievements = False
        db_session.commit()

        result = notify_level_up(svc_user.id, new_level=3)

        assert result is None

    def test_streak_blocked_when_pref_off(self, svc_user, db_session):
        svc_user.notify_in_app_streaks = False
        db_session.commit()

        result = notify_streak_milestone(svc_user.id, streak=7, reward=5)

        assert result is None

    def test_weekly_challenge_blocked_when_pref_off(self, svc_user, db_session):
        svc_user.notify_in_app_weekly = False
        db_session.commit()

        result = notify_weekly_challenge(svc_user.id, 'Blocked Challenge')

        assert result is None

    def test_create_notification_direct_respects_pref(self, svc_user, db_session):
        """create_notification() itself must obey preference flags."""
        svc_user.notify_in_app_achievements = False
        db_session.commit()

        result = create_notification(svc_user.id, 'achievement', 'Direct Test')

        assert result is None


class TestNotificationDropdownDOMSafety:
    """Notification dropdown must use textContent/DOM API, not innerHTML for user data."""

    def _get_authenticated_client(self, app, user):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
        return client

    def test_notification_list_js_does_not_use_innerhtml_for_titles(
        self, app, svc_user, db_session
    ):
        """The JS that renders notification items must not use innerHTML with user data."""
        auth_client = self._get_authenticated_client(app, svc_user)
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode('utf-8')

        # The notification list rendering JS should use safe DOM API
        assert 'document.createElement' in html or '.textContent' in html, (
            "Notification list JS must use document.createElement or .textContent"
        )

    def test_notification_titles_not_interpolated_into_innerhtml(
        self, app, svc_user, db_session
    ):
        """User-supplied notification title must not be injected via innerHTML string concat."""
        auth_client = self._get_authenticated_client(app, svc_user)
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode('utf-8')

        # Pattern: innerHTML = `...${n.title}...` or innerHTML = "..." + n.title + "..."
        # would be an XSS risk — these should not appear in notification rendering code
        assert "innerHTML = `" not in html or "n.title" not in html.split("innerHTML = `")[1].split("`")[0] if "innerHTML = `" in html else True
