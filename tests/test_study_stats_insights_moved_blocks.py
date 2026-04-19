"""Tests for Task 16 of the compact dashboard redesign.

Task 16 moves the blocks removed from the dashboard into their dedicated
homes:

* ``/study/stats`` — Best Study Time, This Week's Stats, Route Board
* ``/study/insights`` — Reading Speed (with delta), Streak Milestones

These tests are file-level (no DB): they render the page templates with
Jinja2 directly against representative context dicts and assert on the
rendered markup. They also assert on the routes file to verify the
widget functions are wired in.
"""
import os
from datetime import datetime

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


_TEMPLATES_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates'
)
_STATS_TPL = os.path.join(_TEMPLATES_DIR, 'study', 'stats.html')
_INSIGHTS_TPL = os.path.join(_TEMPLATES_DIR, 'study', 'insights.html')
_STUDY_ROUTES = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'study', 'routes.py'
)


def _read(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _extract_content_block(tpl_source: str) -> str:
    start = tpl_source.index('{% block content %}') + len('{% block content %}')
    end = tpl_source.index('{% endblock %}', start)
    return tpl_source[start:end]


def _strip_inline_style(html: str) -> str:
    out = html
    while '<style>' in out and '</style>' in out:
        s = out.index('<style>')
        e = out.index('</style>', s) + len('</style>')
        out = out[:s] + out[e:]
    return out


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=True,
        undefined=ChainableUndefined,
    )
    env.globals['url_for'] = lambda endpoint, **kw: f'/stub/{endpoint}'
    env.globals['_'] = lambda s: s
    env.globals['gettext'] = lambda s: s
    env.globals['csrf_token'] = lambda: 'stub-csrf'
    env.globals['config'] = {}
    return env


def _render_stats(**overrides) -> str:
    source = _read(_STATS_TPL)
    block = _extract_content_block(source)
    env = _env()
    ctx = {
        'total_items': 100,
        'mastered_items': 30,
        'mastery_percentage': 30,
        'study_streak': 5,
        'recent_sessions': [],
        'accuracy_trend': None,
        'mastered_over_time': None,
        'study_heatmap': {'data': [], 'day_names': []},
        'best_study_time': None,
        'session_stats': None,
        'route_progress_state': None,
        'telegram_linked': False,
    }
    ctx.update(overrides)
    rendered = env.from_string(block).render(**ctx)
    return _strip_inline_style(rendered)


def _render_insights(**overrides) -> str:
    source = _read(_INSIGHTS_TPL)
    block = _extract_content_block(source)
    env = _env()
    ctx = {
        'summary': {
            'total_words_learned': 0,
            'total_lessons': 0,
            'total_hours': 0,
            'current_streak_days': 0,
            'books_enrolled': 0,
            'grammar_topics_practiced': 0,
            'total_words_review': 0,
        },
        'heatmap': [],
        'best_time': None,
        'at_risk_words': [],
        'grammar_weaknesses': [],
        'reading_trend': None,
        'milestone_history': None,
    }
    ctx.update(overrides)
    rendered = env.from_string(block).render(**ctx)
    return _strip_inline_style(rendered)


# ---------------------------------------------------------------------------
# /study/stats: Best Study Time
# ---------------------------------------------------------------------------


class TestStudyStatsBestTime:
    def test_best_time_section_renders_when_data_present(self):
        bst = {
            'best_hour': 14,
            'hourly_scores': {9: 80.0, 14: 92.5, 18: 75.0},
        }
        markup = _render_stats(best_study_time=bst)
        assert 'stats-best-time' in markup
        assert '14:00' in markup

    def test_best_time_chart_bars_rendered(self):
        bst = {
            'best_hour': 10,
            'hourly_scores': {h: float(h * 3) for h in range(24)},
        }
        markup = _render_stats(best_study_time=bst)
        # One <div class="stats-best-time__bar"...> per hour (0..23).
        assert markup.count('<div class="stats-best-time__bar') == 24
        assert 'stats-best-time__bar--best' in markup

    def test_best_time_hidden_when_no_data(self):
        markup = _render_stats(best_study_time={'best_hour': None, 'hourly_scores': {}})
        assert 'stats-best-time' not in markup

    def test_best_time_hidden_when_none(self):
        markup = _render_stats(best_study_time=None)
        assert 'stats-best-time' not in markup


