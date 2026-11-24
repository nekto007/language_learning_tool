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

    def test_completed_day_has_a_plan_exit(self):
        # The actual SRS result stays visible until the learner follows the link.
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

    def test_helper_updates_server_ctas_in_place(self):
        # The helper REUSES the server-rendered [data-plan-cta] anchors (emitted
        # by the _lesson_completion_actions partial on both the card-lesson and
        # /study/cards SRS surfaces) and refreshes the next-slot href IN PLACE —
        # it must NOT delete + rebuild. The old rebuild dropped the partial's
        # .lsn-btn styling, re-created unstyled btn-plan-* anchors, and clobbered
        # the identical in-place update flashcard-session.js already performs
        # from the inline complete-response ctx.
        assert '[data-plan-cta="next-slot"]' in JS_SRC
        assert '[data-plan-cta="dashboard"]' in JS_SRC
        # The synthesise-when-absent fallback uses the shared .lsn-btn styling
        # (never the undefined btn-plan-* classes).
        assert 'lsn-btn--plan-equal' in JS_SRC


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
        assert '"source": "linear_plan"' in html
        assert '"from": "linear_plan"' in html
        assert '"slot": "srs"' in html

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

    def test_study_index_redirects_linear_plan_srs_to_cards(
        self, authenticated_client,
    ):
        # Old SRS baseline-slot URLs pointed at /study/ (deck index). Keep
        # those links working, but send the user straight into the card
        # session and preserve plan context for the completion screen.
        response = authenticated_client.get(
            '/study/?source=linear_plan&from=linear_plan&slot=srs'
        )
        assert response.status_code == 302
        assert response.location.endswith(
            '/study/cards?source=linear_plan&from=linear_plan&slot=srs'
        )


def test_web_round_counts_repeated_answers_and_both_directions(
    authenticated_client, test_user, test_word, db_session,
) -> None:
    from app.study.models import PLAN_SRS_SESSION_TYPE, StudySession

    entry = authenticated_client.get('/study/cards?source=linear_plan&from=linear_plan&slot=srs')
    assert entry.status_code == 200 and b'planSrs: true' in entry.data
    run = db_session.query(StudySession).filter_by(user_id=test_user.id, session_type=PLAN_SRS_SESSION_TYPE).one()
    for direction, rating in [('eng-rus', 1), ('rus-eng', 2), ('eng-rus', 3)]:
        result = authenticated_client.post('/study/api/update-study-item', json={
            'session_id': run.id, 'direction': direction, 'quality': rating, 'word_id': test_word.id,
        })
        assert result.status_code == 200 and result.json['success']

    result = authenticated_client.post('/study/api/complete-session', json={'session_id': run.id})
    stats = result.json['stats']
    assert stats['words_studied'] == 3 and stats['correct'] == 2 and stats['percentage'] == 67
    assert stats['ratings'] == {'words': 1, 'unknown': 1, 'hesitant': 1, 'known': 1}
    db_session.refresh(run)
    finished_at = run.end_time
    late = authenticated_client.post('/study/api/update-study-item', json={
        'session_id': run.id, 'direction': 'eng-rus', 'quality': 1, 'word_id': test_word.id,
    })
    assert late.status_code == 409 and late.json['error'] == 'session_completed'
    replay = authenticated_client.post('/study/api/complete-session', json={'session_id': run.id})
    assert replay.json['stats'] == stats
    db_session.refresh(run)
    assert run.end_time == finished_at


def test_completed_step_selects_only_latest_finished_plan_round_today(test_user, second_user, db_session) -> None:
    from datetime import timedelta

    from app.daily_plan.items.srs import add_last_session_result
    from app.study.models import PLAN_SRS_SESSION_TYPE, StudySession
    from app.utils.db import db
    from app.utils.time_utils import get_user_local_day_bounds

    start, end = get_user_local_day_bounds(test_user.id, db)
    def round_(user_id: int, session_type: str, minutes: int | None, remembered: int, total: int) -> StudySession:
        return StudySession(user_id=user_id, session_type=session_type,
                            start_time=start - timedelta(hours=1),
                            end_time=start + timedelta(minutes=minutes) if minutes is not None else None,
                            words_studied=total, correct_answers=remembered, incorrect_answers=total - remembered)

    # A different activity, an empty run or an unsubmitted round must not hide the result.
    db_session.add_all([
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, -1, 0, 8),
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, 0, 1, 3),
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, 1, 3, 4),
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, 2, 0, 0),
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, None, 0, 6),
        round_(test_user.id, PLAN_SRS_SESSION_TYPE, int((end - start).total_seconds() / 60), 1, 5),
        round_(test_user.id, 'cards', 3, 9, 9),
        round_(second_user.id, PLAN_SRS_SESSION_TYPE, 4, 7, 7),
    ])
    db_session.flush()
    items = [dict(id=kind, completed=done, subtitle='план')
             for kind, done in [('srs:global', True), ('srs:global', False), ('srs:deck_quiz', True)]]
    add_last_session_result(test_user.id, items, db)
    assert [item['subtitle'] for item in items] == ['Последнее повторение · вспомнил 3 из 4', 'план', 'план']
