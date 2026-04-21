"""Task 9: Error-review session completion in plan context.

Entering ``/learn/error-review/`` via the linear-plan 4th baseline slot
(``?from=linear_plan&slot=error_review``) must surface plan-aware CTAs on
resolve instead of a blind redirect to ``/``: primary "Следующий слот
плана · <title>" and secondary "На дашборд". If the error-review slot is
the last incomplete baseline, the helper hands off to the dashboard
day-secured banner via ``/dashboard?day_secured=1``.

The DOM mutation lives in
``linearPlanContext.applyErrorReviewPlanAwareCompletion`` in
``app/static/js/linear-plan-context.js`` and is called by an inline
script in ``curriculum/error_review.html`` after a successful POST to
``/api/daily-plan/error-review/complete``.

These tests pin:
- the static JS / template hooks so renames break immediately,
- the template's wiring to the resolve API,
- the server-side contract (no regression on the completion endpoint,
  and the /api/daily-plan/next-slot endpoint correctly handles an
  ``error_review`` as the final baseline slot).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.daily_plan.models import DailyPlanLog


REPO_ROOT = Path(__file__).resolve().parent.parent
JS_SRC = (REPO_ROOT / 'app' / 'static' / 'js' / 'linear-plan-context.js').read_text(
    encoding='utf-8'
)
TEMPLATE_SRC = (
    REPO_ROOT / 'app' / 'templates' / 'curriculum' / 'error_review.html'
).read_text(encoding='utf-8')


# ── JS helper hooks ───────────────────────────────────────────────────


class TestLinearPlanContextErrorReviewHelper:
    """Exposes ``applyErrorReviewPlanAwareCompletion`` on the global context."""

    def test_helper_function_is_defined(self):
        assert 'function applyErrorReviewPlanAwareCompletion' in JS_SRC

    def test_helper_exposed_on_window_context(self):
        # Must be reachable as
        # ``window.linearPlanContext.applyErrorReviewPlanAwareCompletion`` so
        # the error-review template can call it without a module import.
        assert (
            'applyErrorReviewPlanAwareCompletion: applyErrorReviewPlanAwareCompletion'
            in JS_SRC
        )

    def test_helper_gated_on_error_review_slot_kind(self):
        # Only error-review contexts should run the swap — curriculum/SRS/
        # book flows have their own completion UX.
        assert "getSlotKind() !== 'error_review'" in JS_SRC

    def test_helper_uses_next_slot_endpoint(self):
        # Re-uses the shared fetchNextSlot as the other plan-aware helpers.
        assert 'fetchNextSlot()' in JS_SRC

    def test_helper_redirects_on_day_secured(self):
        # When error-review is the last baseline slot, hand off to the
        # dashboard's "День сохранён" banner.
        assert "'/dashboard?day_secured=1'" in JS_SRC

    def test_helper_renders_plan_ctas(self):
        # Russian copy pinned — rename has to update translations once.
        assert 'Следующий слот плана' in JS_SRC
        assert 'На дашборд' in JS_SRC
        # data-plan-cta markers are the hook tests (and the helper itself on
        # re-entry) use to find dynamically-injected CTAs.
        assert "setAttribute('data-plan-cta', 'next-slot')" in JS_SRC
        assert "setAttribute('data-plan-cta', 'dashboard')" in JS_SRC

    def test_helper_hides_legacy_resolve_button(self):
        # The original resolve button must be hidden in plan mode so it
        # doesn't coexist with the next-slot CTA.
        assert '#error-review-complete-btn' in JS_SRC


# ── Template wiring ───────────────────────────────────────────────────


class TestErrorReviewTemplateWiring:
    def test_linear_plan_context_script_is_loaded(self):
        # The error-review page does not extend lesson_base_template — the
        # template itself must pull the context script in.
        assert 'js/linear-plan-context.js' in TEMPLATE_SRC

    def test_container_carries_standalone_default(self):
        # Mirrors the lesson-completion hook: starts standalone, flipped to
        # "plan" only when the helper succeeds.
        assert 'data-completion-mode="standalone"' in TEMPLATE_SRC

    def test_helper_invoked_from_inline_script(self):
        # Symbol name is the contract — a rename breaks this test.
        assert 'applyErrorReviewPlanAwareCompletion' in TEMPLATE_SRC

    def test_resolve_button_and_status_present(self):
        # Stable ids the helper uses to hide the standalone UI.
        assert 'id="error-review-complete-btn"' in TEMPLATE_SRC
        assert 'id="error-review-status"' in TEMPLATE_SRC

    def test_complete_endpoint_still_posted(self):
        # Plan-aware flow still resolves the errors via the existing API —
        # CTA swap happens after the POST succeeds.
        assert '/api/daily-plan/error-review/complete' in TEMPLATE_SRC


# ── Route still renders ───────────────────────────────────────────────


class TestErrorReviewRouteStillRenders:
    """Sanity: the error-review entry URL works with plan-context query params."""

    def test_route_accepts_linear_plan_params(self, authenticated_client):
        # Plan-context query-params must not crash the route even for users
        # who have no errors to resolve — the page renders the empty-state
        # copy and still includes the context script.
        response = authenticated_client.get(
            '/learn/error-review/?from=linear_plan&slot=error_review'
        )
        assert response.status_code == 200


# ── End-to-end: next-slot endpoint with error-review as final baseline ──


def _plan_with_error_review(
    *,
    curriculum_done: bool,
    srs_done: bool,
    reading_done: bool,
    error_review_done: bool,
) -> dict:
    return {
        'mode': 'linear',
        'position': None,
        'progress': {'level': 'B1', 'percent': 20, 'lessons_remaining_in_level': 60},
        'baseline_slots': [
            {
                'kind': 'curriculum',
                'title': 'B1 · M5 · L3 (card)',
                'lesson_type': 'card',
                'eta_minutes': 8,
                'url': '/learn/101/?source=linear_plan_card&from=linear_plan&slot=curriculum',
                'completed': curriculum_done,
                'data': {},
            },
            {
                'kind': 'srs',
                'title': 'Карточки на повторение',
                'lesson_type': None,
                'eta_minutes': 5,
                'url': '/study?source=linear_plan&from=linear_plan&slot=srs',
                'completed': srs_done,
                'data': {},
            },
            {
                'kind': 'reading',
                'title': 'The Great Gatsby',
                'lesson_type': None,
                'eta_minutes': 10,
                'url': '/read/7?from=linear_plan&slot=book',
                'completed': reading_done,
                'data': {},
            },
            {
                'kind': 'error_review',
                'title': 'Разбор ошибок (5)',
                'lesson_type': None,
                'eta_minutes': 6,
                'url': '/learn/error-review/?from=linear_plan&slot=error_review',
                'completed': error_review_done,
                'data': {'unresolved_count': 5, 'pool_size': 5},
            },
        ],
        'continuation': {'available': False, 'next_lessons': []},
        'day_secured': False,
    }


def _all_done_summary() -> dict:
    return {
        'lessons_count': 1,
        'lesson_types': [],
        'words_reviewed': 5,
        'srs_words_reviewed': 5,
        'srs_new_reviewed': 0,
        'srs_review_reviewed': 5,
        'grammar_exercises': 0,
        'grammar_correct': 0,
        'books_read': ['Book A'],
        'book_course_lessons_today': 0,
    }


@pytest.fixture
def linear_user(db_session, test_user):
    test_user.use_linear_plan = True
    db_session.commit()
    return test_user


class TestErrorReviewClosesDay:
    """When error-review is the last incomplete slot, next-slot secures the day."""

    def test_error_review_as_fourth_slot_triggers_day_secured(
        self, authenticated_client, linear_user, db_session,
    ):
        # Error-review is the 4th baseline slot; the prior three are done
        # and the error-review itself has just been resolved. The next-slot
        # endpoint should now see every baseline completed and flip
        # day_secured=True / secured_just_now=True.
        plan = _plan_with_error_review(
            curriculum_done=True,
            srs_done=True,
            reading_done=True,
            error_review_done=True,
        )
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_all_done_summary(),
        ):
            response = authenticated_client.get(
                '/api/daily-plan/next-slot?current=error_review'
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['next'] is None
        assert data['day_secured'] is True
        assert data['secured_just_now'] is True

        log = DailyPlanLog.query.filter_by(user_id=linear_user.id).first()
        assert log is not None
        assert log.secured_at is not None

    def test_error_review_incomplete_picks_itself_as_next(
        self, authenticated_client, linear_user,
    ):
        # If the user just finished SRS or reading, next-slot should point
        # at the outstanding error-review slot.
        plan = _plan_with_error_review(
            curriculum_done=True,
            srs_done=True,
            reading_done=True,
            error_review_done=False,
        )
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_all_done_summary(),
        ):
            response = authenticated_client.get(
                '/api/daily-plan/next-slot?current=book'
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['next'] is not None
        assert data['next']['kind'] == 'error_review'
        assert data['next']['url'].startswith('/learn/error-review/')
        assert data['day_secured'] is False


class TestErrorReviewCompleteEndpoint:
    """No regression: the existing resolve API still returns 200 + JSON."""

    def test_endpoint_returns_success_for_empty_payload(
        self, authenticated_client, linear_user,
    ):
        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': []},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['resolved_count'] == 0
