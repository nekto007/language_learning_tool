"""Smoke tests for the compact dashboard redesign (Task 19).

Cover the four dashboard states the redesign must handle:
    1. zero-state user (all counters 0) renders only the welcome card
    2. mid-plan user renders hero CTA to next phase + roadmap + 3-col social
    3. plan-done user renders completion summary + done/extra CTA
    4. legacy user (``mission_plan`` absent) renders the legacy branch unchanged

These tests render the dashboard content block with ``jinja2`` (no DB/Flask
request context) so they run reliably in any environment. Marked with
``@pytest.mark.smoke`` for the ``pytest -m smoke`` fast lane.
"""
import os

import pytest
from jinja2 import ChainableUndefined, Environment, FileSystemLoader


pytestmark = pytest.mark.smoke


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)


def _read_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def _extract_content_block(template_source: str) -> str:
    start_tag = '{% block content %}'
    end_tag = '{% endblock %}'
    start_idx = template_source.index(start_tag) + len(start_tag)
    end_idx = template_source.index(end_tag, start_idx)
    return template_source[start_idx:end_idx]


def _strip_inline_style(rendered: str) -> str:
    out = rendered
    while '<style>' in out and '</style>' in out:
        start = out.index('<style>')
        end = out.index('</style>', start) + len('</style>')
        out = out[:start] + out[end:]
    return out


class _StubUser:
    id = 1
    username = 'stub'
    is_authenticated = True
    is_admin = False
    onboarding_completed = True
    referral_code = 'refcode'
    birth_year = 2000


def _build_env() -> Environment:
    tpl_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
    env = Environment(
        loader=FileSystemLoader(tpl_dir),
        autoescape=True,
        undefined=ChainableUndefined,
    )

    def _url_for(endpoint, **values):
        return f'/stub/{endpoint}'

    env.globals['url_for'] = _url_for
    env.globals['current_user'] = _StubUser()
    env.globals['csrf_token'] = lambda: 'stub-csrf'
    env.globals['config'] = {}
    return env


def _base_ctx() -> dict:
    """Minimal non-zero dashboard context.

    Every section guard is off by default. Individual tests flip the pieces
    they care about (mission_plan, completion_summary, hero_cta, etc.).
    """
    return {
        'is_zero_state': False,
        'unseen_badges': None,
        'greeting': 'Привет',
        'streak': 0,
        'streak_status': None,
        'streak_repaired': False,
        'hero_cta': None,
        'rank_info': None,
        'mission_level_info': None,
        'xp_level_up': None,
        'daily_race': None,
        'mission_plan': None,
        'completion_summary': None,
        'plan_completion': {},
        'plan_steps': {},
        'phase_urls': {},
        'cards_url': '/stub/cards',
        'lesson_minutes': 0,
        'words_minutes': 0,
        'required_steps': 0,
        'plan_steps_done': 0,
        'plan_steps_total': 0,
        'plan_meta': None,
        'rival_strip': None,
        'plan_today': '2026-04-19',
        'words_total': 1,          # non-zero → is_zero_state skip
        'words_in_progress': 1,
        'words_stats': {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0},
        'books_reading': 0,
        'recent_book': None,
        'grammar_total': 0,
        'grammar_studied': 0,
        'grammar_mastered': 0,
        'courses_enrolled': 0,
        'active_course': None,
        'total_achievements': 0,
        'earned_achievements': 0,
        'best_matching': None,
        'best_quiz': None,
        'telegram_linked': False,
        'today_xp': 0,
        'daily_xp_goal': 0,
        'weekly_challenge': None,
        'onboarding_focus': None,
        'onboarding_level': None,
        'activity_heatmap': [],
        'heatmap_pad': 0,
        'streak_calendar': {},
        'words_at_risk': [],
        'grammar_weaknesses': [],
        'xp_leaderboard': [],
        'user_xp_rank': None,
        'achievements_by_category': {},
        'weekly_analytics': None,
        'continue_lesson': None,
        'grammar_user_stats': None,
        'badges_showcase': None,
        'weekly_digest': None,
        'route_metadata': None,
        'route_progress_state': None,
        'yesterday_summary': None,
        'yesterday': None,
        'daily_summary': {
            'lessons_count': 0,
            'grammar_exercises': 0,
            'words_reviewed': 0,
            'books_read': 0,
        },
    }


