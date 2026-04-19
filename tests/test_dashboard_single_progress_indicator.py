"""Tests for Task 5 of the compact dashboard redesign.

Task 5 collapses the four redundant progress indicators on the mission plan
down to a single one — the visual roadmap. This module verifies that the
linear 0/3 progress bar, the finish-marker distance label, and the route
board (with its checkpoint bar, day-secured marker, and "checkpoint reached"
label) have all been removed from the dashboard template.
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


def _mission_plan(done_states):
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


def _base_ctx(mission_plan):
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
        'mission_level_info': None,
        'xp_level_up': None,
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


def _render_plan_markup(done_states=(True, False, False), day_secured=False):
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
    plan['day_secured'] = day_secured
    ctx = _base_ctx(plan)
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


class TestSingleProgressIndicator:
    """Task 5: removed progress indicators are absent from the markup."""

    def test_linear_progress_bar_markup_removed_from_template(self):
        tpl = _read_template()
        # The mission-plan branch no longer emits a linear 0/3 bar
        assert 'data-plan-progress="true"' not in tpl
        assert 'data-progress-fill="true"' not in tpl
        assert 'data-progress-pct=' not in tpl

    def test_marker_distance_label_removed_from_template(self):
        tpl = _read_template()
        assert 'data-marker-distance="true"' not in tpl
        assert 'dash-roadmap__marker-distance' not in tpl
        assert 'до финиша' not in tpl

    def test_route_board_block_removed_from_template(self):
        tpl = _read_template()
        assert 'data-route-board="true"' not in tpl
        assert 'data-route-bar-fill="true"' not in tpl
        assert 'data-secured-marker="true"' not in tpl
        assert 'data-checkpoint-reached="true"' not in tpl
        assert 'data-steps-to-checkpoint="true"' not in tpl
        assert 'data-steps-today-label="true"' not in tpl
        # Banner text that lived inside the route board is gone too.
        assert 'Контрольная точка' not in tpl
        assert 'Серия закреплена' not in tpl

    def test_roadmap_track_still_rendered_as_sole_progress_indicator(self):
        markup = _render_plan_markup((True, False, False))
        # The roadmap — nodes, connectors, start/finish markers — is kept.
        assert 'data-roadmap="true"' in markup
        assert 'dash-roadmap__track' in markup
        assert 'data-roadmap-marker="start"' in markup
        assert 'data-roadmap-marker="finish"' in markup
        # Route tokens + swipe hint are also retained.
        assert 'dash-roadmap__swipe-hint' in markup
        # And none of the removed indicators are in the rendered markup either.
        assert 'data-plan-progress="true"' not in markup
        assert 'data-marker-distance="true"' not in markup
        assert 'data-route-board="true"' not in markup

    def test_single_progress_indicator_present_in_rendered_output(self):
        """Only one roadmap track element renders per plan."""
        markup = _render_plan_markup((False, False, False))
        track_hits = len(re.findall(r'class="dash-roadmap__track"', markup))
        assert track_hits == 1, f'expected exactly 1 roadmap track, found {track_hits}'

    def test_route_board_hidden_even_when_day_secured(self):
        markup = _render_plan_markup((True, True, False), day_secured=True)
        # day_secured does not revive the route board.
        assert 'data-route-board="true"' not in markup
        assert 'data-secured-marker="true"' not in markup

    def test_progress_bar_css_scoped_selectors_removed(self):
        tpl = _read_template()
        # The animation hook selectors tied to the removed progress bar are gone.
        assert 'data-plan-progress="true"' not in tpl
        assert 'data-progress-fill="true"' not in tpl
        assert 'dash-progress--animate' not in tpl
        # And the distance-label style rule is gone.
        assert '.dash-roadmap__marker-distance' not in tpl
