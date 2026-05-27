"""Mobile responsiveness audit tests (Task 48).

Verifies that design-system.css contains the necessary CSS patterns for
mobile layout at 375px (iPhone SE) and that key templates have correct
viewport and responsive patterns.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_CSS_PATH = (
    Path(__file__).resolve().parents[2]
    / 'app' / 'static' / 'css' / 'design-system.css'
)
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / 'app' / 'templates'
_BASE_TPL = _TEMPLATES_DIR / 'base.html'
_COLLOCATION_TPL = (
    _TEMPLATES_DIR / 'curriculum' / 'lessons' / 'collocation_matching.html'
)


@pytest.fixture(scope='module')
def css() -> str:
    return _CSS_PATH.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def base_tpl() -> str:
    return _BASE_TPL.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def collocation_tpl() -> str:
    return _COLLOCATION_TPL.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# Viewport meta tag
# ---------------------------------------------------------------------------

def test_viewport_meta_present(base_tpl: str) -> None:
    assert 'width=device-width, initial-scale=1' in base_tpl, (
        'base.html must have viewport meta tag for mobile scaling'
    )


# ---------------------------------------------------------------------------
# Mobile breakpoints in CSS
# ---------------------------------------------------------------------------

def test_lesson_shell_mobile_breakpoint(css: str) -> None:
    """Lesson shell must have a mobile media query (≤640px)."""
    assert '@media (max-width: 640px)' in css, (
        'design-system.css must define a ≤640px breakpoint for .lesson-shell'
    )
    # Find the 640px breakpoint that contains .lesson-shell (may not be the first one)
    found = False
    start = 0
    while True:
        idx640 = css.find('@media (max-width: 640px)', start)
        if idx640 == -1:
            break
        snippet = css[idx640:idx640 + 500]
        if '.lesson-shell' in snippet:
            found = True
            break
        start = idx640 + 1
    assert found, (
        'A ≤640px breakpoint containing .lesson-shell rules must exist in design-system.css'
    )


def test_lesson_shell_overflow_mobile(css: str) -> None:
    """Lesson shell must have overflow-x:hidden at narrow viewports."""
    # Either inline in the 640px block or in a separate mobile block
    assert 'overflow-x: hidden' in css or 'overflow-x:hidden' in css, (
        '.lesson-shell needs overflow-x:hidden to prevent horizontal scroll on mobile'
    )


def test_small_screen_375_breakpoint_exists(css: str) -> None:
    """CSS must include at least one 375px or narrower-specific rule."""
    pattern = re.compile(r'@media\s*\([^)]*max-width:\s*(375|360|320)px')
    assert pattern.search(css), (
        'design-system.css should have ≤375px breakpoint rules for iPhone SE'
    )


def test_modal_responsive_width(css: str) -> None:
    """linear-modal__panel must use min() for responsive width."""
    assert 'width: min(640px, 100%)' in css or 'width:min(640px,100%)' in css, (
        'linear-modal__panel must use min(640px, 100%) for mobile responsiveness'
    )


def test_feedback_modal_responsive(css: str) -> None:
    """feedback-modal must shift FAB position on mobile."""
    assert 'feedback-fab' in css
    # The FAB must have a mobile override (moved up to clear nav)
    assert 'bottom: 5.5rem' in css or 'bottom:5.5rem' in css, (
        'feedback-fab must move up on mobile to clear bottom navigation'
    )


# ---------------------------------------------------------------------------
# Touch-action on interactive audio elements
# ---------------------------------------------------------------------------

def test_audio_play_btn_touch_action(css: str) -> None:
    """audio-play-btn must have touch-action:manipulation to prevent tap delay."""
    idx = css.index('.audio-play-btn {')
    block_end = css.index('}', idx)
    block = css[idx:block_end]
    assert 'touch-action: manipulation' in block, (
        '.audio-play-btn must have touch-action:manipulation for mobile double-tap prevention'
    )


def test_audio_speed_btn_touch_action(css: str) -> None:
    """audio-speed-btn must have touch-action:manipulation."""
    idx = css.index('.audio-speed-btn {')
    block_end = css.index('}', idx)
    block = css[idx:block_end]
    assert 'touch-action: manipulation' in block, (
        '.audio-speed-btn must have touch-action:manipulation for mobile double-tap prevention'
    )


# ---------------------------------------------------------------------------
# Collocation matching — touch support
# ---------------------------------------------------------------------------

def test_collocation_matching_single_column_breakpoint(collocation_tpl: str) -> None:
    """Collocation matching must switch to single column on mobile."""
    assert 'grid-template-columns: 1fr' in collocation_tpl, (
        'collocation_matching.html must use single-column layout on mobile'
    )
    assert 'max-width: 600px' in collocation_tpl or 'max-width:600px' in collocation_tpl, (
        'collocation_matching.html must have a ≤600px media query for single-column layout'
    )


def test_collocation_speak_btn_touch_action(collocation_tpl: str) -> None:
    """.cm-speak-btn in collocation_matching must have touch-action:manipulation."""
    assert 'touch-action: manipulation' in collocation_tpl, (
        '.cm-speak-btn in collocation_matching.html must have touch-action:manipulation'
    )


def test_collocation_uses_click_not_drag(collocation_tpl: str) -> None:
    """Collocation matching uses click handlers (touch-compatible), not drag API."""
    assert 'ondragstart' not in collocation_tpl, (
        'collocation_matching.html must not use native drag API (not touch-compatible); '
        'use click/tap handlers instead'
    )
    assert 'selectPhrase' in collocation_tpl or 'onclick' in collocation_tpl, (
        'collocation_matching.html must use click-based selection for touch compatibility'
    )


# ---------------------------------------------------------------------------
# Dashboard rank band — min-width fix for 375px
# ---------------------------------------------------------------------------

def test_dashboard_rank_band_min_width_reset(css: str) -> None:
    """On mobile, dash-rank__progress--band must allow shrinking below 240px."""
    # The min-width:240px exists for desktop; a mobile override must set min-width:0
    assert 'min-width: 240px' in css, 'desktop min-width:240px must be present'
    # Mobile override must reset it
    mobile_section = css[css.rfind('@media (max-width: 480px)'):]
    assert 'dash-rank' in mobile_section, (
        'A ≤480px media query must reset .dash-rank__progress--band constraints'
    )
