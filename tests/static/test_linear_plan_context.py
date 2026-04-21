"""Tests for ``app/static/js/linear-plan-context.js`` (Task 3).

The runtime behaviour of the helper is exercised in the browser (manual
QA + higher-level plan-aware completion tests in Task 4+). Here we pin
down two invariants that the plan depends on:

1. The script is physically included by ``lesson_base_template.html``
   before the ``showLessonCompletion`` helper, so ``window.linearPlanContext``
   is guaranteed to exist at completion time.
2. The helper file exposes the documented public API surface
   (``init``/``isActive``/``getSlotKind``/``clear``) and references the
   known slot kinds + query-param source, so Task 4's completion code can
   call it safely.

Both are string-level asserts against the template source and the raw JS
file — no browser automation required.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_STATIC_JS_DIR = Path(__file__).resolve().parents[2] / 'app' / 'static' / 'js'
_SCRIPT_PATH = _STATIC_JS_DIR / 'linear-plan-context.js'


def _read_script() -> str:
    return _SCRIPT_PATH.read_text(encoding='utf-8')


class TestScriptIncludedInLessonBaseTemplate:
    def test_script_file_exists(self):
        assert _SCRIPT_PATH.exists(), (
            f'linear-plan-context.js must live at {_SCRIPT_PATH}'
        )

    def test_script_referenced_in_base_template(self, app):
        env = app.jinja_env
        source = env.loader.get_source(env, 'lesson_base_template.html')[0]
        assert 'js/linear-plan-context.js' in source

    def test_script_loads_before_showLessonCompletion(self, app):
        """The context helper must be parsed before the inline helper that
        may call ``window.linearPlanContext.isActive()`` in Task 4."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'lesson_base_template.html')[0]
        idx_script = source.find('js/linear-plan-context.js')
        idx_helper = source.find('window.showLessonCompletion')
        assert idx_script != -1
        assert idx_helper != -1
        assert idx_script < idx_helper, (
            'linear-plan-context.js must be included BEFORE the inline '
            'showLessonCompletion helper so the context API is available '
            'when the helper dispatches dailyPlanStepComplete.'
        )


class TestPublicApiSurface:
    """Keep the JS public surface stable — Task 4+ code relies on it."""

    def test_exposes_linearPlanContext_global(self):
        src = _read_script()
        assert 'window.linearPlanContext' in src

    @pytest.mark.parametrize('method', ['init', 'isActive', 'getSlotKind', 'clear'])
    def test_exports_documented_method(self, method):
        src = _read_script()
        # Method appears both as a local function declaration and on the
        # exported object literal (``method: method``).
        assert 'function ' + method in src, f'missing function {method}'
        assert method + ': ' + method in src, (
            f'{method} must be exposed on window.linearPlanContext'
        )

    def test_all_four_slot_kinds_referenced(self):
        src = _read_script()
        for slot in ('curriculum', 'srs', 'book', 'error_review'):
            assert "'" + slot + "'" in src, f'slot kind {slot!r} missing from script'

    def test_references_linear_plan_query_source(self):
        src = _read_script()
        assert "'linear_plan'" in src, (
            'Script must read the ?from=linear_plan marker'
        )

    def test_sessionStorage_used_with_try_catch(self):
        """Private mode / disabled storage must not crash the lesson page."""
        src = _read_script()
        assert 'sessionStorage' in src
        # Presence of both try and catch around storage access.
        assert 'try {' in src
        assert 'catch' in src

    def test_auto_init_on_load(self):
        """The helper should auto-initialise so the completion flow can
        check ``isActive()`` without an explicit bootstrap step."""
        src = _read_script()
        assert 'init();' in src

    def test_clear_on_dashboard_navigation(self):
        src = _read_script()
        # Explicit dashboard auto-clear binding so context dies when the
        # user goes back to /dashboard.
        assert '/dashboard' in src
        assert '_bindDashboardAutoClear' in src or 'bindDashboardAutoClear' in src


class TestScriptIsIife:
    """The script must not leak locals to the global scope."""

    def test_wrapped_in_iife(self):
        src = _read_script()
        # Tolerate either `(function() {` or `(function () {` etc.
        assert src.lstrip().startswith('/**') or src.lstrip().startswith('(function')
        assert '}());' in src or '})();' in src

    def test_uses_strict_mode(self):
        src = _read_script()
        assert "'use strict';" in src
