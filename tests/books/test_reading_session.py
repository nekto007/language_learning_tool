"""Tests for the reading-slot time gate (Task 11)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.models import StreakEvent
from app.books.reading_session import (
    MIN_READING_SECONDS,
    UserReadingSession,
    end_session,
    get_session_duration,
    has_min_reading_time_today,
    start_session,
)
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE
from app.utils.db import db


def _close_session_with_duration(session: UserReadingSession, seconds: int) -> None:
    """Backdate ``started_at`` so the session reads as ``seconds`` long."""
    now = datetime.now(timezone.utc)
    session.started_at = now - timedelta(seconds=seconds)
    session.ended_at = now


class TestSessionHelpers:
    def test_start_session_persists_open_row(self, app, db_session, test_user, test_chapter):
        session = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        assert session.id is not None
        assert session.ended_at is None
        assert session.duration_seconds() == 0

    def test_end_session_sets_ended_at(self, app, db_session, test_user, test_chapter):
        from app.books.models import UserChapterProgress

        session = start_session(test_user.id, test_chapter.id, db)
        # Simulate progress made during the session: server should compute
        # offset_delta from UserChapterProgress, ignoring any client value.
        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.1,
        ))
        db_session.commit()
        closed = end_session(session.id, db_session=db)
        db_session.commit()
        assert closed is not None
        assert closed.ended_at is not None
        assert closed.offset_delta == pytest.approx(0.1)

    def test_open_session_contributes_zero_duration(
        self, app, db_session, test_user, test_chapter,
    ):
        start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        assert get_session_duration(test_user.id, test_chapter.id, db) == 0

    def test_get_session_duration_sums_closed_only(
        self, app, db_session, test_user, test_chapter,
    ):
        s1 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s1, 30)
        s2 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s2, 45)
        # Open session: should not count.
        start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        total = get_session_duration(test_user.id, test_chapter.id, db)
        assert total == 75

    def test_end_session_returns_none_for_missing_id(self, app, db_session):
        assert end_session(999_999, db_session=db) is None


class TestHasMinReadingTime:
    def test_below_threshold_returns_false(self, app, db_session, test_user, test_chapter, test_book):
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 30)
        db_session.commit()
        assert has_min_reading_time_today(test_user.id, test_book.id, db) is False

    def test_meets_threshold_returns_true(self, app, db_session, test_user, test_chapter, test_book):
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS + 5)
        db_session.commit()
        assert has_min_reading_time_today(test_user.id, test_book.id, db) is True

    def test_open_session_does_not_count_toward_threshold(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        # 30s closed + open session — still below 60s minimum.
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 30)
        start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        assert has_min_reading_time_today(test_user.id, test_book.id, db) is False


class TestSaveReadingPositionTimeGate:
    """``/api/save-reading-position`` should NOT credit the linear book-reading
    slot when the user has not actually spent ``MIN_READING_SECONDS`` reading
    today, even if offset_pct crosses the threshold.
    """

    def _enable_linear_with_pref(self, db_session, user, book):
        user.use_linear_plan = True
        pref = UserReadingPreference(user_id=user.id, book_id=book.id)
        db_session.add(pref)
        db_session.commit()

    def test_no_session_no_linear_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        self._enable_linear_with_pref(db_session, test_user, test_book)
        r = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 0.5, 'chapter': test_chapter.chap_num},
        )
        assert r.status_code == 200
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        ).count()
        assert events == 0

    def test_below_threshold_no_linear_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        self._enable_linear_with_pref(db_session, test_user, test_book)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 30)
        db_session.commit()

        r = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 0.5, 'chapter': test_chapter.chap_num},
        )
        assert r.status_code == 200
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        ).count()
        assert events == 0

    def test_above_threshold_awards_linear_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        self._enable_linear_with_pref(db_session, test_user, test_book)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS + 10)
        s.offset_delta = 0.1
        db_session.commit()

        r = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 0.5, 'chapter': test_chapter.chap_num},
        )
        assert r.status_code == 200
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 1

    def test_qualifying_duration_but_low_session_offset_no_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Bypass guard: a 60s+ session whose own offset_delta is below 5%
        must NOT credit linear book-reading XP, even when subsequent
        progress saves push absolute offset_pct past the threshold.
        """
        self._enable_linear_with_pref(db_session, test_user, test_book)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS + 10)
        s.offset_delta = 0.001  # nudge: well below per-visit 5% gate
        db_session.commit()

        r = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 0.5, 'chapter': test_chapter.chap_num},
        )
        assert r.status_code == 200
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 0


