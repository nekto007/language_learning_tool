"""Smoke tests for dashboard UX audit (Task 46).

Covers:
- Skeleton loaders: none present in server-rendered dashboard (no stale loaders)
- .btn--loading class applied on reload-plan and skip-reason buttons in JS
- Empty state shown when plan is empty (not blank screen)
- day_secured reflected in CSS classes and template output
- null plan payload fields handled gracefully (no template crash)
"""
import os
import re

import pytest
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

pytestmark = pytest.mark.smoke

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
_UNIFIED_PLAN_PATH = os.path.join(_TEMPLATES_DIR, 'partials', 'unified_daily_plan.html')
_DASHBOARD_UNIFIED_PATH = os.path.join(_TEMPLATES_DIR, 'words', 'dashboard_unified.html')
_JS_NEXT_STEP_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'static', 'js', 'daily-plan-next.js'
)
_JS_UNIFIED_PLAN_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'static', 'js', 'daily-plan-next.js'
)


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=True,
        undefined=ChainableUndefined,
    )

    class _User:
        id = 1
        username = 'tester'
        is_authenticated = True
        is_admin = False
        onboarding_completed = True
        onboarding_focus = None

    def _url_for(endpoint, **kw):
        return '/stub/' + endpoint

    env.globals['url_for'] = _url_for
    env.globals['current_user'] = _User()
    env.globals['csrf_token'] = lambda: 'tok'
    env.globals['config'] = {}
    return env


def _render_partial(env: Environment, unified_plan: dict, plan_completion: dict | None = None) -> str:
    tpl = env.get_template('partials/unified_daily_plan.html')
    return tpl.render(unified_plan=unified_plan, plan_completion=plan_completion or {})


def _base_plan(**overrides) -> dict:
    plan: dict = {
        'required': [],
        'optional': [],
        'setup': [],
        'day_secured': False,
        'total_estimated_minutes': 0,
        'has_more_optional': False,
        'position': None,
        'progress': {},
        'module_progress': {},
    }
    plan.update(overrides)
    return plan


class TestNoSkeletonLoaders:
    """Dashboard uses server-side rendering — no stale skeleton loaders."""

    def test_no_skeleton_class_in_dashboard_template(self):
        with open(_DASHBOARD_UNIFIED_PATH, encoding='utf-8') as f:
            src = f.read()
        # Server-rendered template must not inject skeleton placeholders that
        # JS would need to remove later (they would stay visible on JS errors).
        assert 'class="skeleton"' not in src
        assert 'class="skeleton-box"' not in src

    def test_no_skeleton_class_in_unified_plan_partial(self):
        with open(_UNIFIED_PLAN_PATH, encoding='utf-8') as f:
            src = f.read()
        assert 'class="skeleton"' not in src
        assert 'class="skeleton-box"' not in src


class TestBtnLoading:
    """Reload-plan and skip-reason buttons apply btn--loading during fetch."""

    def test_inline_script_adds_btn_loading_on_reload(self):
        with open(_UNIFIED_PLAN_PATH, encoding='utf-8') as f:
            src = f.read()
        # The reload-plan click handler must add btn--loading before reload
        assert "btn.classList.add('btn--loading')" in src

    def test_inline_script_adds_btn_loading_on_skip_reason(self):
        with open(_UNIFIED_PLAN_PATH, encoding='utf-8') as f:
            src = f.read()
        # skip-reason submit adds loading state
        assert "btn.classList.add('btn--loading')" in src

    def test_inline_script_removes_btn_loading_on_error(self):
        with open(_UNIFIED_PLAN_PATH, encoding='utf-8') as f:
            src = f.read()
        # On fetch error, loading state must be removed
        assert "btn.classList.remove('btn--loading')" in src


class TestEmptyState:
    """When plan has no required items, an empty state is shown — not blank."""

    def test_empty_required_renders_empty_state(self):
        env = _build_env()
        html = _render_partial(env, _base_plan(required=[]))
        assert 'daily-plan__empty' in html

    def test_empty_state_has_icon(self):
        env = _build_env()
        html = _render_partial(env, _base_plan(required=[]))
        assert 'daily-plan__empty-state' in html
        assert 'daily-plan__empty-icon' in html

    def test_nonempty_required_does_not_show_empty_state(self):
        env = _build_env()
        plan = _base_plan(required=[{
            'id': 'r1', 'kind': 'curriculum', 'title': 'Урок 1',
            'url': '/lesson/1', 'completed': False, 'skipped': False,
            'blocked': False, 'data': {}, 'lesson_type': 'vocabulary',
        }])
        html = _render_partial(env, plan)
        assert 'daily-plan__empty' not in html


