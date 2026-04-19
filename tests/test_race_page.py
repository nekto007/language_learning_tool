"""Tests for Task 14 of the compact dashboard redesign.

Task 14:
- On the dashboard, the large Daily Race section is replaced with a compact
  strip linking to ``/race``; the strip shows place / total and score for the
  in-progress state, and rank + score + "Итоги" for the finished state.
- A new ``GET /race`` route renders a dedicated page that holds the full
  race UX: 3-tasks block, nudge callout, full leaderboard, rival_above /
  rival_below tasks, CTA button, and the finished-state summary.

These are file-level / template-level tests that do not require a database
connection: they render the dashboard content block with a jinja2
environment pre-populated with a stub context and inspect the output
markup. The same pattern is used by the sibling
``tests/test_dashboard_*`` files added in earlier tasks of this plan.
"""
from __future__ import annotations

import html as html_lib
import os
import re

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)
_RACE_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'race', 'today.html'
)


def _decode_entities(text: str) -> str:
    return html_lib.unescape(text)


def _read_template(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class _StubUser:
    id = 1
    username = 'stub'
    is_authenticated = True
    onboarding_completed = True
    referral_code = 'refcode'
    birth_year = 2000


def _url_for(endpoint, **values):
    if endpoint == 'race.today':
        return '/race'
    if endpoint == 'words.dashboard':
        return '/dashboard'
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


def _mission_plan():
    return {
        'plan_version': 'v1',
        'mission': {
            'type': 'progress',
            'title': 'Продвигаемся',
            'reason_code': 'progress_default',
            'reason_text': 'Идём',
        },
        'primary_goal': {'type': 'complete_lesson', 'title': 'Завершить', 'success_criterion': '1 урок'},
        'primary_source': {'kind': 'normal_course', 'id': '1', 'label': 'English'},
        'phases': [
            {
                'id': 'ph0',
                'phase': 'recall',
                'title': 'Phase 0',
                'source_kind': 'normal_course',
                'mode': 'default',
                'required': True,
                'completed': False,
                'preview': None,
            }
        ],
        'completion': None,
        'day_secured': False,
    }


def _base_ctx(daily_race=None):
    plan = _mission_plan()
    completion = {p['id']: p.get('completed', False) for p in plan['phases']}
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
        'daily_race': daily_race,
        'mission_plan': plan,
        'completion_summary': None,
        'plan_completion': completion,
        'plan_steps': {},
        'phase_urls': {p['id']: '/stub' for p in plan['phases']},
        'cards_url': '/stub/cards',
        'lesson_minutes': 0,
        'words_minutes': 0,
        'required_steps': 1,
        'plan_steps_done': 0,
        'plan_steps_total': 1,
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
            'steps_today': 0,
            'total_steps': 0,
            'checkpoint_number': 0,
            'steps_to_next_checkpoint': 0,
            'percent_to_checkpoint': 0,
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


def _make_env():
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
    return env


def _render_dashboard(daily_race=None):
    tpl_source = _read_template(_TEMPLATE_PATH)
    block_html = _extract_content_block(tpl_source)
    env = _make_env()
    tpl = env.from_string(block_html)
    return _strip_inline_style(tpl.render(**_base_ctx(daily_race=daily_race)))


def _render_race_page(daily_race=None, dashboard_url='/dashboard'):
    tpl_source = _read_template(_RACE_TEMPLATE_PATH)
    block_html = _extract_content_block(tpl_source)
    env = _make_env()
    tpl = env.from_string(block_html)
    rendered = tpl.render(daily_race=daily_race, dashboard_url=dashboard_url)
    return _strip_inline_style(rendered)


def _leaderboard_entry(rank, username='user', score=50, is_me=False, is_bot=False,
                      steps_done=2, steps_total=4, streak=3):
    return {
        'rank': rank,
        'username': username,
        'initials': username[:2].upper() if username else '?',
        'score': score,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'streak': streak,
        'is_me': is_me,
        'is_bot': is_bot,
        'is_complete': False,
        'place_class': {1: 'gold', 2: 'silver', 3: 'bronze'}.get(rank, 'default'),
        'next_step_title': None,
        'next_step_points': 0,
        'route_position': 0,
    }


def _daily_race_in_progress(rank=2, total=4, score=40, place_class='silver'):
    return {
        'rank': rank,
        'place_class': place_class,
        'total': total,
        'score': score,
        'steps_done': 2,
        'steps_total': 4,
        'streak': 3,
        'is_complete': False,
        'rival_above': _leaderboard_entry(rank=1, username='Anna', score=60),
        'rival_below': _leaderboard_entry(rank=3, username='Boris', score=30),
        'gap_up': 20,
        'gap_down': 10,
        'callout': 'Сделай урок, догони Anna',
        'next_step_title': 'Урок 3',
        'next_step_points': 22,
        'duel_target': _leaderboard_entry(rank=1, username='Anna', score=60),
        'has_bot_rivals': False,
        'leaderboard': [
            _leaderboard_entry(rank=1, username='Anna', score=60),
            _leaderboard_entry(rank=2, username='Me', score=40, is_me=True),
            _leaderboard_entry(rank=3, username='Boris', score=30),
        ],
        'route_rivals': [],
        'next_action_title': 'Урок 3',
        'next_action_url': '/lesson/3',
    }


def _daily_race_complete(rank=1, total=5, score=95, place_class='gold'):
    payload = _daily_race_in_progress(rank=rank, total=total, score=score, place_class=place_class)
    payload['is_complete'] = True
    return payload


# =========================================================================
# Dashboard compact strip
# =========================================================================


class TestDashboardCompactStrip:
    """Task 14: dashboard shows only the compact strip — no full race block."""

    def test_strip_renders_when_daily_race_present(self):
        markup = _render_dashboard(daily_race=_daily_race_in_progress())
        assert 'data-race-strip="true"' in markup
        assert 'dash-race-strip' in markup

    def test_strip_links_to_race_page(self):
        markup = _render_dashboard(daily_race=_daily_race_in_progress())
        # Anchor must point at /race (url_for('race.today'))
        m = re.search(
            r'<a[^>]+class="dash-race-strip[^"]*"[^>]+href="([^"]+)"',
            markup,
            flags=re.DOTALL,
        )
        assert m, 'compact strip anchor missing'
        assert m.group(1) == '/race'

    def test_strip_shows_place_and_score_in_progress(self):
        markup = _render_dashboard(
            daily_race=_daily_race_in_progress(rank=2, total=4, score=40)
        )
        text = _decode_entities(markup)
        assert 'Место 2/4' in text
        assert '40 очк' in text
        assert 'Подробнее' in text

    def test_strip_uses_place_class_badge(self):
        markup = _render_dashboard(
            daily_race=_daily_race_in_progress(place_class='silver')
        )
        assert 'dash-race__badge--silver' in markup

    def test_strip_complete_state_shows_rank_and_summary_cta(self):
        markup = _render_dashboard(
            daily_race=_daily_race_complete(rank=1, score=95)
        )
        text = _decode_entities(markup)
        assert 'dash-race-strip--complete' in markup
        assert '1-е место' in text
        assert '95 очк' in text
        assert 'Итоги' in text
        # In-progress placeholders must be absent on the finished strip
        assert 'Подробнее' not in text
        assert 'Место 1/' not in text

    def test_strip_hidden_without_daily_race(self):
        markup = _render_dashboard(daily_race=None)
        assert 'data-race-strip' not in markup
        assert 'dash-race-strip' not in markup

    def test_dashboard_no_longer_renders_full_race_ux(self):
        """The full 3-tasks/leaderboard UX now only lives on /race."""
        markup = _render_dashboard(daily_race=_daily_race_in_progress())
        # These markers belong on /race, not the dashboard
        assert 'dash-race__tasks' not in markup
        assert 'dash-race__nudge' not in markup
        assert 'dash-race__board' not in markup
        assert 'dash-race__list' not in markup
        assert 'dash-race__stats' not in markup
        assert 'dash-race__final' not in markup
        assert 'dash-race__hero' not in markup


# =========================================================================
# /race page
# =========================================================================


class TestRaceTodayPage:
    """Task 14: /race page holds the full race UX previously on dashboard."""

    def test_three_tasks_block_renders(self):
        markup = _render_race_page(daily_race=_daily_race_in_progress())
        assert 'dash-race__tasks' in markup
        # next_step + rival_above + rival_below → three task tiles
        assert markup.count('dash-race__task-index') == 3

    def test_nudge_callout_renders(self):
        markup = _render_race_page(daily_race=_daily_race_in_progress())
        text = _decode_entities(markup)
        assert 'Сделай урок, догони Anna' in text

    def test_full_leaderboard_renders(self):
        markup = _render_race_page(daily_race=_daily_race_in_progress())
        assert 'dash-race__board' in markup
        # All three leaderboard rows present
        assert markup.count('dash-race__row') >= 3
        assert 'dash-race__row--me' in markup

    def test_rival_above_and_below_tasks_labelled(self):
        markup = _render_race_page(daily_race=_daily_race_in_progress())
        text = _decode_entities(markup)
        assert 'Сократи отрыв до Anna' in text
        assert 'Удержи позицию перед Boris' in text

    def test_cta_button_links_to_next_action(self):
        markup = _render_race_page(daily_race=_daily_race_in_progress())
        # Accept either order of attributes (href / class)
        m = re.search(
            r'<a\s+href="([^"]+)"\s+class="dash-race__cta"',
            markup,
            flags=re.DOTALL,
        ) or re.search(
            r'<a\s+class="dash-race__cta"\s+href="([^"]+)"',
            markup,
            flags=re.DOTALL,
        )
        assert m, 'race CTA anchor missing'
        assert m.group(1) == '/lesson/3'
        assert 'Открыть: Урок 3' in _decode_entities(markup)

    def test_finished_state_shows_rank_summary(self):
        markup = _render_race_page(daily_race=_daily_race_complete(rank=1, score=95))
        text = _decode_entities(markup)
        assert 'dash-race--complete' in markup
        assert 'dash-race__final' in markup
        assert 'Гонка завершена' in text
        assert '95 очков' in text
        # Finished state suppresses the in-progress stats/tasks block
        assert 'dash-race__stats' not in markup
        assert 'dash-race__tasks' not in markup

    def test_back_link_points_to_dashboard(self):
        markup = _render_race_page(
            daily_race=_daily_race_in_progress(), dashboard_url='/dashboard'
        )
        m = re.search(
            r'<a\s+href="([^"]+)"\s+class="race-page__back"',
            markup,
            flags=re.DOTALL,
        ) or re.search(
            r'<a\s+class="race-page__back"\s+href="([^"]+)"',
            markup,
            flags=re.DOTALL,
        )
        assert m, 'back link missing'
        assert m.group(1) == '/dashboard'

    def test_empty_state_when_race_unavailable(self):
        markup = _render_race_page(daily_race=None)
        assert 'data-race-empty="true"' in markup
        text = _decode_entities(markup)
        assert 'Гонка дня недоступна' in text
        # No leaderboard rendering if race is None
        assert 'dash-race__list' not in markup


# =========================================================================
# Blueprint registration
# =========================================================================


class TestRaceBlueprintWiring:
    """The ``race`` blueprint must be defined and wired into the app factory.

    We avoid instantiating the full Flask app (which needs a live Postgres)
    and instead inspect the module state + factory source. When the project
    is run under CI (with Postgres up), the full render path is exercised
    by the broader dashboard integration tests.
    """

    def test_race_blueprint_importable(self):
        from app.race import race_bp
        assert race_bp.name == 'race'

    def test_race_today_endpoint_defined(self):
        """The blueprint must expose a ``today`` view function at ``/race``."""
        from app.race import race_bp
        from app.race import routes as race_routes
        assert callable(getattr(race_routes, 'today', None)), (
            'app.race.routes.today must be a view function'
        )
        # Before app-level registration, route decorators register via
        # deferred_functions. Confirm at least one was recorded (the @route
        # decorator adds one for /race).
        assert race_bp.deferred_functions, (
            'race_bp must have at least one deferred registration'
        )

    def test_app_factory_registers_race_blueprint(self):
        factory_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', '__init__.py'
        )
        with open(factory_path, 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'from app.race import race_bp' in source
        assert 'app.register_blueprint(race_bp)' in source
