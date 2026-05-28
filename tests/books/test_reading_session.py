"""Tests for the reading-slot time gate (Task 11)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.achievements.models import StreakEvent
from app.books.reading_session import (
    DAILY_CHAPTER_ADVANCE_MIN,
    DAILY_READING_TARGET_SECONDS,
    MIN_READING_SECONDS,
    UserReadingSession,
    compute_chapter_daily_target_state,
    end_session,
    get_session_duration,
    has_min_reading_time_today,
    is_daily_reading_target_met_today,
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

    def test_qualifying_duration_with_aggregate_offset_advance_credits_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Daily-target aggregation: active reading time >= 5 minutes plus
        chapter offset advance >= 2% across today's sessions credits the
        linear book-reading XP. Per-session enforcement was retired with
        the unified-plan daily reading target (the old 60s + 5%-per-session
        gate has been replaced by 300s + 2%-advance aggregated across
        pause-cycled sessions on the same chapter).
        """
        self._enable_linear_with_pref(db_session, test_user, test_book)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS + 10)
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


class TestTask15Audit:
    """Task 15 audit: ownership, no-duplicate sessions, aggregation, negative offset."""

    def test_end_session_returns_403_for_foreign_session(
        self, authenticated_client, db_session, second_user, test_chapter,
    ):
        """end_session API must return 403 when session belongs to a different user."""
        other = start_session(second_user.id, test_chapter.id, db)
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': other.id},
        )
        assert r.status_code == 403
        body = r.get_json()
        assert body.get('error') == 'forbidden'

    def test_start_session_no_duplicate_open_rows(
        self, app, db_session, test_user, test_chapter,
    ):
        """start_session must produce at most one open row per (user, chapter).

        A second call auto-closes the first open session before inserting a
        new one — the partial unique index enforces the invariant.
        """
        s1 = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        s2 = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        open_count = (
            db_session.query(UserReadingSession)
            .filter(
                UserReadingSession.user_id == test_user.id,
                UserReadingSession.chapter_id == test_chapter.id,
                UserReadingSession.ended_at.is_(None),
            )
            .count()
        )
        assert open_count == 1
        # First session must now be closed
        s1_fresh = db.session.get(UserReadingSession, s1.id)
        assert s1_fresh.ended_at is not None
        # Second session is the currently open one
        s2_fresh = db.session.get(UserReadingSession, s2.id)
        assert s2_fresh.ended_at is None

    def test_has_min_reading_time_aggregates_multiple_sessions(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        """Two sessions each shorter than MIN_READING_SECONDS must together
        satisfy has_min_reading_time_today when their sum >= minimum.
        """
        half = MIN_READING_SECONDS // 2 + 5  # each session alone: below threshold

        s1 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s1, half)
        s2 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s2, half)
        db_session.commit()

        total = get_session_duration(test_user.id, test_chapter.id, db)
        assert total >= MIN_READING_SECONDS
        assert has_min_reading_time_today(test_user.id, test_book.id, db) is True

    def test_single_session_below_threshold_insufficient(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        """A single session shorter than MIN_READING_SECONDS must not satisfy
        has_min_reading_time_today even when another open (unclosed) session exists.
        """
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS - 10)
        # Open session — must NOT contribute to duration
        start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        assert has_min_reading_time_today(test_user.id, test_book.id, db) is False

    def test_negative_offset_delta_does_not_break_aggregation(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        """offset_delta is always clamped to >= 0 by end_session (max(0, ...)).
        has_min_reading_time_today aggregates duration_seconds — unaffected
        by offset values. A session with offset_delta=0 still contributes
        its full duration to the time-gate sum.
        """
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, MIN_READING_SECONDS + 5)
        # Force offset_delta to 0 (simulates start_offset_pct == current offset)
        s.offset_delta = 0.0
        db_session.commit()

        # Duration gate still met regardless of offset_delta value
        assert has_min_reading_time_today(test_user.id, test_book.id, db) is True

    def test_end_session_offset_delta_clamped_never_negative(
        self, app, db_session, test_user, test_chapter,
    ):
        """end_session must compute offset_delta = max(0, ...) so it can never
        be negative even when start_offset_pct > current progress.
        """
        from app.books.models import UserChapterProgress

        # Persist progress at 0.5, then start a session that snapshots 0.5
        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.5,
        ))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        # Simulate progress going backward (should not happen in practice but
        # we want to verify the guard)
        progress = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=test_user.id, chapter_id=test_chapter.id)
            .first()
        )
        progress.offset_pct = 0.0  # regressed
        db_session.commit()

        closed = end_session(s.id, db_session=db)
        db_session.commit()
        assert closed is not None
        assert closed.offset_delta >= 0.0


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
        ``session_id`` must NOT mutate the session's ``offset_delta`` field
        on the row itself, even when ``UserChapterProgress`` advanced after
        the original close. (The unified daily target uses an aggregated
        check across all sessions of the day, so once progress crosses the
        2%-advance threshold the slot does fire — but the individual
        session row remains locked, which is what this test guards.)
        """
        from app.books.models import UserChapterProgress

        test_user.use_linear_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        progress = UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        )
        db_session.add(progress)
        db_session.commit()

        # Visit A: 300s+, no scroll. Closes with offset_delta=0.
        s_a = start_session(test_user.id, test_chapter.id, db)
        s_a.started_at = datetime.now(timezone.utc) - timedelta(seconds=MIN_READING_SECONDS + 30)
        db_session.commit()
        r1 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id},
        )
        assert r1.status_code == 200
        # At this point UserChapterProgress.offset_pct is still 0, so the
        # aggregated daily-target check (offset_advance < 2%) cannot fire
        # the slot yet.
        assert r1.get_json()['reading_slot_completed'] is False
        s_a_refetched = db.session.get(UserReadingSession, s_a.id)
        assert s_a_refetched.offset_delta == pytest.approx(0.0)

        # Progress advances past 2% (e.g. a new visit that wrote progress).
        progress.offset_pct = 0.5
        db_session.commit()

        # Replay /end on session A — must be a no-op for the session row.
        r2 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id, 'current_offset_pct': 0.9},
        )
        assert r2.status_code == 200
        s_a_after = db.session.get(UserReadingSession, s_a.id)
        # The closed session's own offset_delta field stays at 0 — the
        # replay is idempotent on the row even if the aggregated target
        # has since been met by other progress.
        assert s_a_after.offset_delta == pytest.approx(0.0)

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

    def test_concurrent_open_sessions_auto_close_prior(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """``start_session`` auto-closes any prior open session for the same
        ``(user, chapter)``. The closed session's own ``offset_delta`` field
        records the delta between its snapshot and the persisted progress
        AT close-time — it does not pick up later writes to that progress
        row. The unified daily-target check uses the aggregated state of
        all closed sessions for the day, so subsequent honest reading from
        the second tab still counts toward today's slot completion.
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

        # Tab B opens later — should auto-close tab A. At close-time the
        # persisted progress is still 0, so tab A's offset_delta is 0.
        s_b = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        s_a_after_b_start = db.session.get(UserReadingSession, s_a.id)
        assert s_a_after_b_start.ended_at is not None
        assert s_a_after_b_start.offset_delta == pytest.approx(0.0)

        # Tab B scrolls and persists progress to 50%.
        progress.offset_pct = 0.5
        db_session.commit()

        # A late /end on tab A is a no-op for that row (already closed).
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s_a.id, 'current_offset_pct': 0.9},
        )
        assert r.status_code == 200
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


