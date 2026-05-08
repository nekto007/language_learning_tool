"""Tests for Task 11: Day-secured banner shows next-best-step CTA."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest


def _render_partial(app, context: dict) -> str:
    env = app.jinja_env
    template = env.get_template('partials/linear_daily_plan.html')
    return template.render(**context)


def _linear_plan_payload(all_done: bool = True) -> dict:
    return {
        'mode': 'linear',
        'position': None,
        'progress': None,
        'baseline_slots': [
            {
                'kind': 'curriculum', 'title': 'L1', 'lesson_type': 'card',
                'eta_minutes': 5, 'url': '/learn/1/', 'completed': all_done, 'data': {},
            },
            {
                'kind': 'srs', 'title': 'SRS', 'lesson_type': None,
                'eta_minutes': 5, 'url': '/study', 'completed': all_done,
                'data': {'due_count': 0},
            },
        ],
        'continuation': {'next_lessons': [], 'available': False},
        'day_secured': all_done,
    }


class TestPartialNextStepRender:
    def test_next_step_with_url_renders_link(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'day_secured_banner': {
                'today_xp': 50, 'streak': 3, 'slots_done': 2, 'slots_total': 2,
                'next_step': {
                    'kind': 'lesson',
                    'reason': 'Continue with the next lesson: "L2"',
                    'estimated_minutes': 8,
                    'url': '/learn/2/',
                },
            },
        })
        assert 'data-linear-day-secured-next-step="true"' in html
        assert 'Следующий шаг' in html
        assert 'href="/learn/2/"' in html
        assert 'L2' in html
        assert '~8 мин' in html
        assert 'data-linear-step-kind="lesson"' in html

    def test_next_step_without_url_renders_text(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'day_secured_banner': {
                'today_xp': 0, 'streak': 0, 'slots_done': 2, 'slots_total': 2,
                'next_step': {
                    'kind': 'vocab',
                    'reason': 'Review your vocabulary',
                    'estimated_minutes': None,
                    'url': None,
                },
            },
        })
        assert 'data-linear-day-secured-next-step="true"' in html
        assert 'Review your vocabulary' in html
        assert 'href=' not in html.split('day-secured-banner-next')[1].split('day-secured-banner-actions')[0]

    def test_next_step_absent_when_missing(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'day_secured_banner': {
                'today_xp': 0, 'streak': 0, 'slots_done': 2, 'slots_total': 2,
            },
        })
        assert 'data-linear-day-secured-next-step' not in html


class TestLateDayHint:
    """Task 12: subtle hint when slots pending and local hour ≥ 20."""

    def _plan_with_pending(self) -> dict:
        plan = _linear_plan_payload(all_done=False)
        # Mark first slot done, keep second pending.
        plan['baseline_slots'][0]['completed'] = True
        plan['baseline_slots'][1]['completed'] = False
        return plan

    def test_hint_renders_at_20(self, app):
        plan = self._plan_with_pending()
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'local_hour': 20,
        })
        assert 'data-linear-late-hint="true"' in html
        assert 'До конца дня осталось мало времени' in html

    def test_hint_renders_at_23(self, app):
        plan = self._plan_with_pending()
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'local_hour': 23,
        })
        assert 'data-linear-late-hint="true"' in html

    def test_hint_hidden_at_19(self, app):
        plan = self._plan_with_pending()
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'local_hour': 19,
        })
        assert 'data-linear-late-hint' not in html

    def test_hint_hidden_when_all_slots_done(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'local_hour': 22,
        })
        assert 'data-linear-late-hint' not in html

    def test_hint_hidden_when_local_hour_missing(self, app):
        plan = self._plan_with_pending()
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'local_hour': None,
        })
        assert 'data-linear-late-hint' not in html


# ── Dashboard route integration ───────────────────────────────────────


@pytest.fixture
def words_module_access(app, db_session, test_user):
    from app.modules.models import SystemModule, UserModule
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
def clear_leaderboard_cache():
    from app.words.routes import _leaderboard_cache
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0
    yield
    with _leaderboard_cache['lock']:
        _leaderboard_cache['data'] = None
        _leaderboard_cache['expires'] = 0.0


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _seed_secured_log(db_session, user_id, for_date):
    from app.daily_plan.models import DailyPlanLog
    row = DailyPlanLog(
        user_id=user_id, plan_date=for_date, mission_type=None,
        secured_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _all_done_plan() -> dict:
    plan = _linear_plan_payload(all_done=True)
    plan['_plan_meta'] = {
        'mission_plan_enabled': False,
        'effective_mode': 'linear',
        'fallback_reason': None,
    }
    return plan


class TestDashboardNextStepBanner:
    def test_next_step_appears_in_banner(
        self, client, app, db_session, test_user, words_module_access,
    ):
        from app.daily_plan.next_step import NextStep
        test_user.use_linear_plan = True
        db_session.commit()
        today = date.today()
        _seed_secured_log(db_session, test_user.id, today)
        _login(client, test_user)
        plan = _all_done_plan()
        fake_step = NextStep(
            kind='srs',
            reason='You have 5 cards due for review',
            data={'words_due': 5, 'daily_limit': 50},
            estimated_minutes=2,
        )
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.daily_plan.next_step.get_next_best_step',
            return_value=[fake_step],
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-next-step="true"' in html
        assert 'cards due for review' in html
        assert 'href="/study?source=linear_plan"' in html
        assert 'data-linear-step-kind="srs"' in html

    def test_next_step_absent_when_no_steps(
        self, client, app, db_session, test_user, words_module_access,
    ):
        test_user.use_linear_plan = True
        db_session.commit()
        today = date.today()
        _seed_secured_log(db_session, test_user.id, today)
        _login(client, test_user)
        plan = _all_done_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.daily_plan.next_step.get_next_best_step', return_value=[],
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Banner is still rendered, but no next-step block
        assert 'data-linear-day-secured-banner="true"' in html
        assert 'data-linear-day-secured-next-step' not in html

    def test_next_step_failure_does_not_break_banner(
        self, client, app, db_session, test_user, words_module_access,
    ):
        test_user.use_linear_plan = True
        db_session.commit()
        today = date.today()
        _seed_secured_log(db_session, test_user.id, today)
        _login(client, test_user)
        plan = _all_done_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.daily_plan.next_step.get_next_best_step',
            side_effect=RuntimeError('boom'),
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-banner="true"' in html
        assert 'data-linear-day-secured-next-step' not in html
