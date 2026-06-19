"""Stage 2 — single LessonCompletion renderer + JS i18n bridge.

Pins the additive stage-2 contract from docs/design/lesson-completion-contract.md:
the lesson-completion logic lives in one reusable module reading server-localized
labels from window.I18N; the inline showLessonCompletion is a thin shim; and the
plan-branch CTA labels in the partial are wrapped in _() (translatable).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.daily_plan.linear.lesson_context import DailyPlanLessonContext

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JS = (REPO_ROOT / 'app' / 'static' / 'js' / 'lesson-completion.js').read_text(encoding='utf-8')
BASE = (REPO_ROOT / 'app' / 'templates' / 'lesson_base_template.html').read_text(encoding='utf-8')
PARTIAL = (
    REPO_ROOT / 'app' / 'templates' / 'components' / '_lesson_completion_actions.html'
).read_text(encoding='utf-8')


class TestLessonCompletionModule:
    def test_exposes_show_on_window(self):
        assert 'window.LessonCompletion' in JS
        assert 'function show(' in JS

    def test_reads_labels_from_i18n_bridge(self):
        # External JS can't call _(), so labels come from window.I18N with a
        # Russian fallback (the leak the bridge fixes — see audit A3).
        assert 'window.I18N' in JS
        assert "_t('plan_next'" in JS
        assert "_t('dashboard'" in JS

    def test_updates_server_ctas_in_place(self):
        assert '[data-plan-cta="next-slot"]' in JS
        assert '[data-plan-cta="dashboard"]' in JS

    def test_preserves_day_secured_redirect_and_event(self):
        assert "'?day_secured=1'" in JS
        assert 'dailyPlanStepComplete' in JS

    def test_has_plan_and_standalone_modes(self):
        assert "_revealCompletion('standalone')" in JS
        assert "_revealCompletion('plan')" in JS


class TestShowLessonCompletionShim:
    def test_inline_helper_is_now_a_thin_shim(self):
        # The big implementation moved to lesson-completion.js.
        assert 'window.LessonCompletion.show(opts)' in BASE
        # Regression guard: the body must NOT be re-inlined in the base template.
        assert 'function _renderPlanCtas' not in BASE
        assert 'function _revealCompletion' not in BASE

    def test_base_loads_module_and_i18n_bridge(self):
        assert 'js/lesson-completion.js' in BASE
        assert "include 'components/_lesson_i18n.html'" in BASE


class TestPartialLabelsTranslatable:
    def test_plan_branch_labels_wrapped_in_gettext(self):
        # The plan branch used to render raw Russian (untranslatable); now _()-wrapped.
        assert "_('Следующий урок плана')" in PARTIAL
        assert "_('На дашборд')" in PARTIAL
        assert "_('День завершён · на дашборд')" in PARTIAL


class TestI18nBridgeRender:
    def _render(self, app, name, **ctx):
        with app.test_request_context():
            return app.jinja_env.get_template(name).render(**ctx)

    def test_bridge_exposes_completion_labels(self, app):
        html = self._render(app, 'components/_lesson_i18n.html')
        assert 'window.I18N' in html
        assert 'Object.assign' in html
        # Keys consumed by lesson-completion.js. Values are |tojson-escaped
        # (\\uXXXX) — value correctness is covered by the partial render test,
        # which uses the same _() calls without tojson.
        assert 'plan_next' in html
        assert 'dashboard' in html
        assert 'day_done' in html

    def test_partial_still_renders_localized_plan_ctas(self, app):
        ctx = DailyPlanLessonContext(
            is_daily_plan=True, slot_kind='curriculum',
            next_slot_url='/learn/2/?from=linear_plan', next_slot_title='X',
            next_slot_kind='curriculum', day_secured=False, dashboard_url='/dashboard',
        )
        html = self._render(
            app, 'components/_lesson_completion_actions.html',
            daily_plan_ctx=ctx, lesson=None,
        )
        assert 'data-plan-cta="next-slot"' in html
        assert 'data-plan-cta="dashboard"' in html
        # Wrapping in _() must not change the rendered (Russian) copy.
        assert 'Следующий урок плана' in html
        assert 'На дашборд' in html
