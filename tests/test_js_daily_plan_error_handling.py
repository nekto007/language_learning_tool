"""Tests for JS error handling in the daily-plan surfaces (Task 50).

Originally this file also covered ``daily-plan-next.js`` — the banner + modal
that fetched the next plan step. Audit UI-031 (cross-zone audit 2026-08-08)
established that the file was unreachable: it self-activated only on
``?from=daily_plan``, the plan builds slot URLs with ``?from=linear_plan``, and
the one route that does emit ``from=daily_plan`` (``/learn/phrase-review/``,
``app/daily_plan/items/phrase_review.py:207``) renders a template that never
loaded the script. It was deleted along with its four containers and six
orphaned ``dailyPlanStepComplete`` dispatchers, so the checks against its source
went with it.

What remains here is the part that never lived in that file: the skip-reason
loading state in ``partials/unified_daily_plan.html``.
"""
import os

import pytest

pytestmark = pytest.mark.smoke

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')
_PLAN_PARTIAL = os.path.join(_TEMPLATES_DIR, 'partials', 'unified_daily_plan.html')
_JS_DIR = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'js')


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


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


class TestDeadBannerStaysDeleted:
    """UI-031 — reintroducing the file without fixing the gate rebuilds dead weight."""

    def test_script_file_is_gone(self):
        assert not os.path.exists(os.path.join(_JS_DIR, 'daily-plan-next.js'))

    def test_no_template_loads_it(self):
        hits = []
        for root, _dirs, files in os.walk(_TEMPLATES_DIR):
            for name in files:
                if not name.endswith('.html'):
                    continue
                path = os.path.join(root, name)
                if 'daily-plan-next' in _read(path):
                    hits.append(path)
        assert hits == []

    def test_no_orphaned_event_dispatchers_remain(self):
        """The event had exactly one listener; it lived in the deleted file."""
        hits = []
        for root, _dirs, files in os.walk(_JS_DIR):
            for name in files:
                if name.endswith('.js') and 'dailyPlanStepComplete' in _read(os.path.join(root, name)):
                    hits.append(name)
        assert hits == []
