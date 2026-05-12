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

    def test_no_attempts_returns_zero(self, app, db_session, test_user):
        from app.api.daily_plan import _compute_listening_goal

        with app.app_context():
            test_user.listening_goal_minutes = 10
            result = _compute_listening_goal(test_user, 'Europe/Moscow')

        assert result['listening_minutes_today'] == 0.0
        assert result['listening_goal_minutes'] == 10
        assert result['listening_goal_reached'] is False

    def test_goal_zero_always_reached(self, app, db_session, test_user):
        from app.api.daily_plan import _compute_listening_goal

        with app.app_context():
            test_user.listening_goal_minutes = 0
            result = _compute_listening_goal(test_user, 'Europe/Moscow')

        assert result['listening_goal_reached'] is True
        assert result['listening_goal_minutes'] == 0

    def test_attempts_today_accumulate_minutes(self, app, db_session, test_user, test_lesson_vocabulary):
        """One listening attempt for a 300s lesson = 5 minutes → goal reached at goal=5."""
        from app.api.daily_plan import _compute_listening_goal
        from app.curriculum.models import ListeningAttempt

        with app.app_context():
            # goal = 5 min; one 300s lesson = 5 min → reached
            test_user.listening_goal_minutes = 5

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            attempt = ListeningAttempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                score=80.0,
                replay_count=0,
                created_at=now_utc,
            )
            db_session.add(attempt)
            db_session.flush()

            result = _compute_listening_goal(test_user, 'UTC')

        assert result['listening_minutes_today'] == 5.0
        assert result['listening_goal_reached'] is True

    def test_attempts_use_content_duration(self, app, db_session, test_user, test_lesson_vocabulary):
        """Lesson content duration_seconds used when available."""
        from app.api.daily_plan import _compute_listening_goal
        from app.curriculum.models import ListeningAttempt

        with app.app_context():
            test_user.listening_goal_minutes = 5
            original_content = test_lesson_vocabulary.content or {}
            test_lesson_vocabulary.content = {**original_content, 'duration_seconds': 120}
            db_session.flush()

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            attempt = ListeningAttempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                score=90.0,
                replay_count=0,
                created_at=now_utc,
            )
            db_session.add(attempt)
            db_session.flush()

            result = _compute_listening_goal(test_user, 'UTC')

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

    def test_returns_none_when_yesterday_secured(self, app, db_session, test_user):
        """DailyPlanLog exists with secured_at set → returns None."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        import pytz

        with app.app_context():
            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=test_user.id,
                plan_date=yesterday,
                secured_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(test_user.id, 'UTC')

        assert result is None

    def test_returns_suggestion_when_yesterday_unsecured(self, app, db_session, test_user):
        """DailyPlanLog exists with secured_at=None → returns recovery suggestion."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        import pytz

        with app.app_context():
            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=test_user.id,
                plan_date=yesterday,
                secured_at=None,
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(test_user.id, 'UTC')

        assert result is not None
        assert 'missed_kind' in result
        assert 'action_url' in result
        assert result['missed_date'] == yesterday.isoformat()
        assert result['missed_kind'] == 'srs'

    def test_mission_type_used_as_missed_kind(self, app, db_session, test_user):
        """mission_type from DailyPlanLog used as missed_kind when set."""
        from app.api.daily_plan import _get_recovery_suggestion
        from app.daily_plan.models import DailyPlanLog
        import pytz

        with app.app_context():
            tz_obj = pytz.timezone('UTC')
            yesterday = (datetime.now(tz_obj) - timedelta(days=1)).date()

            log = DailyPlanLog(
                user_id=test_user.id,
                plan_date=yesterday,
                mission_type='progress',
                secured_at=None,
            )
            db_session.add(log)
            db_session.flush()

            result = _get_recovery_suggestion(test_user.id, 'UTC')

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


