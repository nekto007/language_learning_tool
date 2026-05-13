"""Assert that the modern lesson UI tokens exist in design-system.css.

Task 2 of the lesson UI redesign adds a shared `.lesson-shell` shell plus
shared feedback / input / option-button / chip primitives. The templates
redesigned in Tasks 3-5 depend on these class names; this test pins the
contract so a CSS cleanup cannot silently strip them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_CSS_PATH = (
    Path(__file__).resolve().parents[2]
    / 'app'
    / 'static'
    / 'css'
    / 'design-system.css'
)


@pytest.fixture(scope='module')
def css_source() -> str:
    return _CSS_PATH.read_text(encoding='utf-8')


REQUIRED_SELECTORS = [
    # Lesson shell skeleton
    '.lesson-shell',
    '.lesson-shell__header',
    '.lesson-shell__progress',
    '.lesson-shell__progress-bar',
    '.lesson-shell__progress-fill',
    '.lesson-shell__body',
    '.lesson-shell__actions',
    '.lesson-shell__card',
    '.lesson-shell__instruction',
    '.lesson-shell__result',
    # Result badge taxonomy
    '.result-badge',
    '.result-badge--correct',
    '.result-badge--incorrect',
    '.result-badge--neutral',
    # Input validation states
    '.input--correct',
    '.input--wrong',
    '.input--checking',
    # BEM option-button modifiers
    '.option-btn--selected',
    '.option-btn--correct',
    '.option-btn--wrong',
    # Hint chips
    '.chip',
    '.chip--clickable',
]


@pytest.mark.parametrize('selector', REQUIRED_SELECTORS)
def test_required_selector_present(css_source: str, selector: str) -> None:
    assert selector in css_source, (
        f'design-system.css is missing required selector "{selector}". '
        'Task 2 of the lesson UI redesign depends on it; do not remove '
        'without coordinating with docs/design/lesson-frontend-spec.md.'
    )


def test_reduced_motion_guard_still_present(css_source: str) -> None:
    """The global prefers-reduced-motion guard must remain.

    All new transitions added in Task 2 rely on this single global block
    (line ~8537) instead of defining their own no-preference wrappers.
    """
    assert '@media (prefers-reduced-motion: reduce)' in css_source
    assert 'transition-duration: 0.01ms !important' in css_source
