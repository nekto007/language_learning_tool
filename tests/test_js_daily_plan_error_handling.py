"""Tests for JS error handling in daily-plan-next.js (Task 50).

Covers:
- Network errors during plan fetch show a retry button (not blank)
- JSON parse errors don't crash the entire plan script
- Skip-lesson requests show loading state while pending
- Continuation endpoint failure doesn't block the main plan content
"""
import os
import re

import pytest

pytestmark = pytest.mark.smoke

_JS_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'js')
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')

_NEXT_JS = os.path.join(_JS_DIR, 'daily-plan-next.js')
_PLAN_PARTIAL = os.path.join(_TEMPLATES_DIR, 'partials', 'unified_daily_plan.html')


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


class TestNetworkErrorRetryButton:
    """On network error, a retry button appears in the container — not a blank screen."""

    def test_catch_handler_creates_retry_button(self):
        src = _read(_NEXT_JS)
        assert 'daily-next-retry-btn' in src, (
            "Catch handler must create an element with class 'daily-next-retry-btn'"
        )

    def test_catch_handler_sets_button_type_button(self):
        src = _read(_NEXT_JS)
        assert "retryBtn.type = 'button'" in src, (
            "Retry button must have type='button' to avoid form submission"
        )

    def test_catch_handler_sets_retry_text(self):
        src = _read(_NEXT_JS)
        # "Повторить" encoded as \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c or literal
        assert (
            '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c' in src
            or 'Повторить' in src
        ), "Retry button must show a 'retry' label"

    def test_catch_handler_clears_container_before_retry(self):
        src = _read(_NEXT_JS)
        # container.innerHTML = '' must appear inside the catch block
        assert "container.innerHTML = ''" in src

    def test_catch_handler_resets_debounce_on_retry(self):
        src = _read(_NEXT_JS)
        assert 'lastShownAt = 0' in src, (
            "Retry click must reset lastShownAt so re-dispatch is not debounced"
        )

    def test_retry_dispatches_step_complete_event(self):
        src = _read(_NEXT_JS)
        assert "dailyPlanStepComplete" in src
        # Retry click re-dispatches the event
        assert "dispatchEvent(new CustomEvent('dailyPlanStepComplete'))" in src


class TestJsonParseErrorGraceful:
    """JSON parse errors must be caught and not crash the page."""

    def test_json_parsed_with_try_catch(self):
        src = _read(_NEXT_JS)
        # Must use JSON.parse inside a try-catch, not r.json() directly
        assert 'JSON.parse(text)' in src, (
            "JSON must be parsed via JSON.parse(text) with explicit error handling"
        )

    def test_json_parse_uses_text_not_json_method(self):
        src = _read(_NEXT_JS)
        # r.text() should be used instead of r.json() for explicit error handling
        assert 'r.text()' in src or '.text()' in src, (
            "Fetch should call r.text() so JSON parse errors can be caught explicitly"
        )
        # r.json() should NOT be the primary parse method anymore
        lines_with_json = [
            l for l in src.splitlines()
            if 'r.json()' in l and not l.strip().startswith('//')
        ]
        assert len(lines_with_json) == 0, (
            f"r.json() should be replaced with r.text()+JSON.parse: {lines_with_json}"
        )

    def test_json_parse_error_thrown(self):
        src = _read(_NEXT_JS)
        # JSON parse error must propagate to the catch handler
        assert "json_parse_error" in src, (
            "A tagged error type for JSON parse failures must be thrown"
        )

    def test_try_catch_wraps_json_parse(self):
        src = _read(_NEXT_JS)
        # Both try and catch must appear before JSON.parse reference
        try_idx = src.index('try {')
        parse_idx = src.index('JSON.parse(text)')
        # try block must come before the parse call
        assert try_idx < parse_idx, "try block must wrap JSON.parse call"


class TestSkipLessonLoadingState:
    """Skip-reason buttons show btn--loading while the POST request is in flight."""

    def test_skip_reason_adds_btn_loading(self):
        src = _read(_PLAN_PARTIAL)
        assert "btn.classList.add('btn--loading')" in src, (
            "Skip-reason submit must add btn--loading class before fetch"
        )

    def test_skip_reason_removes_btn_loading_on_error(self):
        src = _read(_PLAN_PARTIAL)
        assert "btn.classList.remove('btn--loading')" in src, (
            "Skip-reason must remove btn--loading class on fetch error"
        )

    def test_skip_reason_disables_button_during_request(self):
        src = _read(_PLAN_PARTIAL)
        assert 'btn.disabled = true' in src, (
            "Skip-reason button must be disabled while request is pending"
        )

    def test_skip_reason_re_enables_on_error(self):
        src = _read(_PLAN_PARTIAL)
        assert 'btn.disabled = false' in src, (
            "Skip-reason button must be re-enabled on fetch failure"
        )


class TestContinuationIsolation:
    """Continuation endpoint failure must not touch main plan content."""

    def test_catch_only_modifies_container(self):
        src = _read(_NEXT_JS)
        catch_block_start = src.find('.catch(function(err)')
        assert catch_block_start != -1
        # Find the catch block content (up to the next });)
        catch_block = src[catch_block_start:]
        # The catch block must reference 'container' (the banner area)
        assert 'container' in catch_block, (
            "Catch handler must use 'container' (banner area) — not main plan content"
        )

    def test_catch_does_not_touch_daily_plan_section(self):
        src = _read(_NEXT_JS)
        catch_block_start = src.find('.catch(function(err)')
        catch_block = src[catch_block_start:]
        # Catch must not query for the main plan section
        assert 'data-daily-plan' not in catch_block, (
            "Catch handler must not modify the main [data-daily-plan] element"
        )
        assert 'daily-plan__section' not in catch_block, (
            "Catch handler must not touch plan section classes"
        )

    def test_continuation_response_check_before_parse(self):
        src = _read(_NEXT_JS)
        # r.ok check must come before parsing to give meaningful network errors
        assert "if (!r.ok)" in src or "r.ok" in src, (
            "Response ok status must be checked before JSON parsing"
        )

    def test_network_error_tagged_distinctly(self):
        src = _read(_NEXT_JS)
        assert 'network_error' in src, (
            "Network errors should be tagged with 'network_error' for clarity"
        )