class TestReadingSessionEndpoints:
    def test_start_then_end_returns_duration(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        r = authenticated_client.post(
            '/api/books/reading-session/start',
            json={'chapter_id': test_chapter.id},
        )
        assert r.status_code == 200
        sid = r.get_json()['session_id']

        # Backdate started_at so end_session yields a non-zero duration.
        session = db.session.get(UserReadingSession, sid)
        session.started_at = datetime.now(timezone.utc) - timedelta(seconds=90)
        db_session.commit()

        r2 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': sid},
        )
        assert r2.status_code == 200
        body = r2.get_json()
        assert body['session_id'] == sid
        assert body['duration_seconds'] >= 60

    def test_start_requires_chapter_id(self, authenticated_client):
        r = authenticated_client.post('/api/books/reading-session/start', json={})
        assert r.status_code == 400

    def test_end_requires_session_id(self, authenticated_client):
        r = authenticated_client.post('/api/books/reading-session/end', json={})
        assert r.status_code == 400

    def test_end_unknown_session_returns_404(self, authenticated_client):
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': 999_999},
        )
        assert r.status_code == 404

    def test_end_other_users_session_is_forbidden(
        self, authenticated_client, db_session, test_user, second_user, test_chapter,
    ):
        other = start_session(second_user.id, test_chapter.id, db)
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': other.id},
        )
        assert r.status_code == 403

    def test_end_session_short_visit_does_not_award_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """A short-but-scrolled session must NOT credit the linear reading
        slot. Server-computed offset_delta now snapshots offset_pct at
        session start, so a forged ``offset_delta`` payload cannot bypass
        the per-visit duration gate.
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        # Snapshot offset at start: 0.5 (already past the 5% threshold).
        progress = UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.5,
        )
        db_session.add(progress)
        db_session.commit()

        s_b = start_session(test_user.id, test_chapter.id, db)
        s_b.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        # Simulate the user scrolling further during the visit.
        progress.offset_pct = 0.7
        db_session.commit()

        # Client tries to forge a large offset_delta — server ignores it.
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_b.id, 'offset_delta': 0.2},
        )
        assert r.status_code == 200
        assert r.get_json()['reading_slot_completed'] is False
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 0

    def test_end_session_forged_delta_without_progress_no_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Bypass guard: a 60s+ session whose underlying chapter progress
        did NOT advance during the visit must not credit the slot, even if
        the client posts a large ``offset_delta``.
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.5,
        ))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 10)
        # No chapter-progress update between start and end → server-side
        # delta is 0 even if the client lies in the request body.
        db_session.commit()

        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'offset_delta': 0.2},
        )
        assert r.status_code == 200
        assert r.get_json()['reading_slot_completed'] is False
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 0

    def test_end_session_replay_does_not_widen_offset_delta(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """A closed session is locked: replaying /end with the same
        ``session_id`` after a later visit advanced ``UserChapterProgress``
        must NOT retroactively combine the old session's duration with the
        new session's progress to qualify for reading XP.
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        progress = UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        )
        db_session.add(progress)
        db_session.commit()

        # Visit A: 60s+, no scroll. Closes with offset_delta=0.
        s_a = start_session(test_user.id, test_chapter.id, db)
        s_a.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 30)
        db_session.commit()
        r1 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id},
        )
        assert r1.status_code == 200
        assert r1.get_json()['reading_slot_completed'] is False
        s_a_refetched = db.session.get(UserReadingSession, s_a.id)
        assert s_a_refetched.offset_delta == pytest.approx(0.0)

        # Later visit B: short, but progress advances past 5%.
        progress.offset_pct = 0.5
        db_session.commit()

        # Replay /end on session A — must be a no-op for offset_delta.
        r2 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id, 'current_offset_pct': 0.9},
        )
        assert r2.status_code == 200
        assert r2.get_json()['reading_slot_completed'] is False
        s_a_after = db.session.get(UserReadingSession, s_a.id)
        assert s_a_after.offset_delta == pytest.approx(0.0)
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 0

    def test_end_session_uses_client_offset_hint_when_progress_lags(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """The reader debounces progress saves by 3s, so on page-leave the
        persisted ``UserChapterProgress`` may lag the live scroll. The
        ``current_offset_pct`` hint lets the server credit a qualifying
        visit even when the latest progress save hasn't landed yet.
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        ))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 10)
        db_session.commit()

        # Persisted offset still 0.0 (debounce hasn't fired); client sends hint.
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 0.5},
        )
        assert r.status_code == 200
        s_after = db.session.get(UserReadingSession, s.id)
        assert s_after.offset_delta == pytest.approx(0.5)

    def test_end_session_awards_xp_when_persisted_offset_lags_hint(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """The reader debounces progress saves by 3s. When the user crosses
        5% just before page-leave, the persisted ``UserChapterProgress``
        row may still read 0 at the moment the session closes — the linear
        reading-slot award path must NOT additionally gate on the persisted
        absolute offset, because ``has_qualifying_reading_session_today``
        already enforces per-session ``offset_delta >= 0.05`` (using the
        client hint when persisted state lags).
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        ))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 10)
        db_session.commit()

        # Persisted offset is still 0.0 at end-time (debounce hasn't fired);
        # the client supplies the live scroll position via the hint.
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 0.5},
        )
        assert r.status_code == 200
        assert r.get_json()['reading_slot_completed'] is True

    def test_concurrent_open_sessions_idle_tab_cannot_steal_progress(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Two tabs on the same chapter both open sessions snapshotting
        offset=0. Tab B scrolls past 5% and persists progress; if tab A is
        later closed it must NOT inherit B's progress as its own
        ``offset_delta``. ``start_session`` auto-closes the prior open
        session so this combination is impossible.
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        progress = UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        )
        db_session.add(progress)
        db_session.commit()

        # Tab A: opens, sits idle.
        s_a = start_session(test_user.id, test_chapter.id, db)
        s_a.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 30)
        db_session.commit()

        # Tab B opens later — should auto-close tab A.
        s_b = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        s_a_after_b_start = db.session.get(UserReadingSession, s_a.id)
        assert s_a_after_b_start.ended_at is not None
        assert s_a_after_b_start.offset_delta == pytest.approx(0.0)

        # Tab B scrolls and persists progress, then closes.
        progress.offset_pct = 0.5
        db_session.commit()

        # A late /end on tab A must be a no-op (already closed).
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id, 'current_offset_pct': 0.9},
        )
        assert r.status_code == 200
        assert r.get_json()['reading_slot_completed'] is False
        s_a_final = db.session.get(UserReadingSession, s_a.id)
        assert s_a_final.offset_delta == pytest.approx(0.0)

    def test_end_session_single_qualifying_visit_awards_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        # Start with offset=0; user scrolls during the visit so the server
        # observes a real per-visit delta.
        progress = UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        )
        db_session.add(progress)
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 10)
        progress.offset_pct = 0.5
        db_session.commit()

        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id},
        )
        assert r.status_code == 200
        assert r.get_json()['reading_slot_completed'] is True
        events = StreakEvent.query.filter(
            StreakEvent.user_id == test_user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        ).count()
        assert events == 1
