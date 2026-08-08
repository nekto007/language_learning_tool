"""Regression tests for UI-003 / UI-007 (cross-zone audit 2026-08-08).

UI-003 — the completion ``fetch`` in five book-course lesson templates ended in
``.catch(e => { console.error(e); showCompletionUI(); })``: a 404/401/500 painted
the very same "✓ Модуль завершён!" screen as success, while nothing had been
written to ``UserLessonProgress`` / ``BookModuleProgress``.

UI-007 — multiple-choice options and matching items were bare ``<div onclick>``.
Tab skipped every one of them and landed on a ``#next-btn`` that stays disabled
until an answer is chosen, so a keyboard-only learner could not proceed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

LESSON_DIR = (
    Path(__file__).resolve().parents[2]
    / 'app' / 'templates' / 'curriculum' / 'book_courses' / 'lessons'
)
DESIGN_SYSTEM = (
    Path(__file__).resolve().parents[2] / 'app' / 'static' / 'css' / 'design-system.css'
)

COMPLETION_TEMPLATES = [
    'final_test.html',
    'context_review.html',
    'comprehension_check.html',
    'retelling.html',
    'phrase_cloze.html',
]

KEYBOARD_TEMPLATES = [
    'comprehension_check.html',
    'match_headings.html',
    'context_review.html',
]


def _source(name: str) -> str:
    return (LESSON_DIR / name).read_text(encoding='utf-8')


class TestFailedSaveIsNotReportedAsSuccess:
    @pytest.mark.parametrize('template', COMPLETION_TEMPLATES)
    def test_catch_branch_no_longer_calls_show_completion_ui(self, template):
        source = _source(template)
        # Anchor on the completion request, not on any other fetch in the file.
        completion = source[source.index('function completeLessonAPI('):]
        catch_start = completion.index('.catch(e =>')
        catch_block = completion[catch_start:catch_start + 200]

        assert 'showCompletionUI' not in catch_block, (
            f'{template}: a failed POST still paints the success screen'
        )
        assert 'showSaveError' in catch_block

    @pytest.mark.parametrize('template', COMPLETION_TEMPLATES)
    def test_error_ui_offers_a_retry(self, template):
        source = _source(template)

        assert 'function showSaveError(retry)' in source
        assert "button.textContent = isRu ? 'Повторить' : 'Retry';" in source
        assert 'lesson-save-error' in source

    @pytest.mark.parametrize('template', COMPLETION_TEMPLATES)
    def test_error_ui_uses_dom_api_not_innerhtml(self, template):
        """The message is built with textContent — no HTML injection surface."""
        source = _source(template)
        block = source[source.index('function showSaveError(retry)'):]
        block = block[:block.index('\nfunction ')]

        assert 'innerHTML' not in block
        assert 'note.textContent' in block

    def test_error_style_exists(self):
        assert '.lesson-save-error' in DESIGN_SYSTEM.read_text(encoding='utf-8')


# The two guard shapes that actually activate on Enter and Space. Asserting
# `=== 'Enter'` OR `!== 'Enter'` (as this file used to) is satisfied by a
# handler that explicitly ignores both keys — the regression it exists to catch.
ENTER_SPACE_GUARDS = (
    "e.key === 'Enter' || e.key === ' '",
    "e.key !== 'Enter' && e.key !== ' '",
)


class TestKeyboardReachability:
    @pytest.mark.parametrize('template', KEYBOARD_TEMPLATES)
    def test_interactive_divs_expose_role_and_tabindex(self, template):
        import re

        source = _source(template)
        # Both attributes on the SAME element: an unrelated `tabindex` elsewhere
        # in the file says nothing about the clickable divs.
        focusable = re.findall(
            r'<div[^>]*\brole="button"[^>]*\btabindex=|<div[^>]*\btabindex=[^>]*\brole="button"',
            source,
        )

        assert focusable, f'{template}: clickable divs are not both labelled and focusable'

    @pytest.mark.parametrize('template', KEYBOARD_TEMPLATES)
    def test_enter_and_space_activate(self, template):
        source = _source(template)

        assert "addEventListener('keydown'" in source
        matches = [g for g in ENTER_SPACE_GUARDS if g in source]
        assert matches, f'{template}: no keydown guard activates on both Enter and Space'
        # The guard has to lead somewhere — swallowing the key is not activation.
        for guard in matches:
            after = source[source.index(guard):source.index(guard) + 400]
            assert 'preventDefault()' in after, (
                f'{template}: Enter/Space guard never activates the control'
            )

    def test_comprehension_check_locks_after_answering(self):
        source = _source('comprehension_check.html')
        body = source[source.index('function selectOption(optIndex)'):]
        body = body[:body.index('\nfunction ')]

        assert 'if (answers[currentQ] !== undefined) return;' in body