def _make_mission_plan(phases_completed):
    """Build a minimal mission-plan dict compatible with the template."""
    phase_defs = [
        {'phase': 'recall', 'title': 'Вспомни слова'},
        {'phase': 'learn', 'title': 'Новый урок'},
        {'phase': 'use', 'title': 'Применение'},
    ]
    phases = []
    for i, done in enumerate(phases_completed):
        d = phase_defs[i]
        phases.append({
            'id': f'ph{i}',
            'phase': d['phase'],
            'title': d['title'],
            'source_kind': 'normal_course',
            'mode': 'default',
            'required': True,
            'completed': done,
            'preview': None,
        })
    return {
        'plan_version': 'v1',
        'mission': {
            'type': 'progress',
            'title': 'Продвигаемся вперёд',
            'reason_code': 'progress_default',
            'reason_text': 'Следующий урок готов',
        },
        'primary_goal': {
            'type': 'complete_lesson',
            'title': 'Завершить урок',
            'success_criterion': '1 урок',
        },
        'primary_source': {
            'kind': 'normal_course',
            'id': '1',
            'label': 'English Basics',
        },
        'phases': phases,
        'completion': None,
        'steps': {},
    }


def _render_content(ctx: dict) -> str:
    env = _build_env()
    block_html = _extract_content_block(_read_template())
    tpl = env.from_string(block_html)
    return tpl.render(**ctx)


class TestSmokeZeroState:
    """Smoke: a user with zero activity sees only the fullscreen welcome."""

    def test_zero_state_renders_only_welcome_card(self):
        ctx = _base_ctx()
        ctx['is_zero_state'] = True
        ctx['words_total'] = 0
        markup = _strip_inline_style(_render_content(ctx))
        assert 'dash-welcome--fullscreen' in markup
        assert 'data-zero-state="true"' in markup

    def test_zero_state_hides_hero_plan_and_sections(self):
        ctx = _base_ctx()
        ctx['is_zero_state'] = True
        markup = _strip_inline_style(_render_content(ctx))
        assert 'dash-hero' not in markup
        assert 'dash-plan' not in markup
        assert 'dash-race-strip' not in markup
        assert 'dash-social-row' not in markup


class TestSmokeMidPlan:
    """Smoke: streak > 0, mission in progress → hero CTA, roadmap, 3-col social."""

    def _ctx(self):
        ctx = _base_ctx()
        ctx['streak'] = 5
        ctx['streak_status'] = {'coins_balance': 10, 'can_repair': False}
        ctx['mission_plan'] = _make_mission_plan([True, False, False])
        ctx['plan_completion'] = {'ph0': True, 'ph1': False, 'ph2': False}
        ctx['plan_steps_total'] = 3
        ctx['plan_steps_done'] = 1
        ctx['required_steps'] = 3
        ctx['hero_cta'] = {
            'kind': 'continue',
            'title': 'Продолжить: Новый урок',
            'url': '/stub/learn/phase/ph1',
        }
        ctx['rank_info'] = {
            'code': 'explorer',
            'display_name': 'Исследователь',
            'icon': '🧭',
            'color': '#4c9',
            'plans_completed': 10,
            'next_threshold': 21,
            'next_display_name': 'Студент',
            'is_max': False,
            'progress_percent': 48,
        }
        ctx['xp_leaderboard'] = [
            {'id': 1, 'username': 'stub', 'total_xp': 120, 'level': 2},
            {'id': 2, 'username': 'other', 'total_xp': 80, 'level': 1},
        ]
        ctx['user_xp_rank'] = 1
        return ctx

    def test_hero_cta_points_to_next_phase(self):
        markup = _strip_inline_style(_render_content(self._ctx()))
        # Hero CTA: 'continue' variant with next-phase title + url
        assert 'data-hero-cta="continue"' in markup
        assert 'Продолжить: Новый урок' in markup
        assert 'href="/stub/learn/phase/ph1"' in markup

    def test_single_progress_indicator_roadmap_only(self):
        markup = _strip_inline_style(_render_content(self._ctx()))
        # Mission plan header + roadmap track rendered
        assert 'dash-mission-header' in markup
        assert 'dash-roadmap' in markup
        # Removed progress indicators (Task 5)
        assert 'dash-plan__progress-bar' not in markup
        assert 'dash-roadmap__marker-distance' not in markup
        assert 'dash-route-board' not in markup
        # Other removed blocks
        assert 'dash-day-secured' not in markup
        assert 'dash-rival-strip' not in markup

    def test_social_row_three_columns_with_rank(self):
        markup = _strip_inline_style(_render_content(self._ctx()))
        assert 'dash-social-row' in markup
        assert 'dash-rank' in markup               # rank card (Task 13)
        assert 'dash-leaderboard' in markup
        # Legacy welcome card stays hidden in non-zero-state
        assert 'dash-welcome' not in markup


