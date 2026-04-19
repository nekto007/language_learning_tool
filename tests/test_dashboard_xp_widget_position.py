"""Tests for Task 7 of the compact dashboard redesign.

Task 7 moves the standalone `.dash-xp` widget that lived right after the hero
into the `.dash-plan` card, directly under the mission header and before the
phase cards / roadmap. The `.dash-xp-levelup` overlay stays but remains
viewport-centered (position: fixed), not hero-relative.
"""
import os
import re

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)


def _read_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


class _StubUser:
    id = 1
    username = 'stub'
    is_authenticated = True
    onboarding_completed = True
    referral_code = 'refcode'
    birth_year = 2000


def _url_for(endpoint, **values):
    return f'/stub/{endpoint}'


def _extract_content_block(tpl: str) -> str:
    start_tag = '{% block content %}'
    end_tag = '{% endblock %}'
    start_idx = tpl.index(start_tag) + len(start_tag)
    end_idx = tpl.index(end_tag, start_idx)
    return tpl[start_idx:end_idx]


def _strip_inline_style(html: str) -> str:
    out = html
    while '<style>' in out and '</style>' in out:
        start = out.index('<style>')
        end = out.index('</style>', start) + len('</style>')
        out = out[:start] + out[end:]
    return out


def _mission_plan(done_states=(False, False, False)):
    kinds = ('recall', 'learn', 'use', 'check')
    phases = []
    for i, done in enumerate(done_states):
        phases.append({
            'id': f'ph{i}',
            'phase': kinds[i % 4],
            'title': f'Phase {i}',
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
            'reason_text': 'Идём дальше',
        },
        'primary_goal': {'type': 'complete_lesson', 'title': 'Завершить урок', 'success_criterion': '1 урок'},
        'primary_source': {'kind': 'normal_course', 'id': '1', 'label': 'English Basics'},
        'phases': phases,
        'completion': None,
        'day_secured': False,
    }


def _base_ctx(mission_plan, mission_level_info=None, xp_level_up=None):
    completion = {p['id']: p.get('completed', False) for p in mission_plan['phases']}
    return {
        'is_zero_state': False,
        'unseen_badges': None,
        'greeting': 'Привет',
        'streak': 0,
        'streak_status': None,
        'streak_repaired': False,
        'hero_cta': None,
        'rank_info': None,
        'mission_level_info': mission_level_info,
        'xp_level_up': xp_level_up,
        'daily_race': None,
        'mission_plan': mission_plan,
        'completion_summary': None,
        'plan_completion': completion,
        'plan_steps': {},
        'phase_urls': {p['id']: '/stub' for p in mission_plan['phases']},
        'cards_url': '/stub/cards',
        'lesson_minutes': 0,
        'words_minutes': 0,
        'required_steps': 1,
        'plan_steps_done': sum(1 for v in completion.values() if v),
        'plan_steps_total': len(completion),
        'plan_meta': None,
        'rival_strip': None,
        'plan_today': '2026-04-19',
        'words_total': 1,
        'words_in_progress': 0,
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
        'best_study_time': None,
        'session_stats': {
            'total_sessions': 0,
            'total_words_studied': 0,
            'accuracy_percent': 0,
            'total_time_seconds': 0,
        },
        'xp_leaderboard': [],
        'user_xp_rank': None,
        'achievements_by_category': {},
        'milestone_history': [],
        'reading_speed_trend': None,
        'grammar_levels_summary': {},
        'weekly_analytics': None,
        'continue_lesson': None,
        'grammar_user_stats': None,
        'badges_showcase': None,
        'weekly_digest': None,
        'route_metadata': None,
        'route_progress_state': {
            'steps_today': 5,
            'total_steps': 25,
            'checkpoint_number': 1,
            'steps_to_next_checkpoint': 15,
            'percent_to_checkpoint': 25,
        },
        'yesterday_summary': None,
        'yesterday': None,
        'daily_summary': {
            'lessons_count': 0,
            'grammar_exercises': 0,
            'grammar_correct': 0,
            'words_reviewed': 0,
            'books_read': [],
        },
        'show_daily_summary_header': False,
    }


def _render_content(mission_level_info=None, xp_level_up=None, done_states=(False, False, False)):
    tpl_source = _read_template()
    block_html = _extract_content_block(tpl_source)
    tpl_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
    env = Environment(
        loader=FileSystemLoader(tpl_dir),
        autoescape=True,
        undefined=ChainableUndefined,
    )
    env.globals['url_for'] = _url_for
    env.globals['current_user'] = _StubUser()
    env.globals['csrf_token'] = lambda: 'stub-csrf'
    env.globals['config'] = {}
    tpl = env.from_string(block_html)
    plan = _mission_plan(done_states)
    ctx = _base_ctx(plan, mission_level_info=mission_level_info, xp_level_up=xp_level_up)
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