class TestComputeGoalProgressUnit:
    """Unit tests for _compute_goal_progress helper."""

    def test_no_activity_returns_zeros(self, app, db_session, test_user):
        """No new cards and no completed lessons → actual=0 for both goals."""
        from app.api.daily_plan import _compute_goal_progress

        with app.app_context():
            test_user.daily_word_goal = 10
            test_user.weekly_lesson_goal = 5

            result = _compute_goal_progress(test_user, 'UTC')

        gp = result['goal_progress']
        assert gp['daily_words']['goal'] == 10
        assert gp['daily_words']['actual'] == 0
        assert gp['daily_words']['reached'] is False
        assert gp['weekly_lessons']['goal'] == 5
        assert gp['weekly_lessons']['actual'] == 0
        assert gp['weekly_lessons']['reached'] is False

    def test_daily_words_reached_when_actual_gte_goal(self, app, db_session, test_user):
        """words_today >= daily_word_goal → reached=True."""
        from app.api.daily_plan import _compute_goal_progress
        from unittest.mock import patch

        with app.app_context():
            test_user.daily_word_goal = 5
            test_user.weekly_lesson_goal = 10

            with patch('app.srs.counting.count_new_cards_today', return_value=5):
                result = _compute_goal_progress(test_user, 'UTC')

        gp = result['goal_progress']
        assert gp['daily_words']['actual'] == 5
        assert gp['daily_words']['reached'] is True

    def test_daily_words_not_reached_when_actual_lt_goal(self, app, db_session, test_user):
        """words_today < daily_word_goal → reached=False."""
        from app.api.daily_plan import _compute_goal_progress
        from unittest.mock import patch

        with app.app_context():
            test_user.daily_word_goal = 10
            test_user.weekly_lesson_goal = 5

            with patch('app.srs.counting.count_new_cards_today', return_value=3):
                result = _compute_goal_progress(test_user, 'UTC')

        gp = result['goal_progress']
        assert gp['daily_words']['actual'] == 3
        assert gp['daily_words']['reached'] is False

    def test_weekly_lessons_reached_when_actual_gte_goal(self, app, db_session, test_user, test_lesson_vocabulary):
        """lessons_this_week >= weekly_lesson_goal → reached=True."""
        from app.api.daily_plan import _compute_goal_progress
        from app.curriculum.models import LessonProgress

        with app.app_context():
            test_user.daily_word_goal = 10
            test_user.weekly_lesson_goal = 1

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            lp = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                completed_at=now_utc,
            )
            db_session.add(lp)
            db_session.flush()

            result = _compute_goal_progress(test_user, 'UTC')

        gp = result['goal_progress']
        assert gp['weekly_lessons']['actual'] >= 1
        assert gp['weekly_lessons']['reached'] is True

    def test_week_boundary_excludes_last_week_lessons(self, app, db_session, test_user, test_lesson_vocabulary):
        """LessonProgress completed before Monday this week not counted."""
        from app.api.daily_plan import _compute_goal_progress
        from app.curriculum.models import LessonProgress

        with app.app_context():
            test_user.daily_word_goal = 5
            test_user.weekly_lesson_goal = 2

            # Completed 10 days ago (definitely last week)
            old_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
            lp = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                completed_at=old_date,
            )
            db_session.add(lp)
            db_session.flush()

            result = _compute_goal_progress(test_user, 'UTC')

        gp = result['goal_progress']
        # Old lesson should not count toward this week
        assert gp['weekly_lessons']['reached'] is False


