"""Tests for Task 12 of the compact dashboard redesign.

Task 12 removes the Grammar Levels (A0-C2) breakdown widget from the
dashboard and keeps the 4-card Progress Overview grid with per-focus
card reordering (grammar / reading / vocabulary / default).
"""
import os

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


def _base_ctx(onboarding_focus=None, grammar_levels_summary=None):
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
        'onboarding_focus': onboarding_focus,
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
        'grammar_levels_summary': grammar_levels_summary,
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


def _render_content(onboarding_focus=None, grammar_levels_summary=None):
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
    ctx = _base_ctx(
        onboarding_focus=onboarding_focus,
        grammar_levels_summary=grammar_levels_summary,
    )
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


def _card_positions(markup: str):
    """Return the ordered list of card kinds as they appear in the markup."""
    slugs = {
        'dash-progress__card--words': 'words',
        'dash-progress__card--grammar': 'grammar',
        'dash-progress__card--courses': 'courses',
        'dash-progress__card--books': 'books',
    }
    overview_start = markup.index('dash-progress-overview__grid')
    # Take only the markup inside the progress overview block.
    overview_end_candidates = [
        markup.find('</div>\n    </div>\n\n    <!-- Section 7', overview_start),
        markup.find('<!-- Section 7', overview_start),
    ]
    # Pick the earliest valid boundary after overview_start.
    overview_end = min(x for x in overview_end_candidates if x > 0)
    chunk = markup[overview_start:overview_end]
    hits = []
    for cls, kind in slugs.items():
        idx = chunk.find(cls)
        if idx >= 0:
            hits.append((idx, kind))
    hits.sort()
    return [kind for _, kind in hits]


class TestGrammarLevelsRemoved:
    """Task 12: the grammar-by-level widget is gone from the dashboard."""

    def test_dashboard_does_not_render_grammar_levels_markup(self):
        mock_levels = [
            {'level': 'A1', 'topic_count': 10, 'exercises_total': 50, 'exercises_mastered': 30, 'progress_pct': 60.0},
            {'level': 'A2', 'topic_count': 8, 'exercises_total': 40, 'exercises_mastered': 10, 'progress_pct': 25.0},
        ]
        markup = _render_content(grammar_levels_summary=mock_levels)
        assert 'dash-grammar-levels' not in markup
        assert 'dash-grammar-levels__bar' not in markup
        assert 'dash-grammar-levels__heading' not in markup
        assert 'Грамматика по уровням' not in markup

    def test_dashboard_does_not_render_grammar_levels_even_when_empty(self):
        markup = _render_content(grammar_levels_summary=[])
        assert 'dash-grammar-levels' not in markup

    def test_template_source_has_no_grammar_levels_classes(self):
        source = _read_template()
        assert 'dash-grammar-levels' not in source

    def test_template_source_has_no_has_grammar_levels_set(self):
        source = _read_template()
        assert 'has_grammar_levels' not in source


class TestProgressOverviewPreserved:
    """Task 12: the 4-card progress overview remains with per-focus ordering."""

    def test_overview_renders_all_four_cards(self):
        markup = _render_content()
        assert 'dash-progress-overview' in markup
        assert 'dash-progress__card--words' in markup
        assert 'dash-progress__card--grammar' in markup
        assert 'dash-progress__card--courses' in markup
        assert 'dash-progress__card--books' in markup

    def test_ordering_default_no_focus(self):
        markup = _render_content(onboarding_focus=None)
        # default: words, grammar, courses, books
        assert _card_positions(markup) == ['words', 'grammar', 'courses', 'books']

    def test_ordering_focus_grammar(self):
        markup = _render_content(onboarding_focus='grammar')
        assert _card_positions(markup) == ['grammar', 'words', 'courses', 'books']

    def test_ordering_focus_reading(self):
        markup = _render_content(onboarding_focus='reading')
        assert _card_positions(markup) == ['books', 'words', 'grammar', 'courses']

    def test_ordering_focus_vocabulary(self):
        markup = _render_content(onboarding_focus='vocabulary')
        assert _card_positions(markup) == ['words', 'grammar', 'books', 'courses']

    def test_ordering_unknown_focus_falls_back_to_default(self):
        markup = _render_content(onboarding_focus='something-else')
        assert _card_positions(markup) == ['words', 'grammar', 'courses', 'books']

    def test_progress_row_still_present(self):
        markup = _render_content()
        assert 'dash-progress-row' in markup
        assert 'dash-section__heading">Прогресс' in markup
