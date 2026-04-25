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
        session = start_session(test_user.id, test_chapter.id, db)
        db_session.commit()
        closed = end_session(session.id, offset_delta=0.1, db_session=db)
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
        assert end_session(999_999, 0.0, db_session=db) is None


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
            json={'session_id': sid, 'offset_delta': 0.07},
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
            json={'session_id': 999_999, 'offset_delta': 0.0},
        )
        assert r.status_code == 404

    def test_end_other_users_session_is_forbidden(
        self, authenticated_client, db_session, test_user, second_user, test_chapter,
    ):
        other = start_session(second_user.id, test_chapter.id, db)
        db_session.commit()
        r = authenticated_client.post(
            '/api/books/reading-session/end',
            json={'session_id': other.id, 'offset_delta': 0.0},
        )
        assert r.status_code == 403