# ---------------------------------------------------------------------------
# /study/stats: This Week's Stats
# ---------------------------------------------------------------------------


class TestStudyStatsWeekStats:
    def test_week_stats_renders_four_cards(self):
        stats = {
            'period_days': 7,
            'total_sessions': 12,
            'total_words_studied': 180,
            'accuracy_percent': 85.5,
            'total_time_seconds': 3600,
        }
        markup = _render_stats(session_stats=stats)
        assert 'stats-week' in markup
        assert markup.count('stats-week__card') == 4
        assert '12' in markup
        assert '180' in markup
        assert '85.5%' in markup
        assert '60' in markup  # 3600 / 60 minutes

    def test_week_stats_hidden_when_missing(self):
        markup = _render_stats(session_stats=None)
        assert 'stats-week__grid' not in markup


# ---------------------------------------------------------------------------
# /study/stats: Route Board Checkpoint bar
# ---------------------------------------------------------------------------


class TestStudyStatsRouteBoard:
    def test_route_board_renders_when_state_present(self):
        rp = {
            'steps_today': 0,
            'total_steps': 42,
            'checkpoint_number': 2,
            'steps_to_next_checkpoint': 8,
            'percent_to_checkpoint': 60,
        }
        markup = _render_stats(route_progress_state=rp)
        assert 'stats-route-board' in markup
        assert 'Контрольная точка' in markup
        assert '2' in markup
        assert 'stats-route-board__bar-fill' in markup
        assert 'width: 60%' in markup

    def test_route_board_shows_first_checkpoint_when_zero(self):
        rp = {
            'steps_today': 0,
            'total_steps': 0,
            'checkpoint_number': 0,
            'steps_to_next_checkpoint': 20,
            'percent_to_checkpoint': 0,
        }
        markup = _render_stats(route_progress_state=rp)
        assert 'stats-route-board' in markup
        assert 'До первой точки' in markup

    def test_route_board_hidden_when_none(self):
        markup = _render_stats(route_progress_state=None)
        assert 'stats-route-board' not in markup


# ---------------------------------------------------------------------------
# /study/stats: route wires widget functions
# ---------------------------------------------------------------------------


class TestStudyStatsRouteWires:
    def test_stats_route_imports_best_study_time(self):
        src = _read(_STUDY_ROUTES)
        assert 'get_best_study_time' in src

    def test_stats_route_imports_session_service(self):
        src = _read(_STUDY_ROUTES)
        assert 'SessionService' in src
        assert 'get_session_stats' in src

    def test_stats_route_imports_route_state(self):
        src = _read(_STUDY_ROUTES)
        assert 'get_route_state' in src

    def test_stats_route_passes_widgets_to_template(self):
        src = _read(_STUDY_ROUTES)
        assert 'best_study_time=' in src
        assert 'session_stats=' in src
        assert 'route_progress_state=' in src

    def test_stats_route_syncs_route_progress_before_reading_state(self):
        """Without this sync, /study/stats can lag behind mission progress when
        the user visits it before the dashboard path persists today's phases."""
        src = _read(_STUDY_ROUTES)
        # The /study/stats route must call add_route_steps_idempotent to
        # persist completed phases from today's plan before reading state,
        # matching what the dashboard route does.
        assert 'add_route_steps_idempotent' in src
        # It must compute plan_completion from the unified daily plan.
        assert 'get_daily_plan_unified' in src
        assert 'compute_plan_steps' in src
        # steps_today is derived from phase weights, not hard-coded 0.
        assert 'get_phase_step_weight' in src

    def test_stats_route_keeps_persisted_state_when_sync_fails(self):
        """A sync failure should not blank the whole route board; the route still
        attempts get_route_state as a fallback using persisted data."""
        src = _read(_STUDY_ROUTES)
        assert 'route_progress sync failed' in src
        assert 'route_progress_state = get_route_state(current_user.id, steps_today, db.session)' in src


# ---------------------------------------------------------------------------
# /study/insights: Reading Speed sparkline + delta
# ---------------------------------------------------------------------------