class TestDaySecured:
    """day_secured=True is reflected visually in the template output."""

    def test_day_secured_note_shown_when_true(self):
        env = _build_env()
        # Celebration block (replaces the legacy secured-note) renders when
        # required list is non-empty and day_secured=True.
        plan = _base_plan(
            day_secured=True,
            required=[{
                'id': 'r1', 'kind': 'curriculum', 'title': 'Урок 1',
                'url': '/lesson/1', 'completed': True, 'skipped': False,
                'blocked': False, 'data': {}, 'lesson_type': 'vocabulary',
            }]
        )
        html = _render_partial(env, plan)
        assert 'daily-plan__celebration' in html
        assert 'День закрыт' in html

    def test_close_hint_shown_when_not_secured(self):
        env = _build_env()
        plan = _base_plan(
            day_secured=False,
            required=[{
                'id': 'r1', 'kind': 'curriculum', 'title': 'Урок 1',
                'url': '/lesson/1', 'completed': False, 'skipped': False,
                'blocked': False, 'data': {}, 'lesson_type': 'vocabulary',
            }]
        )
        html = _render_partial(env, plan)
        assert 'daily-plan__close-hint' in html

    def test_optional_section_locked_class_when_not_secured(self):
        env = _build_env()
        plan = _base_plan(
            day_secured=False,
            optional=[{
                'id': 'o1', 'kind': 'srs', 'title': 'Повторение',
                'url': '/study', 'completed': False, 'data': {},
            }]
        )
        html = _render_partial(env, plan)
        assert 'daily-plan__section--optional-locked' in html

    def test_optional_section_unlocked_when_day_secured(self):
        env = _build_env()
        plan = _base_plan(
            day_secured=True,
            optional=[{
                'id': 'o1', 'kind': 'srs', 'title': 'Повторение',
                'url': '/study', 'completed': False, 'data': {},
            }]
        )
        html = _render_partial(env, plan)
        assert 'daily-plan__section--optional-locked' not in html


class TestNullSafetyJS:
    """daily-plan-next.js guards against null/undefined API responses."""

    def test_data_null_guard_present(self):
        with open(_JS_NEXT_STEP_PATH, encoding='utf-8') as f:
            src = f.read()
        # Must have a null check before accessing data properties
        assert "if (!data || typeof data !== 'object') return;" in src

    def test_null_plan_payload_does_not_crash_template(self):
        """Template renders without exception when plan fields are None/missing."""
        env = _build_env()
        # All optional fields absent — template should use .get() defaults
        html = _render_partial(env, {})
        # The section wrapper is always rendered
        assert 'daily-plan' in html

    def test_none_position_renders_fallback_header(self):
        env = _build_env()
        html = _render_partial(env, _base_plan(position=None))
        assert 'daily-plan__position--no-content' in html

    def test_none_module_progress_renders_without_error(self):
        env = _build_env()
        html = _render_partial(env, _base_plan(module_progress=None))
        assert 'daily-plan' in html

    def test_eta_zero_does_not_show_eta_label(self):
        env = _build_env()
        html = _render_partial(env, _base_plan(total_estimated_minutes=0))
        assert 'daily-plan__eta' not in html


class TestContinuationQueueSection:
    """Optional section renders a Duolingo-style «Дальше по курсу» queue."""

    def _queue_plan(self, **overrides) -> dict:
        """Day-secured plan with a multi-lesson curriculum continuation queue."""
        optional = [
            {
                'id': f'curriculum:lesson:{n}',
                'kind': 'curriculum',
                'title': f'Урок очереди {n}',
                'url': f'/lesson/{n}',
                'completed': False,
                'lesson_type': 'vocabulary',
                'data': {'lesson_id': n, 'queue_position': i + 1},
            }
            for i, n in enumerate((10, 11, 12))
        ]
        plan = _base_plan(day_secured=True, optional=optional)
        plan.update(overrides)
        return plan

    def test_section_title_renamed_to_continue_course(self):
        env = _build_env()
        html = _render_partial(env, self._queue_plan())
        assert 'Дальше по курсу' in html
        assert 'Дополнительно' not in html

    def test_multiple_curriculum_items_present(self):
        env = _build_env()
        html = _render_partial(env, self._queue_plan())
        # Several curriculum lessons are queued; titles all render even though
        # sequential unlock keeps only the first clickable.
        for n in (10, 11, 12):
            assert f'Урок очереди {n}' in html
        assert html.count('plan-item--curriculum') >= 3
        # The first (current) queue lesson is a live link.
        assert '/lesson/10' in html

    def test_curriculum_items_use_step_badge_not_bonus(self):
        env = _build_env()
        html = _render_partial(env, self._queue_plan())
        # Curriculum queue items get the neutral 📚 step marker, not «Бонус».
        assert 'plan-item__badge--curriculum' in html
        assert 'plan-item__badge-step' in html
        # No «Бонус» label leaks onto curriculum queue items.
        assert 'Бонус' not in html

    def test_challenge_keeps_xp_badge(self):
        env = _build_env()
        plan = self._queue_plan(optional=[{
            'id': 'challenge:1', 'kind': 'curriculum', 'title': 'Челлендж',
            'url': '/challenge', 'completed': False, 'lesson_type': 'quiz',
            'data': {'is_challenge': True, 'bonus_xp': 30},
        }])
        html = _render_partial(env, plan)
        assert '+30 XP' in html

    def test_load_more_label_for_lessons(self):
        env = _build_env()
        plan = self._queue_plan(has_more_optional=True, day_secured=False)
        html = _render_partial(env, plan)
        assert 'Показать ещё уроки' in html

    def test_bonus_label_remains_for_non_curriculum_practice(self):
        env = _build_env()
        plan = _base_plan(day_secured=True, optional=[{
            'id': 'o-srs', 'kind': 'srs', 'title': 'Повторение слов',
            'url': '/study', 'completed': False, 'data': {},
        }])
        html = _render_partial(env, plan)
        assert 'Бонус' in html
