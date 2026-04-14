"""Tests for public streak page and calendar data."""
import pytest
import uuid
from datetime import date, timedelta
from app.auth.models import User
from app.achievements.models import StreakEvent


@pytest.fixture
def streak_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'strk_{suffix}', email=f'strk_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.flush()

    today = date.today()
    for i in range(5):
        db_session.add(StreakEvent(
            user_id=user.id, event_type='earned_daily',
            coins_delta=1, event_date=today - timedelta(days=i),
        ))
    db_session.commit()
    return user


class TestStreakCalendarData:
    """Test get_streak_calendar function."""

    def test_returns_active_dates(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        cal = get_streak_calendar(streak_user.id)
        assert cal['total_active_days'] >= 5

    def test_current_streak(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        cal = get_streak_calendar(streak_user.id)
        assert cal['current_streak'] >= 5

    def test_longest_streak(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        cal = get_streak_calendar(streak_user.id)
        assert cal['longest_streak'] >= 5


class TestPublicStreakPage:
    """Test GET /streak/<username> route."""

    def test_returns_200(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        assert response.status_code == 200

    def test_no_login_required(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        assert response.status_code == 200

    def test_404_for_nonexistent(self, client):
        response = client.get('/streak/nonexistent_user_99999')
        assert response.status_code == 404

    def test_shows_streak_count(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'strk-hero' in html
        assert streak_user.username in html

    def test_has_og_tags(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'og:title' in html

    def test_has_share_buttons(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'share-btn' in html

    def test_has_register_cta(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'register' in html.lower()