class TestStudyInsightsReadingSpeed:
    def test_reading_trend_renders_sparkline_and_delta(self):
        trend = [
            {'week': '2026-W10', 'avg_wpm': 100.0},
            {'week': '2026-W11', 'avg_wpm': 120.0},
            {'week': '2026-W12', 'avg_wpm': 140.0},
        ]
        markup = _render_insights(reading_trend=trend)
        assert 'insights-reading-summary' in markup
        assert 'insights-reading-summary__value' in markup
        assert '140' in markup  # current wpm
        assert 'insights-reading-summary__delta' in markup
        assert 'insights-reading-summary__delta--up' in markup
        assert '+40' in markup  # delta from 100 -> 140
        assert 'insights-reading-sparkline' in markup
        assert markup.count('<div class="insights-reading-sparkline__bar') == 3
        assert 'insights-reading-sparkline__bar--current' in markup

    def test_reading_trend_shows_down_delta(self):
        trend = [
            {'week': '2026-W10', 'avg_wpm': 200.0},
            {'week': '2026-W11', 'avg_wpm': 150.0},
        ]
        markup = _render_insights(reading_trend=trend)
        assert 'insights-reading-summary__delta--down' in markup
        assert '-50' in markup

    def test_reading_trend_single_point_no_delta(self):
        trend = [{'week': '2026-W12', 'avg_wpm': 120.0}]
        markup = _render_insights(reading_trend=trend)
        assert 'insights-reading-summary__value' in markup
        # delta container hidden for single-point data
        assert 'insights-reading-summary__delta' not in markup

    def test_reading_trend_hidden_when_empty(self):
        markup = _render_insights(reading_trend=None)
        assert 'insights-reading-summary' not in markup
        assert 'insights-reading-sparkline' not in markup


# ---------------------------------------------------------------------------
# /study/insights: Streak Milestones Timeline
# ---------------------------------------------------------------------------


class TestStudyInsightsMilestones:
    def test_milestones_renders_all_five_targets(self):
        markup = _render_insights(milestone_history=[])
        assert 'insights-milestones' in markup
        assert '7д' in markup
        assert '14д' in markup
        assert '30д' in markup
        assert '60д' in markup
        assert '100д' in markup

    def test_milestones_marks_earned_ones(self):
        history = [
            {'streak': 7, 'reward': 10, 'date': datetime(2026, 3, 1)},
            {'streak': 14, 'reward': 20, 'date': datetime(2026, 3, 15)},
        ]
        markup = _render_insights(milestone_history=history)
        assert 'insights-milestones__item--earned' in markup
        assert '01.03' in markup
        assert '15.03' in markup

    def test_milestones_marks_next_unearned_target(self):
        history = [
            {'streak': 7, 'reward': 10, 'date': datetime(2026, 3, 1)},
        ]
        markup = _render_insights(milestone_history=history)
        # next earned after 7 should be 14
        assert 'insights-milestones__item--next' in markup

    def test_milestones_empty_shows_placeholder(self):
        markup = _render_insights(milestone_history=None)
        assert 'insights-milestones' in markup
        assert 'Занимайтесь каждый день' in markup

    def test_milestones_always_present(self):
        # Milestone section renders even without history (different from
        # dashboard which hid it completely).
        markup = _render_insights(milestone_history=[])
        assert 'insights-milestones__timeline' in markup


# ---------------------------------------------------------------------------
# /study/insights: route wires milestone_history
# ---------------------------------------------------------------------------


class TestStudyInsightsRouteWires:
    def test_insights_route_imports_milestone_history(self):
        src = _read(_STUDY_ROUTES)
        assert 'get_milestone_history' in src

    def test_insights_route_passes_milestone_history_to_template(self):
        src = _read(_STUDY_ROUTES)
        assert 'milestone_history=milestone_history' in src


# ---------------------------------------------------------------------------
# Empty states render without errors
# ---------------------------------------------------------------------------


class TestEmptyStatesRender:
    def test_stats_page_renders_with_all_empty_data(self):
        markup = _render_stats()
        # page still renders recent sessions area (empty-state copy)
        assert 'stats-sessions' in markup
        # new sections absent when data missing
        assert 'stats-best-time' not in markup
        assert 'stats-week__grid' not in markup
        assert 'stats-route-board' not in markup

    def test_insights_page_renders_with_all_empty_data(self):
        markup = _render_insights()
        assert 'insights-summary' in markup
        # milestones always shown with placeholder
        assert 'insights-milestones' in markup
        # reading trend hidden when empty
        assert 'insights-reading-summary' not in markup