class TestGoalProgressInDailyStatusEndpoint:
    """goal_progress field present in /api/daily-status response."""

    def _base_patches(self):
        plan = _linear_plan()
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
            patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0.0,
                'listening_goal_reached': False,
            }),
        ]

    def test_goal_progress_present_in_payload(self, authenticated_client):
        """goal_progress key is always in /api/daily-status response."""
        patches = self._base_patches()
        goal_data = {
            'goal_progress': {
                'daily_words': {'goal': 10, 'actual': 0, 'reached': False},
                'weekly_lessons': {'goal': 5, 'actual': 0, 'reached': False},
            }
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with patch('app.api.daily_plan._compute_goal_progress', return_value=goal_data):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'goal_progress' in data
        assert 'daily_words' in data['goal_progress']
        assert 'weekly_lessons' in data['goal_progress']

    def test_goal_reached_false_when_actual_below_goal(self, authenticated_client):
        """reached=False when actual < goal."""
        patches = self._base_patches()
        goal_data = {
            'goal_progress': {
                'daily_words': {'goal': 10, 'actual': 3, 'reached': False},
                'weekly_lessons': {'goal': 5, 'actual': 2, 'reached': False},
            }
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with patch('app.api.daily_plan._compute_goal_progress', return_value=goal_data):
                response = authenticated_client.get('/api/daily-status')

        data = response.get_json()
        assert data['goal_progress']['daily_words']['reached'] is False
        assert data['goal_progress']['weekly_lessons']['reached'] is False

    def test_goal_reached_true_when_actual_gte_goal(self, authenticated_client):
        """reached=True when actual >= goal."""
        patches = self._base_patches()
        goal_data = {
            'goal_progress': {
                'daily_words': {'goal': 5, 'actual': 5, 'reached': True},
                'weekly_lessons': {'goal': 3, 'actual': 4, 'reached': True},
            }
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with patch('app.api.daily_plan._compute_goal_progress', return_value=goal_data):
                response = authenticated_client.get('/api/daily-status')

        data = response.get_json()
        assert data['goal_progress']['daily_words']['reached'] is True
        assert data['goal_progress']['weekly_lessons']['reached'] is True


class TestStudyMinutesInDailyStatus:
    """Test minutes_studied_today in /api/daily-status response."""

    def _base_patches(self):
        from tests.api.test_daily_status import _linear_plan, _empty_summary
        plan = _linear_plan()
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
        ]

    def test_minutes_studied_in_payload(self, authenticated_client):
        """minutes_studied_today is present in daily-status payload."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_study_minutes', return_value=25):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert 'minutes_studied_today' in data
        assert data['minutes_studied_today'] == 25

    def test_zero_minutes_when_no_activity(self, authenticated_client):
        """No study activity → minutes_studied_today=0."""
        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_study_minutes', return_value=0):
                response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['minutes_studied_today'] == 0


class TestComputeStudyMinutesUnit:
    """Unit tests for _compute_study_minutes and DailyStudyMinutes model."""

    def test_no_rows_returns_zero(self, app, db_session, test_user):
        from app.api.daily_plan import _compute_study_minutes

        with app.app_context():
            result = _compute_study_minutes(test_user, 'UTC')

        assert result == 0

    def test_add_study_minutes_creates_row(self, app, db_session, test_user):
        """add_study_minutes creates a row when none exists."""
        from datetime import date
        from app.curriculum.models import DailyStudyMinutes, add_study_minutes, get_minutes_today
        from app.utils.db import db

        with app.app_context():
            today = date(2026, 5, 21)
            add_study_minutes(test_user.id, today, 15, db)
            db_session.flush()

            result = get_minutes_today(test_user.id, today, db)
            assert result == 15

    def test_add_study_minutes_accumulates(self, app, db_session, test_user):
        """Multiple add_study_minutes calls accumulate minutes for the same date."""
        from datetime import date
        from app.curriculum.models import add_study_minutes, get_minutes_today
        from app.utils.db import db

        with app.app_context():
            today = date(2026, 5, 22)
            add_study_minutes(test_user.id, today, 10, db)
            db_session.flush()
            add_study_minutes(test_user.id, today, 15, db)
            db_session.flush()

            result = get_minutes_today(test_user.id, today, db)
            assert result == 25

    def test_different_dates_independent(self, app, db_session, test_user):
        """Minutes are bucketed per date independently."""
        from datetime import date
        from app.curriculum.models import add_study_minutes, get_minutes_today
        from app.utils.db import db

        with app.app_context():
            d1 = date(2026, 5, 23)
            d2 = date(2026, 5, 24)
            add_study_minutes(test_user.id, d1, 20, db)
            add_study_minutes(test_user.id, d2, 8, db)
            db_session.flush()

            assert get_minutes_today(test_user.id, d1, db) == 20
            assert get_minutes_today(test_user.id, d2, db) == 8