class TestSmokePlanDone:
    """Smoke: all required phases done → completion summary + done/extra CTA."""

    def _ctx_done(self):
        ctx = _base_ctx()
        ctx['streak'] = 8
        ctx['streak_status'] = {'coins_balance': 12, 'can_repair': False}
        ctx['mission_plan'] = _make_mission_plan([True, True, True])
        ctx['plan_completion'] = {'ph0': True, 'ph1': True, 'ph2': True}
        ctx['plan_steps_total'] = 3
        ctx['plan_steps_done'] = 3
        ctx['required_steps'] = 3
        ctx['completion_summary'] = {
            'mission_title': 'Продвигаемся вперёд',
            'today_xp': 120,
            'streak_multiplier': 1.1,
            'level': 3,
            'xp_to_next': 50,
            'xp_progress_percent': 70,
            'streak': 8,
            'race_rank': None,
            'race_total': None,
            'rank_display_name': None,
            'rank_icon': None,
            'rank_color': '#888',
            'rank_is_max': False,
            'rank_plans_to_next': 0,
            'rank_next_display_name': '',
            'rank_progress_percent': 0,
            'new_badges': [],
        }
        return ctx

    def test_completion_summary_rendered_when_all_done(self):
        markup = _strip_inline_style(_render_content(self._ctx_done()))
        assert 'dash-completion-summary' in markup
        assert 'Миссия выполнена' in markup
        assert '+120 XP' in markup

    def test_done_cta_when_no_extra_budget(self):
        ctx = self._ctx_done()
        ctx['hero_cta'] = {
            'kind': 'done',
            'title': '\U0001F3C1 План готов \u2014 до завтра!',
            'url': None,
        }
        markup = _strip_inline_style(_render_content(ctx))
        assert 'data-hero-cta="done"' in markup
        assert 'План готов' in markup
        # Done-state with url=None renders a <span>, not an <a>
        assert '<span class="dash-hero__cta dash-hero__cta--done"' in markup

    def test_extra_cta_when_review_budget_remains(self):
        ctx = self._ctx_done()
        ctx['hero_cta'] = {
            'kind': 'extra',
            'title': 'Ещё тренировка: Карточки \u2192',
            'url': '/stub/study.cards?from=daily_plan',
        }
        markup = _strip_inline_style(_render_content(ctx))
        assert 'data-hero-cta="extra"' in markup
        assert 'Ещё тренировка: Карточки' in markup
        assert '/stub/study.cards?from=daily_plan' in markup


class TestSmokeLegacy:
    """Smoke: user without ``mission_plan`` falls back to legacy layout."""

    def _ctx_legacy(self):
        ctx = _base_ctx()
        ctx['streak'] = 2
        ctx['streak_status'] = {'coins_balance': 3, 'can_repair': False}
        ctx['mission_plan'] = None  # triggers legacy branch
        ctx['hero_cta'] = {
            'kind': 'fallback',
            'title': 'Открыть план \u2192',
            'url': '#dash-plan',
        }
        return ctx

    def test_legacy_branch_no_mission_markers(self):
        markup = _strip_inline_style(_render_content(self._ctx_legacy()))
        # Mission-only markers must not leak into legacy render
        assert 'dash-mission-header' not in markup
        assert 'data-mission-plan' not in markup
        assert 'dash-completion-summary' not in markup
        assert 'dash-roadmap' not in markup

    def test_legacy_branch_renders_fallback_cta(self):
        markup = _strip_inline_style(_render_content(self._ctx_legacy()))
        assert 'data-hero-cta="fallback"' in markup
        assert 'Открыть план' in markup
        assert 'href="#dash-plan"' in markup

    def test_legacy_branch_shows_hero_and_plan_wrapper(self):
        """Legacy users still see the hero card and the `План на сегодня` wrapper."""
        markup = _strip_inline_style(_render_content(self._ctx_legacy()))
        assert 'dash-hero' in markup
        # Plan wrapper heading always renders; legacy branch fills it with
        # non-mission content which is managed elsewhere.
        assert 'dash-plan' in markup
        assert 'План на сегодня' in markup
