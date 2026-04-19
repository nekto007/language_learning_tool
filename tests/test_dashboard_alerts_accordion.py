"""Tests for Task 11 of the compact dashboard redesign.

Task 11 wraps the words-at-risk + grammar-weaknesses block in a collapsible
``<details class="dash-alerts__accordion">`` with a count summary and
removes the ``dash-empty`` fallback entirely — when both collections are
empty, the section must not render at all.
"""
import html as html_lib
import os

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


def _decode_entities(text: str) -> str:
    return html_lib.unescape(text)


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


def _base_ctx(words_at_risk=None, grammar_weaknesses=None):
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
        'words_at_risk': words_at_risk or [],
        'grammar_weaknesses': grammar_weaknesses or [],
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


def _render_content(words_at_risk=None, grammar_weaknesses=None):
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
    ctx = _base_ctx(words_at_risk=words_at_risk, grammar_weaknesses=grammar_weaknesses)
    rendered = tpl.render(**ctx)
    return _strip_inline_style(rendered)


def _risk_word(word='apple', translation='яблоко', days_overdue=3):
    return {'word': word, 'translation': translation, 'days_overdue': days_overdue}


def _weakness(title='Present Simple', attempts=10, accuracy=55):
    return {'title': title, 'attempts': attempts, 'accuracy': accuracy}


class TestAlertsAccordion:
    """Task 11: alerts rendered inside a collapsed <details> accordion."""

    def test_both_empty_section_not_rendered(self):
        markup = _render_content(words_at_risk=[], grammar_weaknesses=[])
        assert 'dash-alerts__accordion' not in markup
        assert 'dash-alerts-row' not in markup
        # Section heading "Внимание" must also be absent
        assert 'Внимание' not in markup
        # The old dash-empty fallback must not appear for alerts
        assert 'Нет слов под угрозой' not in markup
        assert 'отличная работа' not in markup

    def test_accordion_rendered_when_words_at_risk_present(self):
        markup = _render_content(
            words_at_risk=[_risk_word()],
            grammar_weaknesses=[],
        )
        assert 'dash-alerts__accordion' in markup
        # Collapsed by default — no `open` attribute
        assert '<details class="dash-alerts__accordion" open' not in markup
        assert '<details class="dash-alerts__accordion"' in markup
        # Existing inner markup preserved
        assert 'dash-alerts-row' in markup
        assert 'dash-risk' in markup
        assert 'dash-risk__item' in markup

    def test_accordion_rendered_when_grammar_weaknesses_present(self):
        markup = _render_content(
            words_at_risk=[],
            grammar_weaknesses=[_weakness()],
        )
        assert 'dash-alerts__accordion' in markup
        assert 'dash-weakness' in markup
        assert 'dash-weakness__item' in markup

    def test_summary_shows_word_count_singular(self):
        markup = _render_content(
            words_at_risk=[_risk_word()],
            grammar_weaknesses=[],
        )
        summary_start = markup.find('dash-alerts__summary')
        summary_end = markup.find('</summary>', summary_start)
        summary = _decode_entities(markup[summary_start:summary_end])
        # 1 word → "слово"
        assert '1' in summary
        assert 'слово' in summary

    def test_summary_shows_word_count_few(self):
        markup = _render_content(
            words_at_risk=[_risk_word()] * 3,
            grammar_weaknesses=[],
        )
        summary_start = markup.find('dash-alerts__summary')
        summary_end = markup.find('</summary>', summary_start)
        summary = _decode_entities(markup[summary_start:summary_end])
        # 3 words → "слова"
        assert '3' in summary
        assert 'слова' in summary
        # not singular
        assert 'слово ' not in summary
        assert 'слово\n' not in summary

    def test_summary_shows_word_count_many(self):
        markup = _render_content(
            words_at_risk=[_risk_word()] * 7,
            grammar_weaknesses=[],
        )
        summary_start = markup.find('dash-alerts__summary')
        summary_end = markup.find('</summary>', summary_start)
        summary = _decode_entities(markup[summary_start:summary_end])
        # 7 words → "слов" (genitive plural, no trailing vowel)
        assert '7' in summary
        # Collapse whitespace and check for standalone "слов"
        import re
        tokens = re.findall(r'[А-Яа-яёЁ]+', summary)
        assert 'слов' in tokens

    def test_summary_shows_grammar_count(self):
        markup = _render_content(
            words_at_risk=[],
            grammar_weaknesses=[_weakness(), _weakness()],
        )
        summary_start = markup.find('dash-alerts__summary')
        summary_end = markup.find('</summary>', summary_start)
        summary = _decode_entities(markup[summary_start:summary_end])
        # 2 → "слабые темы"
        assert '2' in summary
        assert 'слабые темы' in summary

    def test_summary_shows_both_counts_with_separator(self):
        markup = _render_content(
            words_at_risk=[_risk_word()] * 5,
            grammar_weaknesses=[_weakness()] * 2,
        )
        summary_start = markup.find('dash-alerts__summary')
        summary_end = markup.find('</summary>', summary_start)
        summary = _decode_entities(markup[summary_start:summary_end])
        assert '5' in summary
        assert '2' in summary
        assert 'слов' in summary
        assert 'слабые темы' in summary
        # middle-dot separator must appear when both present
        assert '&middot;' in summary or '·' in summary

    def test_inner_list_markup_preserved(self):
        words = [_risk_word(word='apple', translation='яблоко', days_overdue=4)]
        weaknesses = [_weakness(title='Present Simple', attempts=10, accuracy=40)]
        markup = _render_content(
            words_at_risk=words,
            grammar_weaknesses=weaknesses,
        )
        # Existing inner markers preserved
        assert 'dash-risk__item' in markup
        assert 'dash-risk__badge' in markup
        assert 'dash-risk__action' in markup
        assert 'dash-weakness__item' in markup
        assert 'dash-weakness__bar' in markup
        assert 'dash-weakness__action' in markup
        assert 'apple' in markup
        assert 'Present Simple' in markup

    def test_accordion_is_collapsed_by_default(self):
        markup = _render_content(
            words_at_risk=[_risk_word()],
            grammar_weaknesses=[_weakness()],
        )
        # No `open` attribute means collapsed
        details_start = markup.find('<details class="dash-alerts__accordion"')
        assert details_start >= 0
        details_tag_end = markup.find('>', details_start)
        details_tag = markup[details_start:details_tag_end + 1]
        assert ' open' not in details_tag
