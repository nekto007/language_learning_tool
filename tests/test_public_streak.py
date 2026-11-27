"""Tests for public streak page and calendar data."""
import pytest
import uuid
from datetime import UTC, datetime, timedelta
from flask import Flask, g
from freezegun import freeze_time
from sqlalchemy.orm import scoped_session
from app.auth.models import User
from app.achievements.models import StreakEvent
from app.curriculum.models import LessonProgress, Lessons, Module
from tests.support_dates import study_today


@pytest.fixture
def streak_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'strk_{suffix}', email=f'strk_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.flush()

    today = study_today()
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


def test_public_calendar_dates_follow_the_owner_for_guest_and_signed_in_viewer(
    app: Flask, db_session: scoped_session, test_user: User, admin_user: User, test_module: Module,
) -> None:
    owner, viewer = test_user, admin_user
    owner.timezone = 'Europe/Moscow'
    owner.profile_is_public = True
    viewer.timezone = 'UTC'
    viewer_client = app.test_client()
    with viewer_client.session_transaction() as session:
        session['_user_id'] = viewer.get_id()
        session['_fresh'] = True
    guest = app.test_client()
    path = f'/streak/{owner.username}'
    for number, instant, study_day, count in (
        (1, datetime(2026, 10, 20, 22, 59, tzinfo=UTC), '2026-10-20', 1),
        (2, datetime(2026, 10, 20, 23, 1, tzinfo=UTC), '2026-10-21', 2),
    ):
        lesson = Lessons(module_id=test_module.id, number=number, type='quiz', title='Synthetic boundary')
        db_session.add(lesson)
        db_session.flush()
        db_session.add(LessonProgress(user_id=owner.id, lesson_id=lesson.id, status='completed',
                                      last_activity=instant, completed_at=instant))
        db_session.commit()
        with freeze_time(instant):
            for client in (guest, viewer_client):
                g.pop('_login_user', None)
                response = client.get(path)
                assert response.status_code == 200
                html = response.get_data(as_text=True)
                assert f"""new Date("{study_day}" + 'T00:00:00Z')""" in html
                assert f'<div class="strk-stat__value">{count}</div>' in html
                active_dates = '["2026-10-20"]' if count == 1 else '["2026-10-20", "2026-10-21"]'
                assert f'var activeDates = {active_dates};' in html
