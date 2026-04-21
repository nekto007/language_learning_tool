"""Task 7: SRS session completion in plan context.

``/study/cards?source=linear_plan&from=linear_plan&slot=srs`` is the URL
rendered by the linear daily plan's SRS slot. When the flashcard session
wraps up, the celebration screen should offer "Следующий слот плана · <X>"
and "На дашборд" instead of the stock "К колодам" / "Ещё карточки" CTAs.

The DOM swap is performed client-side by
``linearPlanContext.applySrsPlanAwareCompletion`` (declared in
``app/static/js/linear-plan-context.js``) and wired into the celebration
screen by a small inline script in ``components/_flashcard_session.html``.
These tests pin the expected hooks so a rename of the helper or a missing
script tag breaks immediately.
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
JS_SRC = (REPO_ROOT / 'app' / 'static' / 'js' / 'linear-plan-context.js').read_text(
    encoding='utf-8'
)
TEMPLATE_SRC = (
    REPO_ROOT / 'app' / 'templates' / 'components' / '_flashcard_session.html'
).read_text(encoding='utf-8')


class TestLinearPlanContextSrsHelper:
    """Exposes ``applySrsPlanAwareCompletion`` on the global context."""

    def test_helper_function_is_defined(self):
        assert 'function applySrsPlanAwareCompletion' in JS_SRC

    def test_helper_exposed_on_window_context(self):
        # Must be reachable via ``window.linearPlanContext.applySrsPlanAwareCompletion``
        # so the flashcard-session template can call it without importing.
        assert 'applySrsPlanAwareCompletion: applySrsPlanAwareCompletion' in JS_SRC

    def test_helper_gated_on_flashcard_slot_kinds(self):
        # The flashcard celebration renders for both SRS and curriculum
        # card lessons, so the swap must trigger for both. Other kinds
        # (book/error-review) have their own helpers.
        assert "slotKind !== 'srs' && slotKind !== 'curriculum'" in JS_SRC

    def test_helper_uses_next_slot_endpoint(self):
        # Re-uses the same fetchNextSlot as the lesson-completion helper —
        # keeps both flows in lock-step with the server.
        assert 'fetchNextSlot()' in JS_SRC

    def test_helper_redirects_on_day_secured(self):
        # When the SRS slot was the final baseline, hand off to the
        # dashboard's "День сохранён" banner instead of showing CTAs.
        assert "'/dashboard?day_secured=1'" in JS_SRC

    def test_helper_renders_plan_ctas(self):
        # Primary + secondary CTA copy pinned (Russian is deliberate — any
        # rename has to update translations in one place).
        assert 'Следующий слот плана' in JS_SRC
        assert 'На дашборд' in JS_SRC
        # data-plan-cta markers are the hook tests (and the helper itself on
        # re-entry) use to find dynamically-injected CTAs.
        assert "setAttribute('data-plan-cta', 'next-slot')" in JS_SRC
        assert "setAttribute('data-plan-cta', 'dashboard')" in JS_SRC

    def test_helper_hides_legacy_cta_buttons(self):
        # The legacy "Ещё карточки" link must be hidden in plan mode.
        assert "#session-extra-study-link" in JS_SRC
        # And the stock continue button (#fc-continue-btn) is hidden so it
        # doesn't render alongside the plan CTAs.
        assert "#fc-continue-btn" in JS_SRC


class TestFlashcardSessionTemplateWiring:
    """Inline script in _flashcard_session.html bootstraps the helper."""

    def test_linear_plan_context_script_is_loaded(self):
        # The flashcard session is reused outside lesson_base_template (which
        # already loads the context). The partial itself must pull the
        # script in.
        assert "js/linear-plan-context.js" in TEMPLATE_SRC

    def test_celebration_actions_carry_hook_attribute(self):
        # The helper selects the CTA container via
        # ``[data-celebration-actions]`` — without this attribute the plan
        # branch would not find an insertion point.
        assert 'data-celebration-actions' in TEMPLATE_SRC

    def test_celebration_actions_default_to_standalone_mode(self):
        # Mirrors the lesson-completion hook: starts in standalone and gets
        # flipped to "plan" only when the helper succeeds.
        assert 'data-completion-mode="standalone"' in TEMPLATE_SRC

    def test_bootstrap_script_invokes_helper(self):
        # The inline script must wait for the celebration screen to become
        # visible and then call ``applySrsPlanAwareCompletion``. The symbol
        # name is the contract — a rename breaks this test.
        assert 'applySrsPlanAwareCompletion' in TEMPLATE_SRC
        # Gating: runs for SRS global review AND curriculum card lessons
        # (both render through the shared _flashcard_session.html partial).
        assert "slotKind !== 'srs' && slotKind !== 'curriculum'" in TEMPLATE_SRC

    def test_bootstrap_script_uses_mutation_observer(self):
        # ``_showCelebration`` sets ``display: 'flex'`` on ``#session-complete``
        # — the script observes the style attribute to trigger on reveal.
        assert 'MutationObserver' in TEMPLATE_SRC
        assert "attributeFilter: ['style', 'class']" in TEMPLATE_SRC


class TestStudyCardsRouteStillRenders:
    """Sanity: the SRS entry URL still works with plan-context query params.

    A stray Python error on the route would defeat the whole Task 7 story —
    pin it.
    """

    def test_study_cards_accepts_linear_plan_source(
        self, authenticated_client, study_settings,
    ):
        response = authenticated_client.get(
            '/study/cards?source=linear_plan&from=linear_plan&slot=srs'
        )
        assert response.status_code == 200
        html = response.data.decode()
        # The plan-aware helper + inline bootstrap must land in the HTML —
        # otherwise the celebration screen falls back to the standalone
        # "К колодам" CTA even under the plan context.
        assert 'linear-plan-context.js' in html
        assert 'data-celebration-actions' in html

    def test_study_cards_without_plan_params_still_standalone(
        self, authenticated_client, study_settings,
    ):
        response = authenticated_client.get('/study/cards')
        assert response.status_code == 200
        html = response.data.decode()
        # The script is always loaded (gating happens client-side); both
        # plan-context hooks must exist for the JS to run no-op when
        # context is absent.
        assert 'linear-plan-context.js' in html
        assert 'data-celebration-actions' in html

    def test_study_index_includes_linear_plan_context(
        self, authenticated_client,
    ):
        # The SRS baseline-slot URL points at /study/ (deck index), not
        # /study/cards. Without linear-plan-context.js on the index page,
        # the ``?from=linear_plan&slot=srs`` query-param never reaches
        # sessionStorage, so the subsequent click into a deck loses plan
        # context and the completion screen falls back to "К колодам".
        response = authenticated_client.get(
            '/study/?from=linear_plan&slot=srs'
        )
        assert response.status_code == 200
        assert b'linear-plan-context.js' in response.data
