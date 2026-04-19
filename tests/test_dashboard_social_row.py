"""Tests for Task 13 of the compact dashboard redesign.

Task 13 rebuilds the Social section as a 3-column grid: Rank (moved from
hero) | XP Leaderboard | Achievements. On mobile (<=768px) the columns
stack vertically. The rank card is enlarged and includes icon +
display_name + plans_completed/next_threshold + progress bar (or
"Максимальный титул" for the top rank).
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


def _rank_info(is_max=False, code='student'):
    if is_max:
        return {
            'code': 'grandmaster',
            'display_name': 'Грандмастер',
            'icon': '👑',
            'color': '#facc15',
            'plans_completed': 400,
            'next_threshold': None,
            'next_display_name': None,
            'progress_percent': 100,
            'is_max': True,
        }
    return {
        'code': code,
        'display_name': 'Студент',
        'icon': '🎓',
        'color': '#22c55e',
        'plans_completed': 30,
        'next_threshold': 50,
        'next_display_name': 'Эксперт',
        'progress_percent': 60,
        'is_max': False,
    }


def _xp_leaderboard():
    return [
        {'id': 99, 'username': 'alice', 'total_xp': 1200, 'level': 5},
        {'id': 98, 'username': 'bob', 'total_xp': 800, 'level': 4},
    ]


def _achievements_by_category():
    return {
        'earned_count': 3,
        'total_achievements': 10,
        'progress_percentage': 30,
        'by_category': {
            'Обучение': [
                {'earned': True, 'earned_at': '2026-04-10', 'achievement': {'icon': '🏆', 'name': 'Первый урок'}},
                {'earned': False, 'earned_at': None, 'achievement': {'icon': '📚', 'name': 'Десять уроков'}},
            ],
        },
    }


def _base_ctx(rank_info=None, xp_leaderboard=None, achievements_by_category=None):
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
        'rank_info': rank_info,
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
        'best_study_time': None,
        'session_stats': {
            'total_sessions': 0,
            'total_words_studied': 0,
            'accuracy_percent': 0,
            'total_time_seconds': 0,
        },
        'xp_leaderboard': xp_leaderboard or [],
        'user_xp_rank': None,
        'achievements_by_category': achievements_by_category or {},
        'milestone_history': [],
        'reading_speed_trend': None,
        'grammar_levels_summary': None,
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


def _render_content(rank_info=None, xp_leaderboard=None, achievements_by_category=None):
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
        rank_info=rank_info,
        xp_leaderboard=xp_leaderboard,
        achievements_by_category=achievements_by_category,
    )
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


def _extract_social_row(markup: str) -> str:
    start = markup.index('<div class="dash-social-row">')
    # Find matching </div> by counting nested <div>.
    cursor = start + len('<div class="dash-social-row">')
    depth = 1
    while depth > 0 and cursor < len(markup):
        next_open = markup.find('<div', cursor)
        next_close = markup.find('</div>', cursor)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            cursor = next_open + 4
        else:
            depth -= 1
            cursor = next_close + len('</div>')
    return markup[start:cursor]


def _top_level_children(social_row: str):
    """Return ordered list of top-level direct-child class tokens in social-row."""
    # Strip the outer dash-social-row wrapper.
    inner = social_row[len('<div class="dash-social-row">'):]
    # Walk, collecting only class names on depth-0 <div>s.
    children = []
    depth = 0
    i = 0
    while i < len(inner):
        if inner.startswith('<div', i):
            # Find the end of this opening tag.
            tag_end = inner.index('>', i)
            tag = inner[i:tag_end + 1]
            if depth == 0:
                # Capture class attribute.
                m = re.search(r'class="([^"]+)"', tag)
                if m:
                    children.append(m.group(1))
            depth += 1
            i = tag_end + 1
        elif inner.startswith('</div>', i):
            depth -= 1
            i += len('</div>')
        else:
            i += 1
    return children


class TestHeroNoLongerRendersRank:
    """Task 13: the rank badge is no longer in the hero area."""

    def test_template_has_no_standalone_rank_comment(self):
        source = _read_template()
        assert 'temporarily standalone between hero' not in source

    def test_rendered_hero_does_not_contain_rank(self):
        markup = _render_content(rank_info=_rank_info())
        hero_start = markup.index('<div class="dash-hero">')
        plan_start = markup.index('class="dash-plan"', hero_start)
        hero_markup = markup[hero_start:plan_start]
        assert 'dash-rank' not in hero_markup
        assert 'data-rank-code' not in hero_markup

    def test_rank_appears_after_dash_plan_in_rendered_markup(self):
        markup = _render_content(
            rank_info=_rank_info(),
            xp_leaderboard=_xp_leaderboard(),
            achievements_by_category=_achievements_by_category(),
        )
        plan_idx = markup.index('class="dash-plan"')
        rank_idx = markup.index('dash-rank--')
        assert rank_idx > plan_idx

    def test_rank_appears_in_social_row_not_hero(self):
        markup = _render_content(
            rank_info=_rank_info(),
            xp_leaderboard=_xp_leaderboard(),
            achievements_by_category=_achievements_by_category(),
        )
        social_row = _extract_social_row(markup)
        assert 'dash-rank' in social_row


class TestSocialRowThreeColumns:
    """Task 13: Social row renders rank + leaderboard + achievements."""

    def test_social_row_has_three_children_when_all_data_present(self):
        markup = _render_content(
            rank_info=_rank_info(),
            xp_leaderboard=_xp_leaderboard(),
            achievements_by_category=_achievements_by_category(),
        )
        social_row = _extract_social_row(markup)
        children = _top_level_children(social_row)
        # Exactly 3 top-level children.
        assert len(children) == 3
        assert 'dash-rank' in children[0]
        assert 'dash-leaderboard' in children[1]
        assert 'dash-achievements' in children[2]

    def test_rank_is_first_column(self):
        markup = _render_content(
            rank_info=_rank_info(),
            xp_leaderboard=_xp_leaderboard(),
            achievements_by_category=_achievements_by_category(),
        )
        social_row = _extract_social_row(markup)
        children = _top_level_children(social_row)
        assert 'dash-rank' in children[0]

    def test_empty_rank_falls_back_to_dash_empty(self):
        markup = _render_content(
            rank_info=None,
            xp_leaderboard=_xp_leaderboard(),
            achievements_by_category=_achievements_by_category(),
        )
        social_row = _extract_social_row(markup)
        children = _top_level_children(social_row)
        assert len(children) == 3
        assert 'dash-empty' in children[0]
        assert 'dash-rank' not in social_row

    def test_all_three_columns_empty_state(self):
        markup = _render_content(
            rank_info=None,
            xp_leaderboard=[],
            achievements_by_category={},
        )
        social_row = _extract_social_row(markup)
        children = _top_level_children(social_row)
        assert len(children) == 3
        assert all('dash-empty' in c for c in children)


class TestRankCardLayout:
    """Task 13: enlarged rank card shows icon + name + progress bar."""

    def test_rank_card_shows_icon_and_name(self):
        markup = _render_content(rank_info=_rank_info())
        social_row = _extract_social_row(markup)
        assert 'dash-rank__icon' in social_row
        assert 'dash-rank__name' in social_row
        assert 'Студент' in social_row

    def test_rank_card_shows_progress_bar_for_non_max(self):
        markup = _render_content(rank_info=_rank_info(is_max=False))
        social_row = _extract_social_row(markup)
        assert 'dash-rank__progress-track' in social_row
        assert 'dash-rank__progress-fill' in social_row
        # "30/50 до «Эксперт»"
        assert '30/50' in social_row
        assert 'Эксперт' in social_row

    def test_rank_card_shows_max_message_for_top_rank(self):
        markup = _render_content(rank_info=_rank_info(is_max=True))
        social_row = _extract_social_row(markup)
        assert 'dash-rank__progress--max' in social_row
        assert 'Максимальный титул' in social_row
        # No track/fill for max rank.
        assert 'dash-rank__progress-track' not in social_row
        assert 'dash-rank__progress-fill' not in social_row

    def test_rank_card_has_heading(self):
        markup = _render_content(rank_info=_rank_info())
        social_row = _extract_social_row(markup)
        assert 'dash-rank__heading' in social_row

    def test_rank_card_applies_rank_code_modifier(self):
        markup = _render_content(rank_info=_rank_info(code='expert'))
        social_row = _extract_social_row(markup)
        assert 'dash-rank--expert' in social_row


class TestSocialRowCSS:
    """Task 13: CSS for the 3-column layout + mobile stacking."""

    def test_css_has_three_column_grid(self):
        source = _read_template()
        # Find the .dash-social-row rule.
        match = re.search(
            r'\.dash-social-row\s*\{[^}]*grid-template-columns:\s*([^;]+);',
            source,
        )
        assert match is not None, 'dash-social-row grid-template-columns rule missing'
        cols = match.group(1).strip()
        assert cols == '1fr 1fr 1fr', f'expected three equal columns, got {cols!r}'

    def test_css_stacks_on_mobile_at_768px(self):
        source = _read_template()
        # Find a media query whose selector block contains .dash-social-row: 1fr.
        pattern = re.compile(
            r'@media\s*\(max-width:\s*(\d+)px\)\s*\{[^{}]*\.dash-social-row[^{}]*\{[^}]*grid-template-columns:\s*1fr\s*;',
            re.DOTALL,
        )
        match = pattern.search(source)
        assert match is not None, 'mobile stacking rule for .dash-social-row missing'
        breakpoint_px = int(match.group(1))
        assert breakpoint_px == 768, f'expected 768px breakpoint, got {breakpoint_px}'

    def test_css_no_longer_uses_640px_breakpoint_for_social(self):
        source = _read_template()
        # The 640px-breakpoint-on-social rule from the old 2-column version must be gone.
        pattern = re.compile(
            r'@media\s*\(max-width:\s*640px\)\s*\{[^{}]*\.dash-social-row\s*\{',
            re.DOTALL,
        )
        assert pattern.search(source) is None


class TestRankCardStylesForCardContext:
    """Task 13: rank styles updated for card context (not dark hero)."""

    def test_rank_card_uses_dash_surface_background(self):
        source = _read_template()
        match = re.search(
            r'\.dash-rank\s*\{[^}]*\}',
            source,
            re.DOTALL,
        )
        assert match is not None
        rule = match.group(0)
        assert 'background: var(--dash-surface)' in rule
        assert 'border: 1px solid var(--dash-border)' in rule

    def test_rank_progress_text_uses_text_var_not_hero_white(self):
        source = _read_template()
        match = re.search(
            r'\.dash-rank__progress-text\s*\{[^}]*\}',
            source,
            re.DOTALL,
        )
        assert match is not None
        rule = match.group(0)
        assert 'var(--dash-text)' in rule
        # Hero-context white-on-transparent color should be gone.
        assert 'rgba(255, 255, 255, 0.92)' not in rule
