"""Tests for Task 17 of the compact dashboard redesign: mobile responsiveness audit.

These are file-level CSS assertions that verify the required media-query
rules exist in dashboard.html for the restructured components. Actual
visual regression is manually QA'd — we can only guard against the
rules being accidentally removed or drifting.

Scope:
- Hero greeting + streak stacking on <= 400px
- Mission XP widget stacks level / progress / multiplier on <= 640px
- Social 3-col grid collapses to 1 col on <= 768px
- Race strip wraps cleanly on <= 420px
- Activity streak one-liner / yesterday summary wrap on <= 400px
- Roadmap horizontal scroll on <= 640px and 641-1024px ranges
"""
import os


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'app', 'templates', 'dashboard.html'
)


def _read_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def _inline_style_block(tpl: str) -> str:
    """Return the concatenated text of all <style> blocks in dashboard.html."""
    pieces = []
    pos = 0
    while True:
        start = tpl.find('<style>', pos)
        if start < 0:
            break
        end = tpl.find('</style>', start)
        if end < 0:
            break
        pieces.append(tpl[start + len('<style>'):end])
        pos = end + len('</style>')
    return '\n'.join(pieces)


def _media_block(css: str, media_prefix: str) -> str:
    """Return the concatenated body of ALL `@media (...)` rules matching the prefix.

    Several disjoint `@media (max-width: 640px) { ... }` blocks can exist across
    the stylesheet (hero, heatmap, roadmap, etc.); returning only the first would
    miss rules for unrelated components. We union them and assert membership per
    test.
    """
    results = []
    pos = 0
    while True:
        idx = css.find(media_prefix, pos)
        if idx < 0:
            break
        brace_open = css.find('{', idx)
        if brace_open < 0:
            break
        depth = 1
        i = brace_open + 1
        while i < len(css) and depth > 0:
            c = css[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            i += 1
        results.append(css[brace_open + 1:i - 1])
        pos = i
    assert results, f'Missing media rule: {media_prefix}'
    return '\n'.join(results)


def test_hero_stacks_on_narrow_phone():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 400px)')
    assert '.dash-hero__greeting' in body
    assert 'flex-direction: column' in body
    assert '.dash-streak' in body
    assert '.dash-hero__cta' in body
    assert 'width: 100%' in body


def test_hero_streak_recovery_full_width_on_narrow_phone():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 400px)')
    assert '.dash-streak-recovery' in body


def test_mission_xp_widget_stacks_on_640px():
    css = _inline_style_block(_read_template())
    combined = _media_block(css, '@media (max-width: 640px)')
    assert '.dash-mission__xp .dash-xp' in combined
    assert 'flex-direction: column' in combined
    assert '.dash-xp__progress' in combined
    assert '.dash-xp__bar' in combined


def test_social_row_collapses_at_768px():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 768px)')
    assert '.dash-social-row' in body
    assert 'grid-template-columns: 1fr' in body


def test_race_strip_has_narrow_breakpoint():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 420px)')
    assert '.dash-race-strip' in body
    assert '.dash-race-strip__cta' in body
    # CTA becomes full-width block under very narrow screens.
    assert 'width: 100%' in body


def test_activity_streak_oneliner_wraps_at_400px():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 400px)')
    assert '.dash-heatmap__stat-line' in body
    assert 'word-break: break-word' in body


def test_yesterday_summary_scales_on_narrow_phone():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 400px)')
    assert '.dash-yesterday-summary' in body


def test_roadmap_has_horizontal_scroll_on_mobile():
    css = _inline_style_block(_read_template())
    body_640 = _media_block(css, '@media (max-width: 640px)')
    assert '.dash-roadmap__track' in body_640
    assert 'overflow-x: auto' in body_640
    assert 'scroll-snap-type: x mandatory' in body_640


def test_roadmap_has_horizontal_scroll_on_tablet():
    css = _inline_style_block(_read_template())
    body_tablet = _media_block(
        css, '@media (min-width: 641px) and (max-width: 1024px)'
    )
    assert '.dash-roadmap__track' in body_tablet
    assert 'overflow-x: auto' in body_tablet
    assert 'scroll-snap-type: x mandatory' in body_tablet


def test_roadmap_desktop_no_scroll():
    css = _inline_style_block(_read_template())
    body_desktop = _media_block(css, '@media (min-width: 1025px)')
    assert '.dash-roadmap__track' in body_desktop
    assert 'overflow: visible' in body_desktop


def test_roadmap_swipe_hint_hidden_on_desktop_only():
    """Swipe hint is shown on mobile + tablet, hidden on desktop."""
    css = _inline_style_block(_read_template())
    mobile = _media_block(css, '@media (max-width: 640px)')
    tablet = _media_block(
        css, '@media (min-width: 641px) and (max-width: 1024px)'
    )
    desktop = _media_block(css, '@media (min-width: 1025px)')
    assert '.dash-roadmap__swipe-hint' in mobile
    assert 'display: block' in mobile
    assert '.dash-roadmap__swipe-hint' in tablet
    assert '.dash-roadmap__swipe-hint' in desktop
    assert 'display: none' in desktop


def test_welcome_fullscreen_padding_shrinks_on_mobile():
    css = _inline_style_block(_read_template())
    body = _media_block(css, '@media (max-width: 640px)')
    assert '.dash-welcome--fullscreen' in body
    assert 'padding: 2rem 1.25rem' in body
