"""Tests for listening goal fields in /api/daily-status response."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


def _linear_plan() -> dict:
    return {
        'mode': 'linear',
        'position': {
            'lesson_id': 101,
            'lesson_type': 'card',
            'lesson_number': 3,
            'module_id': 50,
            'module_number': 5,
            'level_code': 'B1',
        },
        'progress': {'level': 'B1', 'percent': 20, 'lessons_remaining_in_level': 60},
        'baseline_slots': [
            {
                'kind': 'srs',
                'title': 'Карточки на повторение',
                'eta_minutes': 5,
                'url': '/study?source=linear_plan',
                'completed': False,
                'data': {'due_count': 3},
            },
        ],
        'continuation': {'available': False, 'next_lessons': []},
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': False,
            'effective_mode': 'linear',
            'fallback_reason': None,
        },
    }


def _empty_summary() -> dict:
    return {
        'lessons_count': 0,
        'lesson_types': [],
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'srs_new_reviewed': 0,
        'srs_review_reviewed': 0,
        'grammar_exercises': 0,
        'grammar_correct': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }


class TestListeningGoalInDailyStatus:
    """Test listening_goal_minutes, listening_minutes_today, listening_goal_reached in /api/daily-status."""

    def _base_patches(self):
        plan = _linear_plan()
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
        ]

    def test_no_attempts_returns_zero_minutes(self, authenticated_client):
        """No ListeningAttempt rows today → listening_minutes_today=0, goal not reached."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0.0,
                'listening_goal_reached': False,
            }):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['listening_goal_minutes'] == 10
        assert data['listening_minutes_today'] == 0.0
        assert data['listening_goal_reached'] is False

    def test_goal_reached_when_minutes_sufficient(self, authenticated_client):
        """When listening_minutes_today >= goal → listening_goal_reached=True."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 10.0,
                'listening_goal_reached': True,
            }):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['listening_goal_reached'] is True

    def test_partial_progress_not_reached(self, authenticated_client):
        """Partial listening time → goal not reached."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 5.0,
                'listening_goal_reached': False,
            }):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['listening_minutes_today'] == 5.0
        assert data['listening_goal_reached'] is False

    def test_goal_zero_always_reached(self, authenticated_client):
        """goal=0 → always reached regardless of minutes."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 0,
                'listening_minutes_today': 0.0,
                'listening_goal_reached': True,
            }):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['listening_goal_minutes'] == 0
        assert data['listening_goal_reached'] is True


class TestComputeListeningGoalUnit:
    """Unit tests for _compute_listening_goal helper."""

    def test_no_attempts_returns_zero(self, app, db_session):
        from app.api.daily_plan import _compute_listening_goal
        from app.auth.models import User

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return
            user.listening_goal_minutes = 10
            result = _compute_listening_goal(user, 'Europe/Moscow')

        assert result['listening_minutes_today'] == 0.0
        assert result['listening_goal_minutes'] == 10
        assert result['listening_goal_reached'] is False

    def test_goal_zero_always_reached(self, app, db_session):
        from app.api.daily_plan import _compute_listening_goal
        from app.auth.models import User

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return
            user.listening_goal_minutes = 0
            result = _compute_listening_goal(user, 'Europe/Moscow')

        assert result['listening_goal_reached'] is True
        assert result['listening_goal_minutes'] == 0

    def test_attempts_today_accumulate_minutes(self, app, db_session):
        """Two attempts with 300s each = 10 minutes total → goal reached."""
        from app.api.daily_plan import _compute_listening_goal
        from app.auth.models import User
        from app.curriculum.models import ListeningAttempt, Lessons

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return
            lesson = db_session.query(Lessons).first()
            if lesson is None:
                return

            user.listening_goal_minutes = 10

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            for _ in range(2):
                attempt = ListeningAttempt(
                    user_id=user.id,
                    lesson_id=lesson.id,
                    score=80.0,
                    replay_count=0,
                    created_at=now_utc,
                )
                db_session.add(attempt)
            db_session.flush()

            result = _compute_listening_goal(user, 'UTC')

        assert result['listening_minutes_today'] == 10.0
        assert result['listening_goal_reached'] is True

    def test_attempts_use_content_duration(self, app, db_session):
        """Lesson content duration_seconds used when available."""
        from app.api.daily_plan import _compute_listening_goal
        from app.auth.models import User
        from app.curriculum.models import ListeningAttempt, Lessons

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return
            lesson = db_session.query(Lessons).filter(
                Lessons.content.isnot(None)
            ).first()
            if lesson is None:
                return

            user.listening_goal_minutes = 5
            original_content = lesson.content or {}
            lesson.content = {**original_content, 'duration_seconds': 120}
            db_session.flush()

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            attempt = ListeningAttempt(
                user_id=user.id,
                lesson_id=lesson.id,
                score=90.0,
                replay_count=0,
                created_at=now_utc,
            )
            db_session.add(attempt)
            db_session.flush()

            result = _compute_listening_goal(user, 'UTC')

        assert result['listening_minutes_today'] == 2.0


class TestRecoverySuggestionInDailyStatus:
    """recovery_suggestion field in /api/daily-status when yesterday incomplete."""

    def _base_patches(self, recovery=None):
        plan = _linear_plan()
        patches = [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
            patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0.0,
                'listening_goal_reached': False,
            }),
            patch('app.api.daily_plan._get_recovery_suggestion', return_value=recovery),
        ]
        return patches

    def test_no_recovery_when_yesterday_completed(self, authenticated_client):
        """No recovery_suggestion field when yesterday's plan was secured."""
        patches = self._base_patches(recovery=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'recovery_suggestion' not in data

    def test_recovery_shown_when_yesterday_incomplete(self, authenticated_client):
        """recovery_suggestion present when yesterday's plan was not secured."""
        suggestion = {
            'missed_kind': 'srs',
            'action_url': '/study?source=linear_plan',
            'missed_date': '2026-05-10',
        }
        patches = self._base_patches(recovery=suggestion)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'recovery_suggestion' in data
        assert data['recovery_suggestion']['missed_kind'] == 'srs'
        assert data['recovery_suggestion']['action_url'] == '/study?source=linear_plan'

    def test_recovery_contains_missed_date(self, authenticated_client):
        """recovery_suggestion includes missed_date field."""
        suggestion = {
            'missed_kind': 'progress',
            'action_url': '/study?source=linear_plan',
            'missed_date': '2026-05-10',
        }
        patches = self._base_patches(recovery=suggestion)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['recovery_suggestion']['missed_date'] == '2026-05-10'


class TestGetRecoverySuggestionUnit:
    """Unit tests for _get_recovery_suggestion helper."""

    def test_returns_none_when_no_log(self, app, db_session):
        """No DailyPlanLog for yesterday → returns None."""
        from app.api.daily_plan import _get_recovery_suggestion

        with app.app_context():
            result = _get_recovery_suggestion(999999, 'UTC')

        assert result is None

    def test_returns_none_when_yesterday_secured(self, app, db_session):
        """DailyPlanLog exists with secured_at set → returns None."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        from app.auth.models import User
        from datetime import datetime, timedelta, timezone
        import pytz

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return

            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=user.id,
                plan_date=yesterday,
                secured_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(user.id, 'UTC')

        assert result is None

    def test_returns_suggestion_when_yesterday_unsecured(self, app, db_session):
        """DailyPlanLog exists with secured_at=None → returns recovery suggestion."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        from app.auth.models import User
        from datetime import datetime, timedelta
        import pytz

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return

            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=user.id,
                plan_date=yesterday,
                secured_at=None,
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(user.id, 'UTC')

        assert result is not None
        assert 'missed_kind' in result
        assert 'action_url' in result
        assert result['missed_date'] == yesterday.isoformat()
        assert result['missed_kind'] == 'srs'

    def test_mission_type_used_as_missed_kind(self, app, db_session):
        """mission_type from DailyPlanLog used as missed_kind when set."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        from app.auth.models import User
        from datetime import datetime, timedelta
        import pytz

        with app.app_context():
            user = db_session.query(User).first()
            if user is None:
                return

            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=user.id,
                plan_date=yesterday,
                mission_type='progress',
                secured_at=None,
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(user.id, 'UTC')

        assert result is not None
        assert result['missed_kind'] == 'progress'


class TestListeningStreakDaysInDailyStatus:
    """listening_streak_days is included in /api/daily-status payload."""

    def _base_patches(self):
        plan = _linear_plan()
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
        ]

    def test_listening_streak_days_present_in_payload(self, authenticated_client):
        """listening_streak_days key is always present in /api/daily-status."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0.0,
                'listening_goal_reached': False,
            }), patch('app.achievements.streak_service.get_listening_streak', return_value=0):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'listening_streak_days' in data
        assert data['listening_streak_days'] == 0

    def test_listening_streak_days_reflects_streak(self, authenticated_client):
        """listening_streak_days reflects the computed streak value."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 5.0,
                'listening_goal_reached': False,
            }), patch('app.achievements.streak_service.get_listening_streak', return_value=5):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['listening_streak_days'] == 5
