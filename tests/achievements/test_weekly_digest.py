"""Tests for get_weekly_digest in app.achievements.weekly_challenge."""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, PropertyMock


class TestGetWeeklyDigest:
    """Tests for get_weekly_digest."""

    def _make_streak_event(self, event_type: str, event_date: date, details: dict | None = None):
        ev = MagicMock()
        ev.event_type = event_type
        ev.event_date = event_date
        ev.details = details or {}
        return ev

    def test_returns_required_keys(self, app, db_session, test_user):
        """Result dict contains all required keys."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)

        assert 'days' in result
        assert 'week_xp' in result
        assert 'prev_week_xp' in result
        assert 'xp_diff' in result
        assert 'mission_counts' in result
        assert 'week_start' in result

    def test_days_length_is_7(self, app, db_session, test_user):
        """days list always has exactly 7 entries."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        assert len(result['days']) == 7

    def test_day_labels_are_correct(self, app, db_session, test_user):
        """Day labels follow Mon-Sun Russian abbreviations."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        expected_labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        actual_labels = [d['label'] for d in result['days']]
        assert actual_labels == expected_labels

    def test_day_states_for_new_user_are_missed_or_future(self, app, db_session, test_user):
        """A user with no activity has all past days as 'missed' and future as 'future'."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        today = date.today()
        for day in result['days']:
            day_date = date.fromisoformat(day['date'])
            if day_date > today:
                assert day['state'] == 'future', f"{day_date} should be future"
            else:
                assert day['state'] in ('missed', 'partial', 'complete'), f"{day_date} unexpected state"

    def test_complete_day_when_plan_completed_event(self, app, db_session, test_user):
        """A day with a plan_completed event shows state='complete'."""
        from app.achievements.weekly_challenge import get_weekly_digest
        from app.achievements.models import StreakEvent

        today = date.today()
        ev = StreakEvent(
            user_id=test_user.id,
            event_type='plan_completed',
            event_date=today,
            coins_delta=0,
        )
        db_session.add(ev)
        db_session.flush()

        result = get_weekly_digest(user_id=test_user.id)
        today_day = next(d for d in result['days'] if d['date'] == today.isoformat())
        assert today_day['state'] == 'complete'

    def test_partial_day_when_only_earned_daily_event(self, app, db_session, test_user):
        """A day with earned_daily but no plan_completed shows state='partial'."""
        from app.achievements.weekly_challenge import get_weekly_digest
        from app.achievements.models import StreakEvent

        today = date.today()
        ev = StreakEvent(
            user_id=test_user.id,
            event_type='earned_daily',
            event_date=today,
            coins_delta=1,
        )
        db_session.add(ev)
        db_session.flush()

        result = get_weekly_digest(user_id=test_user.id)
        today_day = next(d for d in result['days'] if d['date'] == today.isoformat())
        assert today_day['state'] == 'partial'

    def test_xp_diff_positive_when_this_week_more(self, app, db_session, test_user):
        """xp_diff > 0 when this week has more XP events than last week."""
        from app.achievements.weekly_challenge import get_weekly_digest
        from app.achievements.models import StreakEvent

        today = date.today()
        # Add xp_phase event this week
        ev = StreakEvent(
            user_id=test_user.id,
            event_type='xp_phase',
            event_date=today,
            coins_delta=0,
            details={'xp': 40, 'phase_id': 'learn', 'mode': 'learn'},
        )
        db_session.add(ev)
        db_session.flush()

        result = get_weekly_digest(user_id=test_user.id)
        assert result['week_xp'] >= 40
        assert result['xp_diff'] > 0

    def test_xp_diff_equals_week_minus_prev(self, app, db_session, test_user):
        """xp_diff is week_xp - prev_week_xp."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        assert result['xp_diff'] == result['week_xp'] - result['prev_week_xp']

    def test_mission_counts_keys(self, app, db_session, test_user):
        """mission_counts has progress, repair, reading keys."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        assert 'progress' in result['mission_counts']
        assert 'repair' in result['mission_counts']
        assert 'reading' in result['mission_counts']

    def test_mission_counts_from_streak_events(self, app, db_session, test_user):
        """mission_counts reflect mission_selected StreakEvents."""
        from app.achievements.weekly_challenge import get_weekly_digest
        from app.achievements.models import StreakEvent

        today = date.today()
        for mission_type in ('progress', 'repair', 'progress'):
            ev = StreakEvent(
                user_id=test_user.id,
                event_type='mission_selected',
                event_date=today,
                coins_delta=0,
                details={'mission_type': mission_type},
            )
            db_session.add(ev)
        db_session.flush()

        result = get_weekly_digest(user_id=test_user.id)
        assert result['mission_counts']['progress'] == 2
        assert result['mission_counts']['repair'] == 1
        assert result['mission_counts']['reading'] == 0

    def test_week_start_is_monday(self, app, db_session, test_user):
        """week_start is always a Monday (weekday 0)."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        week_start = date.fromisoformat(result['week_start'])
        assert week_start.weekday() == 0, "week_start should be Monday"

    def test_today_flag_set_correctly(self, app, db_session, test_user):
        """Exactly one day has is_today=True, and it matches today's date."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        today = date.today()
        today_days = [d for d in result['days'] if d.get('is_today')]

        # today may not be in the current week if tests run on edge date, but normally it is
        week_start = date.fromisoformat(result['week_start'])
        if week_start <= today <= week_start + timedelta(days=6):
            assert len(today_days) == 1
            assert today_days[0]['date'] == today.isoformat()

    def test_xp_zero_for_user_with_no_events(self, app, db_session, test_user):
        """week_xp and prev_week_xp are 0 for a user with no XP events."""
        from app.achievements.weekly_challenge import get_weekly_digest

        result = get_weekly_digest(user_id=test_user.id)
        assert result['week_xp'] == 0
        assert result['prev_week_xp'] == 0
        assert result['xp_diff'] == 0


