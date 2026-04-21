"""Tests for Task 6: Dashboard day-secured banner (linear plan).

Covers:
- Partial renders banner when `day_secured_banner` passed in context.
- Partial omits banner when `day_secured_banner` is falsy/absent.
- Dashboard route computes banner payload when `?day_secured=1` and a
  DailyPlanLog with `secured_at` exists for the user today.
- Banner absent without query-param, without DailyPlanLog, or without
  linear plan payload.
- Banner XP count aggregates today's StreakEvents via get_today_xp.
- Banner omitted for users without `use_linear_plan=True`.
- JS helper (linear-daily-plan.js) contains day-secured banner wiring so
  `linearPlanContext` is cleared when the banner is present.
- Continuation block carries the `#linear-plan-continuation` anchor that
  the banner CTA targets.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest


# ── Partial-level rendering tests ────────────────────────────────────


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
                'kind': 'curriculum',
                'title': 'L1',
                'lesson_type': 'card',
                'eta_minutes': 5,
                'url': '/learn/1/',
                'completed': all_done,
                'data': {},
            },
            {
                'kind': 'srs',
                'title': 'SRS',
                'lesson_type': None,
                'eta_minutes': 5,
                'url': '/study',
                'completed': all_done,
                'data': {'due_count': 0},
            },
            {
                'kind': 'reading',
                'title': 'Book',
                'lesson_type': None,
                'eta_minutes': 5,
                'url': '/read/1',
                'completed': all_done,
                'data': {},
            },
        ],
        'continuation': {'next_lessons': [], 'available': False},
        'day_secured': all_done,
    }


class TestPartialBannerRender:
    def test_banner_rendered_when_day_secured_banner_passed(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'day_secured_banner': {
                'today_xp': 85,
                'streak': 5,
                'slots_done': 3,
                'slots_total': 3,
            },
        })
        assert 'data-linear-day-secured-banner="true"' in html
        assert 'День сохранён' in html
        assert '+85 XP' in html
        assert '>5<' in html  # streak value
        assert '3/3' in html
        # CTAs present
        assert 'Продолжить обучение' in html
        assert 'На сегодня хватит' in html
        assert 'href="#linear-plan-continuation"' in html
        assert 'data-linear-action="day-secured-dismiss"' in html

    def test_banner_absent_when_context_key_missing(self, app):
        plan = _linear_plan_payload(all_done=False)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
        })
        assert 'data-linear-day-secured-banner' not in html

    def test_banner_absent_when_context_key_none(self, app):
        plan = _linear_plan_payload(all_done=True)
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
            'day_secured_banner': None,
        })
        assert 'data-linear-day-secured-banner' not in html

    def test_streak_plural_forms(self, app):
        """Russian plural for 'дней подряд' handles 1/2/5 correctly."""
        plan = _linear_plan_payload(all_done=True)
        for streak, expected_label in [(1, 'день'), (2, 'дня'), (5, 'дней')]:
            html = _render_partial(app, {
                'linear_plan': plan,
                'plan_completion': {},
                'day_secured_banner': {
                    'today_xp': 10,
                    'streak': streak,
                    'slots_done': 3,
                    'slots_total': 3,
                },
            })
            assert expected_label in html, (
                f'streak={streak} should produce label {expected_label!r}'
            )

    def test_continuation_block_has_linear_plan_continuation_id(self, app):
        plan = _linear_plan_payload(all_done=True)
        plan['continuation']['next_lessons'] = [{
            'lesson_id': 999,
            'lesson_type': 'card',
            'lesson_number': 2,
            'module_number': 1,
            'level_code': 'A1',
        }]
        html = _render_partial(app, {
            'linear_plan': plan,
            'plan_completion': {},
        })
        assert 'id="linear-plan-continuation"' in html


# ── Dashboard route integration tests ────────────────────────────────


@pytest.fixture
def words_module_access(app, db_session, test_user):
    from app.modules.models import SystemModule, UserModule

    words_module = SystemModule.query.filter_by(code='words').first()
    if not words_module:
        words_module = SystemModule(
            code='words', name='Words', description='Words',
        )
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


def _seed_secured_log(db_session, user_id, for_date: date):
    from app.daily_plan.models import DailyPlanLog
    row = DailyPlanLog(
        user_id=user_id,
        plan_date=for_date,
        mission_type=None,
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


class TestDashboardRouteBanner:
    def test_banner_rendered_when_query_and_log_present(
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
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-banner="true"' in html
        assert 'День сохранён' in html

    def test_banner_absent_without_query_param(
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
        ):
            response = client.get('/dashboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-banner' not in html

    def test_banner_absent_without_daily_plan_log(
        self, client, app, db_session, test_user, words_module_access,
    ):
        test_user.use_linear_plan = True
        db_session.commit()
        _login(client, test_user)
        # Plan is not yet secured, so the route doesn't auto-write a
        # DailyPlanLog row — and the banner must stay absent even with
        # `?day_secured=1` in the URL.
        plan = _linear_plan_payload(all_done=False)
        plan['_plan_meta'] = {
            'mission_plan_enabled': False,
            'effective_mode': 'linear',
            'fallback_reason': None,
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-banner' not in html

    def test_banner_xp_aggregates_from_streak_events(
        self, client, app, db_session, test_user, words_module_access,
    ):
        from app.achievements.models import StreakEvent
        test_user.use_linear_plan = True
        db_session.commit()
        today = date.today()
        _seed_secured_log(db_session, test_user.id, today)
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_linear',
            event_date=today,
            coins_delta=0,
            details={'xp': 20, 'source': 'linear_curriculum_card'},
        ))
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_linear',
            event_date=today,
            coins_delta=0,
            details={'xp': 8, 'source': 'linear_srs_global'},
        ))
        db_session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=today,
            coins_delta=0,
            details={'xp': 25},
        ))
        db_session.commit()
        _login(client, test_user)
        plan = _all_done_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert '+53 XP' in html

    def test_banner_absent_for_user_without_linear_plan_flag(
        self, client, app, db_session, test_user, words_module_access,
    ):
        test_user.use_linear_plan = False
        db_session.commit()
        today = date.today()
        _seed_secured_log(db_session, test_user.id, today)
        _login(client, test_user)
        # Mission plan so `linear_plan` context var is None.
        from tests.smoke.test_linear_dashboard_smoke import _mission_plan
        with patch(
            'app.daily_plan.service.get_daily_plan_unified',
            return_value=_mission_plan(),
        ):
            response = client.get('/dashboard?day_secured=1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'data-linear-day-secured-banner' not in html


# ── JS wiring invariants ─────────────────────────────────────────────


class TestLinearDailyPlanJsWiring:
    """File-level asserts that the day-secured banner is wired in JS
    (clears linearPlanContext + dismiss handler + strips query-param)."""

    @staticmethod
    def _js_source() -> str:
        js_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'static', 'js',
            'linear-daily-plan.js',
        )
        with open(js_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_js_queries_banner_data_attribute(self):
        js = self._js_source()
        assert 'data-linear-day-secured-banner' in js

    def test_js_clears_linear_plan_context(self):
        js = self._js_source()
        assert 'linearPlanContext' in js
        assert '.clear()' in js

    def test_js_handles_dismiss_action(self):
        js = self._js_source()
        assert 'data-linear-action="day-secured-dismiss"' in js

    def test_js_strips_day_secured_query_param(self):
        js = self._js_source()
        assert "'day_secured'" in js
        assert 'replaceState' in js


# ── CSS invariants ───────────────────────────────────────────────────


class TestDaySecuredBannerCss:
    def test_banner_css_classes_exist(self):
        css_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'static', 'css',
            'design-system.css',
        )
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        assert '.linear-plan__day-secured-banner' in css
        assert '.linear-plan__day-secured-banner-cta--primary' in css
        assert '.linear-plan__day-secured-banner-cta--secondary' in css
