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
