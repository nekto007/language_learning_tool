"""Daily-plan completion-flow contract tests (Stage 0 + Stage 1.2).

Pins the as-is contract the unified completion flow depends on, so the staged
migration in docs/design/lesson-completion-contract.md stays verifiable:

  * Stage 0 — the ``daily_plan_ctx`` DTO shape (the single source of truth for
    "what's next"); that ``submit_lesson`` returns it; that
    ``_lesson_completion_actions.html`` renders the plan-CTA pair from it; and
    the CURRENT (nested) shape of ``/api/daily-plan/next-slot`` — pinned so a
    later stage flattens it deliberately, not by accident.
  * Stage 1.2 — curriculum lesson pages no longer load ``daily-plan-next.js``
    (it self-activates only on ``?from=daily_plan``, which lessons never carry).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.lesson_context import DailyPlanLessonContext
from tests.conftest import unique_level_code

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Every completion delivery channel (inline submit response, page-load context
# processor, /api/daily-plan/next-slot) must converge on this DTO shape — see
# docs/design/lesson-completion-contract.md §2.1.
DTO_KEYS = {
    'is_daily_plan',
    'slot_kind',
    'next_slot_url',
    'next_slot_title',
    'next_slot_kind',
    'day_secured',
    'dashboard_url',
}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _make_collocation_lesson(db_session):
    pairs = [
        {'phrase': 'make a decision', 'translation': 'принять решение'},
        {'phrase': 'break the rules', 'translation': 'нарушать правила'},
        {'phrase': 'take a risk', 'translation': 'идти на риск'},
    ]
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id, number=1, title='Collocation',
        type='collocation_matching', content={'pairs': pairs},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson, pairs


def _make_vocabulary_lesson(db_session):
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id, number=1, title='Vocab', type='vocabulary',
        content={'words': [{'english': 'hello', 'russian': 'привет'}]},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# Stage 0 — the DTO spine
# ---------------------------------------------------------------------------
class TestDailyPlanCtxDtoShape:
    def test_to_dict_has_exactly_the_contract_keys(self):
        ctx = DailyPlanLessonContext(
            is_daily_plan=True,
            slot_kind='srs',
            next_slot_url='/study/cards?from=linear_plan&slot=srs',
            next_slot_title='Карточки',
            next_slot_kind='srs',
            day_secured=False,
            dashboard_url='/dashboard',
        )
        d = ctx.to_dict()
        assert set(d.keys()) == DTO_KEYS
        assert isinstance(d['is_daily_plan'], bool)
        assert isinstance(d['day_secured'], bool)
        assert isinstance(d['dashboard_url'], str)
        for key in ('slot_kind', 'next_slot_url', 'next_slot_title', 'next_slot_kind'):
            assert d[key] is None or isinstance(d[key], str)


class TestSubmitLessonReturnsDailyPlanCtx:
    """submit_lesson must ALWAYS attach daily_plan_ctx (the inline channel)."""

    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_collocation_submit_response_carries_dto(
        self, _mock_lesson, _mock_module, app, db_session, client, test_user,
    ):
        lesson, pairs = _make_collocation_lesson(db_session)
        _login(client, test_user)
        # GET first to create the LessonProgress row the submit path expects.
        client.get(f'/curriculum/lesson/{lesson.id}/collocation-matching')
        resp = client.post(
            f'/curriculum/api/lesson/{lesson.id}/submit',
            json={'user_pairs': pairs},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'daily_plan_ctx' in data, 'submit response must carry the inline DTO'
        assert set(data['daily_plan_ctx'].keys()) == DTO_KEYS


class TestNextSlotUnifiedShape:
    """Stage 3.1 — /api/daily-plan/next-slot now returns the flat completion DTO
    (same shape as the inline submit channel) PLUS a back-compat nested ``next``
    (dropped in stage 4)."""

    def test_next_slot_returns_flat_dto_and_legacy_next(self, authenticated_client):
        resp = authenticated_client.get('/api/daily-plan/next-slot')
        assert resp.status_code == 200
        data = resp.get_json()
        # Flat DTO fields (the unified contract).
        assert 'next_slot_url' in data
        assert 'next_slot_kind' in data
        assert 'dashboard_url' in data
        assert 'is_daily_plan' in data
        assert 'day_secured' in data
        # Back-compat nested envelope + transport flag.
        assert 'next' in data
        assert 'success' in data


class TestUpdateProgressReturnsDailyPlanCtx:
    """Stage 3.2 — the non-graded completion endpoint (used by text/vocabulary/
    matching/grammar-theory) now also carries the inline DTO, so those call-sites
    can render plan CTAs without a fetchNextSlot round-trip (audit A4)."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_progress_endpoint_carries_dto(
        self, _mock_access, db_session, authenticated_client,
    ):
        # vocabulary is not server-graded so it completes via the progress
        # endpoint; the patch satisfies @require_lesson_access.
        lesson = _make_vocabulary_lesson(db_session)
        resp = authenticated_client.post(
            f'/curriculum/api/lesson/{lesson.id}/progress',
            json={'status': 'completed', 'score': 100},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'daily_plan_ctx' in data
        assert set(data['daily_plan_ctx'].keys()) == DTO_KEYS


class TestCurriculumForwardsDailyPlanCtx:
    """A4: the live completion handlers forward the inline daily_plan_ctx from
    the submit response into showLessonCompletion (no redundant fetchNextSlot)."""

    @pytest.mark.parametrize('tpl,token', [
        ('translation.html', 'daily_plan_ctx: data.daily_plan_ctx'),
        ('audio_fill_blank.html', 'daily_plan_ctx: data.daily_plan_ctx'),
        ('shadow_reading.html', 'daily_plan_ctx: data.daily_plan_ctx'),
        ('text.html', 'daily_plan_ctx: responseData.daily_plan_ctx'),
        # pronunciation now routes through showLessonCompletion instead of a
        # bespoke next-lesson anchor (Stage 3.3).
        ('pronunciation.html', 'daily_plan_ctx: data.daily_plan_ctx'),
    ])
    def test_template_forwards_ctx(self, tpl, token):
        src = (
            REPO_ROOT / 'app' / 'templates' / 'curriculum' / 'lessons' / tpl
        ).read_text(encoding='utf-8')
        assert 'showLessonCompletion' in src
        assert token in src


class TestErrorReviewCtaStyling:
    """Stage 3.4 / audit A13 — the error_review plan CTAs use error_review's own
    btn classes (btn--primary / btn--outline); the dead btn-plan-* classes (and
    the unstyled btn--secondary dashboard CTA) are gone from the shared JS."""

    def _js(self):
        return (
            REPO_ROOT / 'app' / 'static' / 'js' / 'linear-plan-context.js'
        ).read_text(encoding='utf-8')

    def test_no_dead_btn_plan_classes(self):
        js = self._js()
        assert 'btn-plan-next' not in js
        assert 'btn-plan-dashboard' not in js

    def test_error_review_uses_page_native_btn_classes(self):
        js = self._js()
        assert "'btn btn--primary'" in js
        assert "'btn btn--outline'" in js


class TestLessonCompletionPartialRendersPlanCtas:
    """_lesson_completion_actions.html is the single server-side CTA renderer."""

    def _render(self, app, ctx):
        tpl = app.jinja_env.get_template('components/_lesson_completion_actions.html')
        with app.test_request_context():
            return tpl.render(daily_plan_ctx=ctx, lesson=None)

    def test_plan_branch_renders_both_ctas_from_dto(self, app):
        ctx = DailyPlanLessonContext(
            is_daily_plan=True,
            slot_kind='curriculum',
            next_slot_url='/study/cards?from=linear_plan&slot=srs',
            next_slot_title='Карточки',
            next_slot_kind='srs',
            day_secured=False,
            dashboard_url='/dashboard',
        )
        html = self._render(app, ctx)
        assert 'data-plan-cta="dashboard"' in html
        assert 'data-plan-cta="next-slot"' in html
        # NB: Jinja escapes ``&`` → ``&amp;``, so assert on the unescaped prefix.
        assert '/study/cards?from=linear_plan' in html

    def test_plan_branch_drops_next_slot_when_absent_and_marks_day_secured(self, app):
        ctx = DailyPlanLessonContext(
            is_daily_plan=True,
            slot_kind='curriculum',
            next_slot_url=None,
            next_slot_title=None,
            next_slot_kind=None,
            day_secured=True,
            dashboard_url='/dashboard',
        )
        html = self._render(app, ctx)
        assert 'data-plan-cta="dashboard"' in html
        # No next slot left → only the dashboard CTA renders.
        assert 'data-plan-cta="next-slot"' not in html
        # day_secured threads the banner query param onto the dashboard href.
        assert 'day_secured=1' in html


# ---------------------------------------------------------------------------
# Stage 1.2 — daily-plan-next.js is gated OFF curriculum lessons
# ---------------------------------------------------------------------------
class TestDailyPlanNextScriptGatedOffLessons:
    @patch('app.curriculum.security.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    def test_lesson_page_does_not_load_daily_plan_next_js(
        self, _mock_lesson, _mock_module, db_session, authenticated_client,
    ):
        lesson = _make_vocabulary_lesson(db_session)
        resp = authenticated_client.get(f'/learn/{lesson.id}/')
        assert resp.status_code == 200
        html = resp.data.decode()
        # The dead-weight legacy banner/modal script must not ship on lessons.
        assert 'daily-plan-next.js' not in html
        # Sanity: the page still rendered its real completion machinery.
        assert 'showLessonCompletion' in html

    def test_reader_template_still_includes_daily_plan_next_js(self):
        # The book reader is the ONLY surface that emits ?from=daily_plan, so it
        # keeps the script (included directly, not via lesson_base).
        src = (REPO_ROOT / 'app' / 'templates' / 'books' / 'reader_simple.html').read_text(
            encoding='utf-8'
        )
        assert 'daily-plan-next.js' in src
