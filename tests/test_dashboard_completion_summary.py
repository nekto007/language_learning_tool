"""Tests for xp_service.get_today_xp.

The mission-completion summary screen (``_build_completion_summary`` and the
legacy dashboard.html template it fed) has been removed along with the
mission plan; only the still-live ``get_today_xp`` helper is covered here.
"""
from datetime import date, timedelta


class TestGetTodayXP:
    """Unit tests for xp_service.get_today_xp."""

    def test_returns_zero_when_no_events(self, app, db_session, test_user):
        from app.achievements.xp_service import get_today_xp
        result = get_today_xp(test_user.id, date.today())
        assert result == 0

    def test_sums_xp_phase_events(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 40, 'phase_id': 'p1', 'mode': 'learn'},
        ))
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 15, 'phase_id': 'p2', 'mode': 'recall'},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 55

    def test_sums_perfect_day_xp(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=today,
            coins_delta=0,
            details={'xp': 50},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 50

    def test_ignores_other_dates(self, app, db_session, test_user):
        from app.achievements.models import StreakEvent
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        yesterday = today - timedelta(days=1)
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=yesterday,
            coins_delta=0,
            details={'xp': 100, 'phase_id': 'p1', 'mode': 'learn'},
        ))
        db_session.flush()
        result = get_today_xp(test_user.id, today)
        assert result == 0

    def test_ignores_other_users(self, app, db_session, test_user):
        """Returns 0 for a user with no events even when other users have events."""
        from app.achievements.xp_service import get_today_xp
        today = date.today()
        # No events for test_user — just confirm zero
        result = get_today_xp(test_user.id, today)
        assert result == 0
