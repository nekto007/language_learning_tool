"""Tests for dashboard zero-state = fullscreen welcome card (Task 4).

Zero-state (no words, grammar, books, or course enrollments) collapses the
dashboard to a single welcome card. Non-zero users never see the welcome card.
"""
import os

from jinja2 import ChainableUndefined, Environment, FileSystemLoader


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)


def _read_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


class TestZeroStateTemplateMarkers:
    """Static markers ensuring the zero-state guard is wired up correctly."""

    def test_template_has_is_zero_state_guard(self):
        html = _read_template()
        assert '{% if is_zero_state %}' in html

    def test_template_has_fullscreen_welcome_variant(self):
        html = _read_template()
        assert 'dash-welcome--fullscreen' in html

    def test_template_has_fullscreen_welcome_css(self):
        html = _read_template()
        assert '.dash-welcome--fullscreen' in html

    def test_welcome_card_only_rendered_inside_zero_state_guard(self):
        """The legacy always-on welcome block was removed; the only welcome
        markup lives inside the ``is_zero_state`` branch."""
        html = _read_template()
        # The fullscreen welcome is the only remaining `dash-welcome"` (sans
        # modifier) markup. The legacy `<div class="dash-welcome">` guarded by
        # per-counter checks has been deleted.
        assert 'class="dash-welcome"' not in html
        assert 'dash-welcome dash-welcome--fullscreen' in html


class TestZeroStateRendering:
    """Render dashboard template with a minimal context to verify branching."""

    def _build_env(self) -> Environment:
        tpl_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
        env = Environment(
            loader=FileSystemLoader(tpl_dir),
            autoescape=True,
            undefined=ChainableUndefined,
        )

        # Stub url_for so templates render without a Flask request context.
        def _url_for(endpoint, **values):
            return f'/stub/{endpoint}'

        env.globals['url_for'] = _url_for
        env.globals['current_user'] = _StubUser()
        env.globals['csrf_token'] = lambda: 'stub-csrf'
        env.globals['config'] = {}
        return env

    def _base_ctx(self) -> dict:
        """Minimal context with everything truthy-ish disabled so rendering
        skips unrelated branches and errors out loudly on missing data only if
        reached."""
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
            'words_total': 0,
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
            'session_stats': None,
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
            'route_progress_state': None,
            'yesterday_summary': None,
            'yesterday': None,
        }

    def test_zero_state_renders_only_welcome(self):
        env = self._build_env()
        # Render the body block only to avoid pulling base.html dependencies.
        tpl_source = _read_template()
        # Extract just the content block inner HTML for rendering.
        block_html = _extract_content_block(tpl_source)
        tpl = env.from_string(block_html)
        ctx = self._base_ctx()
        ctx['is_zero_state'] = True
        full = tpl.render(**ctx)
        markup = _strip_inline_style(full)
        assert 'dash-welcome--fullscreen' in markup
        assert 'data-zero-state="true"' in markup
        # No hero, no plan, no sections in the rendered markup
        assert 'dash-hero' not in markup
        assert 'dash-plan' not in markup
        assert 'dash-race' not in markup

    def test_non_zero_state_branch_contains_hero_and_no_welcome(self):
        """Structural check: the ``{% else %}`` branch renders the hero and no
        welcome markup. A live render here would require stubbing every
        widget section, so we slice the template between the guard tokens.
        """
        tpl_source = _read_template()
        else_branch = _extract_else_branch(tpl_source)
        assert 'dash-hero' in else_branch
        # Welcome card lives only in the ``is_zero_state`` branch above.
        assert 'dash-welcome' not in else_branch


class _StubUser:
    id = 1
    username = 'stub'
    is_authenticated = True
    onboarding_completed = True
    referral_code = 'refcode'
    birth_year = 2000


def _strip_inline_style(rendered: str) -> str:
    """Return rendered output with ``<style>...</style>`` blocks removed.

    The dashboard template embeds its stylesheet inside the content block, so
    class-name assertions against a full render would match CSS selectors
    rather than live markup. Stripping style tags keeps assertions focused on
    the DOM tree that actually reaches the browser during zero-state.
    """
    out = rendered
    while '<style>' in out and '</style>' in out:
        start = out.index('<style>')
        end = out.index('</style>', start) + len('</style>')
        out = out[:start] + out[end:]
    return out


def _extract_else_branch(template_source: str) -> str:
    """Return the markup between ``{% else %}`` and the matching
    ``{% endif %}`` of the outer ``is_zero_state`` guard, correctly skipping
    nested ``{% if %}/{% else %}/{% endif %}`` pairs."""
    guard_open = '{% if is_zero_state %}'
    cursor = template_source.index(guard_open) + len(guard_open)
    depth = 1  # we're inside the guard

    else_idx = None
    while cursor < len(template_source):
        next_if = template_source.find('{% if', cursor)
        next_else = template_source.find('{% else %}', cursor)
        next_endif = template_source.find('{% endif', cursor)
        candidates = [(i, kind) for i, kind in [
            (next_if, 'if'), (next_else, 'else'), (next_endif, 'endif')
        ] if i != -1]
        if not candidates:
            raise AssertionError('Unterminated is_zero_state guard')
        candidates.sort()
        pos, kind = candidates[0]
        if kind == 'if':
            depth += 1
            cursor = pos + len('{% if')
        elif kind == 'else':
            if depth == 1:
                else_idx = pos + len('{% else %}')
                cursor = else_idx
                break
            cursor = pos + len('{% else %}')
        else:  # endif
            depth -= 1
            cursor = pos + len('{% endif')
            if depth == 0:
                raise AssertionError('is_zero_state guard has no {% else %} branch')

    assert else_idx is not None

    # Now walk from else_idx to the matching {% endif %} (depth 1 at this
    # point, since we consumed the outer-if but not its endif).
    depth = 1
    cursor = else_idx
    while cursor < len(template_source):
        next_if = template_source.find('{% if', cursor)
        next_endif = template_source.find('{% endif', cursor)
        candidates = [(i, kind) for i, kind in [
            (next_if, 'if'), (next_endif, 'endif')
        ] if i != -1]
        if not candidates:
            raise AssertionError('Unterminated else branch of is_zero_state')
        candidates.sort()
        pos, kind = candidates[0]
        if kind == 'if':
            depth += 1
            cursor = pos + len('{% if')
        else:
            depth -= 1
            if depth == 0:
                return template_source[else_idx:pos]
            cursor = pos + len('{% endif')

    raise AssertionError('Walked off end of template extracting else branch')


def _extract_content_block(template_source: str) -> str:
    """Return just the inside of ``{% block content %} ... {% endblock %}``.

    Rendering the whole template would require ``base.html`` and every child
    tag it references. Extracting the block lets us exercise the zero-state
    guard without a full request lifecycle.
    """
    start_tag = '{% block content %}'
    end_tag = '{% endblock %}'
    start_idx = template_source.index(start_tag) + len(start_tag)
    end_idx = template_source.index(end_tag, start_idx)
    return template_source[start_idx:end_idx]
