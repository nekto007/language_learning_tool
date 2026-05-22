"""
Tests for admin activity feed — activity_feed_service and activity_routes.
"""
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# activity_feed_service unit tests (no DB required)
# ---------------------------------------------------------------------------

class TestActivityFeedService:
    """Unit tests for get_recent_events with mocked DB sessions."""

    def _make_user(self, user_id=1, email='user@example.com'):
        u = MagicMock()
        u.id = user_id
        u.email = email
        return u

    def test_get_recent_events_empty(self):
        from app.admin.services.activity_feed_service import get_recent_events

        db_session = MagicMock()
        # Make every query chain return empty list
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = []
        db_session.query.return_value = mock_query

        events = get_recent_events(db_session, limit=50)
        assert events == []

    def test_get_recent_events_single_type_filter(self):
        from app.admin.services.activity_feed_service import get_recent_events, ActivityEvent

        db_session = MagicMock()
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = []
        db_session.query.return_value = mock_query

        # Only 'admin_action' type — should not call other sources
        events = get_recent_events(db_session, event_types=['admin_action'])
        assert events == []

    def test_get_recent_events_sorts_by_timestamp(self):
        from app.admin.services.activity_feed_service import get_recent_events, ActivityEvent

        ts1 = datetime(2026, 5, 1, 10, 0, tzinfo=UTC).replace(tzinfo=None)
        ts2 = datetime(2026, 5, 2, 10, 0, tzinfo=UTC).replace(tzinfo=None)
        ts3 = datetime(2026, 4, 30, 10, 0, tzinfo=UTC).replace(tzinfo=None)

        ev1 = ActivityEvent(timestamp=ts1, user_id=1, user_email='a@x.com', event_type='day_secured', description='d1')
        ev2 = ActivityEvent(timestamp=ts2, user_id=1, user_email='a@x.com', event_type='day_secured', description='d2')
        ev3 = ActivityEvent(timestamp=ts3, user_id=1, user_email='a@x.com', event_type='day_secured', description='d3')

        db_session = MagicMock()
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = [
            (MagicMock(secured_at=e.timestamp, plan_date='2026-05-01', mission_type=None), self._make_user())
            for e in [ev1, ev2, ev3]
        ]
        db_session.query.return_value = mock_query

        with patch('app.admin.services.activity_feed_service._fetch_lesson_completed', return_value=[ev1]), \
             patch('app.admin.services.activity_feed_service._fetch_achievements', return_value=[ev2]), \
             patch('app.admin.services.activity_feed_service._fetch_xp_events', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_day_secured', return_value=[ev3]), \
             patch('app.admin.services.activity_feed_service._fetch_admin_actions', return_value=[]):
            events = get_recent_events(db_session, limit=10)

        assert len(events) == 3
        assert events[0].timestamp == ts2  # newest first
        assert events[1].timestamp == ts1
        assert events[2].timestamp == ts3

    def test_get_recent_events_offset_and_limit(self):
        from app.admin.services.activity_feed_service import get_recent_events, ActivityEvent

        all_events = [
            ActivityEvent(
                timestamp=datetime(2026, 5, i, 10, 0),
                user_id=1, user_email='a@x.com',
                event_type='day_secured',
                description=f'd{i}',
            )
            for i in range(10, 0, -1)
        ]

        with patch('app.admin.services.activity_feed_service._fetch_lesson_completed', return_value=all_events), \
             patch('app.admin.services.activity_feed_service._fetch_achievements', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_xp_events', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_day_secured', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_admin_actions', return_value=[]):
            page1 = get_recent_events(MagicMock(), limit=3, offset=0)
            page2 = get_recent_events(MagicMock(), limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].description != page2[0].description

    def test_get_recent_events_source_exception_swallowed(self):
        from app.admin.services.activity_feed_service import get_recent_events

        def raise_error(*args, **kwargs):
            raise RuntimeError('DB down')

        with patch('app.admin.services.activity_feed_service._fetch_lesson_completed', side_effect=raise_error), \
             patch('app.admin.services.activity_feed_service._fetch_achievements', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_xp_events', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_day_secured', return_value=[]), \
             patch('app.admin.services.activity_feed_service._fetch_admin_actions', return_value=[]):
            # Should not raise, even when one source fails
            events = get_recent_events(MagicMock(), limit=10)
        assert events == []

    def test_all_event_types_list(self):
        from app.admin.services.activity_feed_service import ALL_EVENT_TYPES, EVENT_TYPE_LABELS
        assert set(ALL_EVENT_TYPES) == set(EVENT_TYPE_LABELS.keys())
        assert 'lesson_completed' in ALL_EVENT_TYPES
        assert 'admin_action' in ALL_EVENT_TYPES


# ---------------------------------------------------------------------------
# activity_routes integration tests (require Flask app + mock admin)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_admin_user():
    """Patch current_user in Flask-Login and the admin decorator to bypass auth."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.id = 999
    mock_user.username = 'mock_admin'
    with patch('app.admin.utils.decorators.current_user', mock_user), \
         patch('flask_login.utils.current_user', mock_user):
        yield mock_user


class TestActivityRoutes:
    """Integration tests for /admin/activity routes."""

    def test_activity_requires_admin(self, client):
        response = client.get('/admin/activity', follow_redirects=False)
        assert response.status_code in (302, 401)

    def test_activity_index_renders_for_admin(self, client, mock_admin_user):
        from app.admin.services.activity_feed_service import ActivityEvent

        fake_events = [
            ActivityEvent(
                timestamp=datetime(2026, 5, 20, 12, 0),
                user_id=1,
                user_email='student@example.com',
                event_type='lesson_completed',
                description='Завершил урок «Hello»',
            )
        ]

        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=fake_events):
            response = client.get('/admin/activity')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'student@example.com' in body
        assert 'Урок завершён' in body

    def test_activity_index_empty_shows_placeholder(self, client, mock_admin_user):
        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=[]):
            response = client.get('/admin/activity')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'Нет событий' in body

    def test_activity_filter_user_id_passed(self, client, mock_admin_user):
        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=[]) as mock_fn:
            client.get('/admin/activity?user_id=42')

        _, kwargs = mock_fn.call_args
        assert kwargs.get('user_id') == 42 or mock_fn.call_args[0][2] == 42  # positional or kw

    def test_activity_filter_event_types_passed(self, client, mock_admin_user):
        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=[]) as mock_fn:
            client.get('/admin/activity?event_types=day_secured&event_types=admin_action')

        call_kwargs = mock_fn.call_args[1]
        assert 'day_secured' in (call_kwargs.get('event_types') or [])
        assert 'admin_action' in (call_kwargs.get('event_types') or [])

    def test_activity_filter_invalid_user_id_ignored(self, client, mock_admin_user):
        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=[]) as mock_fn:
            response = client.get('/admin/activity?user_id=notanumber')

        assert response.status_code == 200
        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs.get('user_id') is None

    def test_activity_pagination_has_more(self, client, mock_admin_user):
        from app.admin.services.activity_feed_service import ActivityEvent

        # Return limit+1 events to trigger has_more
        fake_events = [
            ActivityEvent(
                timestamp=datetime(2026, 5, 20, 12, i),
                user_id=1,
                user_email=f'u{i}@x.com',
                event_type='xp_awarded',
                description=f'+10 XP',
            )
            for i in range(51)
        ]

        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=fake_events):
            response = client.get('/admin/activity')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'Вперёд' in body

    def test_activity_date_filter_parsed(self, client, mock_admin_user):
        with patch('app.admin.routes.activity_routes.get_recent_events', return_value=[]) as mock_fn:
            client.get('/admin/activity?date_from=2026-05-01&date_to=2026-05-31')

        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs.get('date_from') == datetime(2026, 5, 1)
        assert call_kwargs.get('date_to') == datetime(2026, 5, 31)