class TestTask51ReaderAudit:
    """Task 51: scroll dedup, unload handler, offset bounds."""

    # ------------------------------------------------------------------
    # offset bounds
    # ------------------------------------------------------------------

    def test_end_session_offset_delta_never_exceeds_1(
        self, app, db_session, test_user, test_chapter,
    ):
        """offset_delta = max(0, current - start) <= 1.0 always because both
        current and start_offset_pct are in [0, 1]."""
        from app.books.models import UserChapterProgress

        db_session.add(UserChapterProgress(
            user_id=test_user.id, chapter_id=test_chapter.id, offset_pct=0.0,
        ))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        progress = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=test_user.id, chapter_id=test_chapter.id)
            .first()
        )
        progress.offset_pct = 1.0
        db_session.commit()

        closed = end_session(s.id, db_session=db)
        db_session.commit()
        assert closed is not None
        assert 0.0 <= closed.offset_delta <= 1.0

    def test_current_offset_pct_greater_than_1_rejected(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        """API must reject current_offset_pct > 1.0 with 400."""
        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 1.5},
        )
        assert r.status_code == 400
        body = r.get_json()
        assert body.get('error') == 'invalid_offset_delta'

    def test_current_offset_pct_negative_rejected(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        """API must reject current_offset_pct < 0 with 400."""
        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': -0.1},
        )
        assert r.status_code == 400
        body = r.get_json()
        assert body.get('error') == 'invalid_offset_delta'

    def test_end_session_clamps_hint_to_0_1(
        self, app, db_session, test_user, test_chapter,
    ):
        """end_session helper clamps the hint via max(0, min(1, hint)) before
        writing to UserChapterProgress even if called directly with bad input."""
        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        closed = end_session(s.id, db_session=db, current_offset_pct=2.5)
        db_session.commit()
        assert closed is not None
        assert closed.offset_delta <= 1.0

    # ------------------------------------------------------------------
    # sendBeacon / text-plain body (unload handler)
    # ------------------------------------------------------------------

    def test_end_session_accepts_text_plain_body(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        """navigator.sendBeacon sends Content-Type: text/plain.
        The endpoint must parse the JSON body regardless of content-type."""
        import json

        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        payload = json.dumps({'session_id': s.id})
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            data=payload,
            content_type='text/plain',
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        assert body['session_id'] == s.id

    def test_end_session_accepts_text_plain_with_offset_hint(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        """sendBeacon can carry a current_offset_pct hint in text/plain body."""
        import json

        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        payload = json.dumps({'session_id': s.id, 'current_offset_pct': 0.4})
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            data=payload,
            content_type='text/plain',
        )
        assert r.status_code == 200
        closed = db.session.get(UserReadingSession, s.id)
        assert closed.offset_delta == pytest.approx(0.4)

    def test_end_session_idempotent_via_pagehide_replay(
        self, authenticated_client, db_session, test_user, test_chapter,
    ):
        """pagehide fires both beforeunload AND pagehide; the JS guards with
        a sessionEnded flag, but a second call to end the same session must
        be a no-op (still 200) and not widen offset_delta."""
        s = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()

        r1 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id},
        )
        assert r1.status_code == 200

        r2 = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 0.9},
        )
        assert r2.status_code == 200
        closed = db.session.get(UserReadingSession, s.id)
        assert closed.offset_delta == pytest.approx(0.0)

    # ------------------------------------------------------------------
    # Rapid progress saves (scroll dedup — server side)
    # ------------------------------------------------------------------

    def test_rapid_progress_saves_are_monotonic(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Multiple quick /api/save-reading-position calls with advancing
        position must not duplicate UserChapterProgress rows and the final
        offset_pct must equal the maximum position seen."""
        from app.books.models import UserChapterProgress

        positions = [0.1, 0.15, 0.2, 0.18, 0.25]
        for pos in positions:
            r = authenticated_client.post(
                '/api/save-reading-position',
                json={
                    'book_id': test_book.id,
                    'position': pos,
                    'chapter': test_chapter.chap_num,
                },
            )
            assert r.status_code == 200

        rows = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=test_user.id, chapter_id=test_chapter.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].offset_pct == pytest.approx(max(positions))

    def test_rapid_progress_saves_with_same_position_idempotent(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """Repeated saves of the same offset are safe — no extra rows, no
        artificial forward progress."""
        from app.books.models import UserChapterProgress

        for _ in range(5):
            r = authenticated_client.post(
                '/api/save-reading-position',
                json={
                    'book_id': test_book.id,
                    'position': 0.3,
                    'chapter': test_chapter.chap_num,
                },
            )
            assert r.status_code == 200

        rows = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=test_user.id, chapter_id=test_chapter.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].offset_pct == pytest.approx(0.3)

    # ------------------------------------------------------------------
    # Tab switch + return: position persistence
    # ------------------------------------------------------------------

    def test_saved_position_persists_for_restoration(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        """After saving a reading position the server persists it in
        UserChapterProgress so that the reader template can restore the scroll
        position on the next page load (simulates tab switch then return)."""
        from app.books.models import UserChapterProgress

        r = authenticated_client.post(
            '/api/save-reading-position',
            json={
                'book_id': test_book.id,
                'position': 0.42,
                'chapter': test_chapter.chap_num,
            },
        )
        assert r.status_code == 200

        progress = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=test_user.id, chapter_id=test_chapter.id)
            .first()
        )
        assert progress is not None
        assert progress.offset_pct == pytest.approx(0.42)


class TestDailyReadingTarget:
    """Aggregated per-chapter daily target: 5min active reading + 2% advance,
    OR chapter completed during today's sessions. Designed to replace the
    legacy per-session 60s+5% gate with a model that survives pause/resume
    cycles cleanly.
    """

    @staticmethod
    def _set_chapter_progress(db_session, user, chapter, offset):
        from app.books.models import UserChapterProgress
        existing = (
            db_session.query(UserChapterProgress)
            .filter_by(user_id=user.id, chapter_id=chapter.id)
            .first()
        )
        if existing:
            existing.offset_pct = offset
        else:
            db_session.add(UserChapterProgress(
                user_id=user.id, chapter_id=chapter.id, offset_pct=offset,
            ))
        db_session.commit()

    def test_target_met_requires_both_time_and_offset(
        self, db_session, test_user, test_chapter,
    ):
        """Both 5min time AND 2% advance are required; meeting only one
        is insufficient."""
        # 5min+ time but 0% advance — not met
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.0)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, DAILY_READING_TARGET_SECONDS + 10)
        db_session.commit()
        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['active_seconds'] >= DAILY_READING_TARGET_SECONDS
        assert state['offset_advance'] == pytest.approx(0.0)
        assert state['daily_target_met'] is False

        # Now advance progress to 5% — both conditions met
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.05)
        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['offset_advance'] == pytest.approx(0.05)
        assert state['daily_target_met'] is True

    def test_target_only_offset_no_time(self, db_session, test_user, test_chapter):
        """2% advance with under-5min time — not met."""
        # Start session at offset 0, advance during session to 10%, but
        # only 30s elapsed — time gate fails.
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.0)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 30)
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.10)
        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['offset_advance'] == pytest.approx(0.10)
        assert state['active_seconds'] == 30
        assert state['daily_target_met'] is False

    def test_target_aggregates_pause_cycled_sessions(
        self, db_session, test_user, test_chapter,
    ):
        """Multiple short sessions on the same chapter today sum honestly.
        This is the pause/resume model: each pause closes a session and
        resume opens a new one. Their durations must add up to satisfy
        the 5min threshold.
        """
        # Two sessions of 200s each = 400s aggregated (>300)
        s1 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s1, 200)
        db_session.commit()
        s2 = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s2, 200)
        db_session.commit()
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.10)

        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['active_seconds'] == 400
        assert state['daily_target_met'] is True

    def test_chapter_completed_detected(self, db_session, test_user, test_chapter):
        """Chapter reaching 99%+ in today's sessions is flagged separately
        from the daily target (used for the chapter-finished banner)."""
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 60)
        db_session.commit()
        self._set_chapter_progress(db_session, test_user, test_chapter, 1.0)
        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['chapter_completed_today'] is True

    def test_chapter_not_completed_when_started_above_threshold(
        self, db_session, test_user, test_chapter,
    ):
        """If the user started today's first session already at >=99%,
        we do NOT consider the chapter "completed today" — the work
        happened on a previous day.
        """
        self._set_chapter_progress(db_session, test_user, test_chapter, 1.0)
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, 30)
        db_session.commit()
        state = compute_chapter_daily_target_state(test_user.id, test_chapter.id, db)
        assert state['chapter_completed_today'] is False

    def test_is_daily_reading_target_met_today_book_scope(
        self, db_session, test_user, test_book, test_chapter,
    ):
        """The book-scoped check returns True when any chapter of the book
        meets the daily target today.
        """
        assert is_daily_reading_target_met_today(test_user.id, test_book.id, db) is False
        s = start_session(test_user.id, test_chapter.id, db)
        _close_session_with_duration(s, DAILY_READING_TARGET_SECONDS + 10)
        db_session.commit()
        self._set_chapter_progress(db_session, test_user, test_chapter, 0.10)
        assert is_daily_reading_target_met_today(test_user.id, test_book.id, db) is True


class TestReadingSessionEndBannerState:
    """`/api/books/reading-session/end` returns banner_state for the client
    to drive the inline completion banner."""

    def test_banner_state_none_when_below_thresholds(
        self, authenticated_client, db_session, test_user, test_book, test_chapter,
    ):
        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 0.01},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['banner_state'] == 'none'
        assert body['daily_target_met'] is False
        assert body['chapter_completed_in_session'] is False

    def test_banner_state_daily_target(
        self, authenticated_client, db_session, test_user, test_book, test_chapter,
    ):
        test_user.use_unified_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=DAILY_READING_TARGET_SECONDS + 30,
        )
        db_session.commit()
        # 10% advance — well past 2%
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 0.10},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['daily_target_met'] is True
        assert body['chapter_completed_in_session'] is False
        assert body['banner_state'] == 'daily_target'

    def test_banner_state_chapter_completed(
        self, authenticated_client, db_session, test_user, test_book, test_chapter,
    ):
        """Chapter finished in a single short session — under daily target,
        but the chapter-completed branch fires for the banner. Banner only
        fires when the chapter belongs to the user's selected book."""
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        db_session.commit()
        # Hint pushes chapter offset to 1.0 — chapter completed in session
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 1.0},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['chapter_completed_in_session'] is True
        assert body['banner_state'] in ('chapter_completed', 'both')

    def test_banner_suppressed_when_book_not_user_preference(
        self, authenticated_client, db_session, test_user, test_book, test_chapter,
    ):
        """Reading a chapter from a book that is NOT the user's selected
        book must not fire the banner — the daily-plan reading slot is
        per-preference, so a misleading "норма выполнена" on a side book
        would not actually close the slot on the dashboard."""
        # No UserReadingPreference set ⇒ banner stays 'none' even with
        # session duration + chapter completion that would otherwise fire.
        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=DAILY_READING_TARGET_SECONDS + 30,
        )
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 1.0},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['banner_state'] == 'none'
        assert body['daily_target_met'] is False
        assert body['chapter_completed_in_session'] is False

    def test_banner_state_both(
        self, authenticated_client, db_session, test_user, test_book, test_chapter,
    ):
        """Long session that finishes the chapter — combined banner."""
        test_user.use_unified_plan = True
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=test_book.id))
        db_session.commit()

        s = start_session(test_user.id, test_chapter.id, db)
        s.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=DAILY_READING_TARGET_SECONDS + 30,
        )
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': s.id, 'current_offset_pct': 1.0},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body['daily_target_met'] is True
        assert body['chapter_completed_in_session'] is True
        assert body['banner_state'] == 'both'
