"""Tests for Task 15 of the compact dashboard redesign.

Task 15 removes three dashboard sections:
- Section 5 (Stats: Best Study Time + This Week's Stats)
- Section 8 (Insights: Reading Speed + Streak Milestones)
- Section 9 (Quick Actions)

and adds links pointing to /study/stats (from Activity) and
/study/insights (from Social) in their place.
"""
import os

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)
_ROUTE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'words', 'routes.py'
)


def _read_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def _read_route() -> str:
    with open(_ROUTE_PATH, 'r', encoding='utf-8') as f:
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


def _mission_plan():
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


def _base_ctx():
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
        'daily_race': None,
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
        'words_total': 100,
        'words_in_progress': 5,
        'words_stats': {'new': 0, 'learning': 0, 'review': 0, 'mastered': 0},
        'books_reading': 2,
        'recent_book': None,
        'grammar_total': 50,
        'grammar_studied': 20,
        'grammar_mastered': 10,
        'courses_enrolled': 1,
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


def _render_content(**overrides):
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
    ctx = _base_ctx()
    ctx.update(overrides)
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


class TestStatsSectionRemoved:
    """Section 5 (Best Study Time + This Week's Stats) is removed."""

    def test_dashboard_does_not_render_study_time_widget(self):
        markup = _render_content()
        assert 'dash-study-time' not in markup

    def test_dashboard_does_not_render_week_stats_widget(self):
        markup = _render_content()
        assert 'dash-week-stats' not in markup

    def test_dashboard_does_not_render_stats_row(self):
        markup = _render_content()
        assert 'dash-stats-row' not in markup

    def test_template_source_has_no_study_time_classes(self):
        source = _read_template()
        assert 'dash-study-time' not in source
        assert 'dash-week-stats' not in source
        assert 'dash-stats-row' not in source

    def test_stats_heading_not_rendered(self):
        markup = _render_content()
        assert '<h2 class="dash-section__heading">Статистика</h2>' not in markup


class TestInsightsSectionRemoved:
    """Section 8 (Reading Speed + Streak Milestones) is removed."""

    def test_dashboard_does_not_render_reading_speed_widget(self):
        markup = _render_content()
        assert 'dash-reading-speed' not in markup
        assert 'dash-sparkline' not in markup

    def test_dashboard_does_not_render_milestones_widget(self):
        markup = _render_content()
        assert 'dash-milestones' not in markup

    def test_dashboard_does_not_render_insights_row(self):
        markup = _render_content()
        assert 'dash-insights-row' not in markup

    def test_template_source_has_no_insights_classes(self):
        source = _read_template()
        assert 'dash-reading-speed' not in source
        assert 'dash-sparkline' not in source
        assert 'dash-milestones' not in source
        assert 'dash-insights-row' not in source


class TestQuickActionsSectionRemoved:
    """Section 9 (Quick Actions) is removed entirely."""

    def test_dashboard_does_not_render_quick_grid(self):
        markup = _render_content()
        assert 'dash-quick' not in markup

    def test_template_source_has_no_quick_classes(self):
        source = _read_template()
        assert 'dash-quick' not in source


class TestStatsLinkInActivity:
    """Activity section ends with a link to /study/stats."""

    def test_activity_section_contains_stats_link(self):
        markup = _render_content()
        assert 'dash-activity__more' in markup
        assert 'dash-activity__more-link' in markup
        assert 'Подробная статистика' in markup

    def test_stats_link_points_to_study_stats(self):
        markup = _render_content()
        assert '/stub/study.stats' in markup
        link_index = markup.find('dash-activity__more-link')
        assert link_index >= 0
        # The href for the link immediately precedes the class in the markup
        snippet = markup[max(0, link_index - 200):link_index]
        assert '/stub/study.stats' in snippet


class TestInsightsLinkInSocial:
    """Social section ends with a link to /study/insights."""

    def test_social_section_contains_insights_link(self):
        markup = _render_content()
        assert 'dash-social-row__more' in markup
        assert 'dash-social-row__more-link' in markup
        assert 'Аналитика обучения' in markup

    def test_insights_link_points_to_study_insights(self):
        markup = _render_content()
        assert '/stub/study.insights' in markup
        link_index = markup.find('dash-social-row__more-link')
        assert link_index >= 0
        snippet = markup[max(0, link_index - 200):link_index]
        assert '/stub/study.insights' in snippet


class TestRouteStopsComputingDeletedWidgets:
    """app/words/routes.py no longer computes or passes widgets for removed sections."""

    def test_route_does_not_import_best_study_time(self):
        source = _read_route()
        assert 'get_best_study_time' not in source

    def test_route_does_not_import_reading_speed_trend(self):
        source = _read_route()
        assert 'get_reading_speed_trend' not in source

    def test_route_does_not_import_milestone_history(self):
        source = _read_route()
        assert 'get_milestone_history' not in source

    def test_route_does_not_import_session_service(self):
        source = _read_route()
        assert 'from app.study.services.session_service import SessionService' not in source

    def test_route_does_not_pass_best_study_time_to_template(self):
        source = _read_route()
        assert 'best_study_time=' not in source

    def test_route_does_not_pass_session_stats_to_template(self):
        source = _read_route()
        assert 'session_stats=' not in source

    def test_route_does_not_pass_milestone_history_to_template(self):
        source = _read_route()
        assert 'milestone_history=' not in source

    def test_route_does_not_pass_reading_speed_trend_to_template(self):
        source = _read_route()
        assert 'reading_speed_trend=' not in source


class TestZeroStateUnaffected:
    """Zero-state rendering still bypasses the dashboard body entirely."""

    def test_zero_state_still_renders_only_welcome(self):
        markup = _render_content(is_zero_state=True)
        assert 'dash-welcome--fullscreen' in markup
        assert 'dash-activity__more' not in markup
        assert 'dash-social-row__more' not in markup