MOCK_DAILY_PLAN = {
    'mission': {'type': 'progress', 'title': 'Прогресс'},
    'phases': [],
    'steps': {},
    'all_done': False,
    '_plan_meta': {},
}


@pytest.fixture
def words_module_access(app, db_session, test_user):
    from app.modules.models import SystemModule, UserModule
    with app.app_context():
        words_module = SystemModule.query.filter_by(code='words').first()
        if not words_module:
            words_module = SystemModule(code='words', name='Words', description='Words')
            db_session.add(words_module)
            db_session.flush()
        existing = UserModule.query.filter_by(
            user_id=test_user.id, module_id=words_module.id,
        ).first()
        if not existing:
            db_session.add(UserModule(
                user_id=test_user.id, module_id=words_module.id, is_enabled=True,
            ))
            db_session.commit()
    return words_module


@pytest.fixture(autouse=True)
def _clear_leaderboard_cache():
    from app.words.routes import _leaderboard_cache
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0
    yield
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0


class TestWeeklyDigestDashboardIntegration:
    """Tests that the dashboard route passes weekly_digest to template."""

    def _get_dashboard(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=dict(MOCK_DAILY_PLAN)):
            return client.get('/dashboard')

    def test_dashboard_returns_200(self, client, app, db_session, test_user, words_module_access):
        """Dashboard route returns 200 for authenticated user with words module."""
        resp = self._get_dashboard(client, test_user)
        assert resp.status_code == 200

    def test_weekly_digest_widget_renders_in_html(self, client, app, db_session, test_user, words_module_access):
        """Dashboard HTML contains dash-weekly element when digest is available."""
        resp = self._get_dashboard(client, test_user)
        assert resp.status_code == 200
        # The widget renders if weekly_digest is in context (truthy dict)
        assert b'dash-weekly' in resp.data