def _level_info(level=2, xp_in_level=40, xp_for_level=100, progress_percent=40, streak_multiplier=1.2):
    return {
        'level': level,
        'xp_in_level': xp_in_level,
        'xp_for_level': xp_for_level,
        'xp_to_next_level': xp_for_level - xp_in_level,
        'progress_percent': progress_percent,
        'total_xp': 100 + xp_in_level,
        'streak_multiplier': streak_multiplier,
    }


class TestMissionXPWidgetPosition:
    """Task 7: `.dash-xp` moves from hero into the plan card."""

    def test_xp_widget_rendered_inside_plan_card(self):
        markup = _render_content(mission_level_info=_level_info())
        plan_start = markup.find('<div class="dash-plan">')
        assert plan_start >= 0, 'dash-plan card should be rendered'
        plan_end = markup.find('</div>\n    <!-- Welcome card', plan_start)
        # fallback: use next section marker
        if plan_end == -1:
            plan_end = len(markup)
        plan_region = markup[plan_start:plan_end]
        assert 'data-xp-widget="true"' in plan_region
        assert 'dash-mission__xp' in plan_region

    def test_xp_widget_is_below_mission_header(self):
        markup = _render_content(mission_level_info=_level_info())
        header_idx = markup.find('dash-mission-header__title')
        xp_idx = markup.find('data-xp-widget="true"')
        assert header_idx >= 0 and xp_idx >= 0
        assert header_idx < xp_idx, 'XP widget must render AFTER the mission header'

    def test_xp_widget_is_above_first_phase_card(self):
        markup = _render_content(mission_level_info=_level_info())
        xp_idx = markup.find('data-xp-widget="true"')
        # Roadmap and phase-card markup only exist inside the plan card
        phase_idx = markup.find('dash-roadmap')
        step_idx = markup.find('dash-step')
        next_content_idx = min(
            (i for i in (phase_idx, step_idx) if i >= 0),
            default=-1,
        )
        assert xp_idx >= 0 and next_content_idx >= 0
        assert xp_idx < next_content_idx, 'XP widget must render BEFORE phase cards / roadmap'

    def test_xp_widget_not_rendered_above_plan_card(self):
        """The widget no longer sits between the hero and the plan card."""
        markup = _render_content(mission_level_info=_level_info())
        plan_start = markup.find('<div class="dash-plan">')
        prelude = markup[:plan_start]
        assert 'data-xp-widget="true"' not in prelude
        assert 'class="dash-xp"' not in prelude

    def test_xp_widget_absent_when_no_mission_level_info(self):
        markup = _render_content(mission_level_info=None)
        assert 'data-xp-widget="true"' not in markup
        assert 'dash-mission__xp' not in markup

    def test_data_xp_hooks_preserved(self):
        """Level-up JS targets these data attributes — they must be intact."""
        markup = _render_content(mission_level_info=_level_info())
        assert 'data-xp-widget="true"' in markup
        assert 'data-xp-level="true"' in markup
        assert 'data-xp-progress="true"' in markup
        assert 'data-xp-multiplier="true"' in markup
        assert 'data-xp-pct="40"' in markup

    def test_levelup_overlay_still_renders(self):
        markup = _render_content(
            mission_level_info=_level_info(),
            xp_level_up={'new_level': 3, 'xp': 300},
        )
        assert 'data-xp-levelup="true"' in markup
        assert 'Новый уровень 3' in markup

    def test_levelup_overlay_is_viewport_centered_not_hero_scoped(self):
        """The overlay uses position: fixed + viewport-anchored coords. Its CSS
        selector must not be nested under .dash-hero."""
        tpl = _read_template()
        # Extract the .dash-xp-levelup rule body
        match = re.search(r'\.dash-xp-levelup\s*\{[^}]*\}', tpl)
        assert match, 'dash-xp-levelup CSS rule must exist'
        body = match.group(0)
        assert 'position: fixed' in body
        assert 'left: 50%' in body
        # No hero-scoped selector like `.dash-hero .dash-xp-levelup`
        assert '.dash-hero .dash-xp-levelup' not in tpl
        assert '.dash-hero__bg .dash-xp-levelup' not in tpl


class TestMissionXPWidgetStyles:
    """Task 7: CSS wrapper for the in-card layout."""

    def test_mission_xp_wrapper_css_present(self):
        tpl = _read_template()
        assert '.dash-mission__xp' in tpl
        # Full-width inside plan card
        body_match = re.search(r'\.dash-mission__xp\s*\{[^}]*\}', tpl)
        assert body_match, 'dash-mission__xp CSS block must exist'
        assert 'width: 100%' in body_match.group(0)

    def test_dash_xp_base_styles_preserved(self):
        tpl = _read_template()
        assert '.dash-xp {' in tpl or '.dash-xp{' in tpl
        assert '.dash-xp__level' in tpl
        assert '.dash-xp__bar' in tpl
        assert '.dash-xp__bar-fill' in tpl
        assert '.dash-xp__multiplier' in tpl
