"""Task 8: Book reading slot completion in plan context.

Entering the reader via ``/read/<book_id>?from=linear_plan&slot=book`` must
surface a floating toast when the user crosses the reading threshold:
``Слот чтения выполнен`` with a CTA to the next baseline slot in plan.

The server side flips the ``linear_book_reading`` XP event from the
``/api/progress`` PATCH endpoint — the response now carries a
``reading_slot_completed`` flag. The client-side DOM mutation lives in
``linearPlanContext.applyBookReadingPlanAwareToast`` in
``app/static/js/linear-plan-context.js`` and is called from
``books/reader_simple.html`` after a successful progress save.

These tests pin:
- the static JS / template hooks so renames are caught immediately,
- the API contract (new field + correct gating),
- the reader template includes the context script and wires the helper.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE
from app.utils.db import db as real_db


REPO_ROOT = Path(__file__).resolve().parent.parent
JS_SRC = (REPO_ROOT / 'app' / 'static' / 'js' / 'linear-plan-context.js').read_text(
    encoding='utf-8'
)
READER_TEMPLATE_SRC = (
    REPO_ROOT / 'app' / 'templates' / 'books' / 'reader_simple.html'
).read_text(encoding='utf-8')


def _make_linear_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'bookread_{suffix}',
        email=f'bookread_{suffix}@example.com',
        active=True,
        onboarding_completed=True,
        use_linear_plan=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(user_id=user.id, total_xp=0, current_streak_days=0))
    db_session.commit()
    return user


def _make_book_with_chapter(db_session) -> tuple[Book, Chapter]:
    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Book {suffix}',
        author='Test Author',
        level='A2',
        chapters_cnt=2,
    )
    db_session.add(book)
    db_session.commit()
    chapter = Chapter(
        book_id=book.id,
        chap_num=1,
        title='Chapter 1',
        words=120,
        text_raw='text...',
    )
    db_session.add(chapter)
    db_session.commit()
    return book, chapter


def _set_preference(db_session, user: User, book: Book) -> UserReadingPreference:
    pref = UserReadingPreference(
        user_id=user.id,
        book_id=book.id,
        selected_at=datetime.now(timezone.utc),
    )
    db_session.add(pref)
    db_session.commit()
    return pref


class TestLinearPlanContextBookToastHelper:
    """Exposes ``applyBookReadingPlanAwareToast`` on the global context."""

    def test_helper_function_is_defined(self):
        assert 'function applyBookReadingPlanAwareToast' in JS_SRC

    def test_helper_exposed_on_window_context(self):
        # Must be reachable as ``window.linearPlanContext
        # .applyBookReadingPlanAwareToast`` so reader_simple.html can
        # invoke it without a module import.
        assert (
            'applyBookReadingPlanAwareToast: applyBookReadingPlanAwareToast'
            in JS_SRC
        )

    def test_helper_gated_on_book_slot_kind(self):
        # Only book contexts should render the toast — curriculum/SRS/
        # error-review flows have their own completion UX.
        assert "getSlotKind() !== 'book'" in JS_SRC

    def test_helper_uses_next_slot_endpoint(self):
        # Re-uses the same fetchNextSlot as the other plan-aware helpers.
        assert 'fetchNextSlot()' in JS_SRC

    def test_helper_redirects_on_day_secured(self):
        # When the book slot is the last baseline, hand off to the
        # dashboard day-secured banner.
        assert "'/dashboard?day_secured=1'" in JS_SRC

    def test_helper_renders_plan_ctas(self):
        # Russian copy is deliberate — rename must update translations in
        # one place.
        assert 'Слот чтения выполнен' in JS_SRC
        assert 'Продолжить план' in JS_SRC
        # data-plan-cta markers are the hook tests and the helper itself
        # (for idempotence checks) use to find injected CTAs.
        assert "setAttribute('data-plan-cta', 'next-slot')" in JS_SRC

    def test_helper_renders_toast_container_with_stable_id(self):
        # Idempotence hinges on this id — a rename would re-render on
        # every saveProgress call.
        assert "'linear-plan-book-toast'" in JS_SRC
        assert "document.getElementById('linear-plan-book-toast')" in JS_SRC

    def test_helper_auto_hides_after_timeout(self):
        # 5s matches the spec: the user can keep reading while the toast
        # gracefully disappears; the slot stays completed server-side.
        assert 'setTimeout(' in JS_SRC
        assert '5000' in JS_SRC


class TestReaderTemplateWiring:
    """Inline reader script bootstraps the helper."""

    def test_linear_plan_context_script_is_loaded(self):
        assert 'js/linear-plan-context.js' in READER_TEMPLATE_SRC

    def test_save_progress_invokes_helper_on_slot_completion(self):
        # Guard key + helper name pinned together so a refactor touches
        # both at once.
        assert 'reading_slot_completed' in READER_TEMPLATE_SRC
        assert 'applyBookReadingPlanAwareToast' in READER_TEMPLATE_SRC

    def test_toast_styles_present(self):
        # Template-scoped CSS classes used by the helper.
        assert '.linear-plan-book-toast' in READER_TEMPLATE_SRC
        assert '.linear-plan-book-toast__cta' in READER_TEMPLATE_SRC


class TestReadBookRedirectPreservesPlanContext:
    """`/read/<book_id>` redirects to the chapter-based reader. The redirect
    must forward query params so ``?from=linear_plan&slot=book`` survives and
    the plan-aware toast can activate.
    """

    def test_redirect_preserves_linear_plan_query_params(
        self, authenticated_client, db_session,
    ):
        from unittest.mock import patch

        book, _chapter = _make_book_with_chapter(db_session)
        with patch(
            'app.modules.decorators.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{book.id}?from=linear_plan&slot=book',
                follow_redirects=False,
            )
        assert response.status_code in (301, 302)
        location = response.headers.get('Location', '')
        assert 'from=linear_plan' in location
        assert 'slot=book' in location


class TestProgressEndpointSlotCompletion:
    """/api/progress PATCH now surfaces the linear reading-slot flag."""

    def test_threshold_crossing_returns_slot_completed_flag(
        self, authenticated_client, db_session, test_user,
    ):
        # Activate the linear plan flag + wire a reading preference so the
        # server-side award gate fires.
        test_user.use_linear_plan = True
        test_user.onboarding_completed = True
        db_session.add(test_user)
        db_session.commit()
        book, chapter = _make_book_with_chapter(db_session)
        _set_preference(db_session, test_user, book)

        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.5,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload['reading_slot_completed'] is True

        # A StreakEvent row backing the slot completion must now exist.
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
        ).all()
        sources = {e.details.get('source') for e in events if e.details}
        assert 'linear_book_reading' in sources

    def test_below_threshold_returns_false(
        self, authenticated_client, db_session, test_user,
    ):
        """An offset delta smaller than the threshold must not complete."""
        test_user.use_linear_plan = True
        db_session.add(test_user)
        db_session.commit()
        book, chapter = _make_book_with_chapter(db_session)
        _set_preference(db_session, test_user, book)

        # First save seeds a baseline offset just under the threshold.
        authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.04,
            },
        )

        # Second save advances by <1% — far below the threshold delta.
        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.045,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload.get('reading_slot_completed') is False

    def test_non_linear_user_skips_award(
        self, authenticated_client, db_session, test_user,
    ):
        """Users without ``use_linear_plan`` get ``reading_slot_completed=False``."""
        test_user.use_linear_plan = False
        db_session.add(test_user)
        db_session.commit()
        book, chapter = _make_book_with_chapter(db_session)
        _set_preference(db_session, test_user, book)

        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.6,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload.get('reading_slot_completed') is False

        # No linear_book_reading StreakEvent was written.
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
        ).all()
        sources = {e.details.get('source') for e in events if e.details}
        assert 'linear_book_reading' not in sources

    def test_repeat_save_is_idempotent(
        self, authenticated_client, db_session, test_user,
    ):
        """Subsequent saves the same day must return ``False``.

        The slot is already marked complete — the client should not show
        a second toast, and XP must not double-credit.
        """
        test_user.use_linear_plan = True
        db_session.add(test_user)
        db_session.commit()
        book, chapter = _make_book_with_chapter(db_session)
        _set_preference(db_session, test_user, book)

        first = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.5,
            },
        )
        assert first.get_json()['reading_slot_completed'] is True

        second = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.7,
            },
        )
        assert second.status_code == 200
        assert second.get_json().get('reading_slot_completed') is False

        # XP event count stays at 1.
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
        ).all()
        reading_events = [
            e for e in events if e.details and e.details.get('source') == 'linear_book_reading'
        ]
        assert len(reading_events) == 1

    def test_no_preference_skips_award(
        self, authenticated_client, db_session, test_user,
    ):
        """Linear user without a ``UserReadingPreference`` must not complete the slot
        — progress in an arbitrary book does not count toward the slot.
        """
        test_user.use_linear_plan = True
        db_session.add(test_user)
        db_session.commit()
        book, chapter = _make_book_with_chapter(db_session)
        # Deliberately skip _set_preference

        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': book.id,
                'chapter_id': chapter.id,
                'offset_pct': 0.6,
            },
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload.get('reading_slot_completed') is False
