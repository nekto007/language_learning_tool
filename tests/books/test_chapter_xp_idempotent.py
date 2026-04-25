"""Tests for idempotent book_chapter XP awarding (Task 1)."""
from datetime import date

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.xp_service import (
    BOOK_CHAPTER_XP_EVENT_TYPE,
    award_book_chapter_xp_idempotent,
)
from app.books.models import UserChapterProgress
from app.utils.db import db


class TestAwardBookChapterXpIdempotent:
    def test_first_call_awards_xp_and_writes_streak_event(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        result = award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=test_book.id,
            chapter_id=test_chapter.id,
            xp=50,
            for_date=date(2026, 4, 24),
            db_session=db,
        )
        assert result is not None
        assert result.xp_awarded >= 50
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).all()
        assert len(events) == 1
        assert events[0].details['book_id'] == test_book.id
        assert events[0].details['chapter_id'] == test_chapter.id

    def test_second_call_returns_none_and_no_duplicate_xp(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        first = award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=test_book.id,
            chapter_id=test_chapter.id,
            xp=50,
            for_date=date(2026, 4, 24),
            db_session=db,
        )
        assert first is not None
        total_after_first = UserStatistics.query.filter_by(
            user_id=test_user.id
        ).first().total_xp

        second = award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=test_book.id,
            chapter_id=test_chapter.id,
            xp=50,
            for_date=date(2026, 4, 25),
            db_session=db,
        )
        assert second is None
        total_after_second = UserStatistics.query.filter_by(
            user_id=test_user.id
        ).first().total_xp
        assert total_after_second == total_after_first

        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).count()
        assert events == 1

    def test_different_chapter_awards_separately(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        from app.books.models import Chapter
        ch2 = Chapter(book_id=test_book.id, chap_num=2, title='C2', words=50, text_raw='x')
        db_session.add(ch2)
        db_session.commit()

        a = award_book_chapter_xp_idempotent(
            user_id=test_user.id, book_id=test_book.id, chapter_id=test_chapter.id,
            xp=50, for_date=date(2026, 4, 24), db_session=db,
        )
        b = award_book_chapter_xp_idempotent(
            user_id=test_user.id, book_id=test_book.id, chapter_id=ch2.id,
            xp=50, for_date=date(2026, 4, 24), db_session=db,
        )
        assert a is not None and b is not None
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).count()
        assert events == 2

    def test_zero_or_negative_xp_is_noop(
        self, app, db_session, test_user, test_chapter, test_book,
    ):
        assert award_book_chapter_xp_idempotent(
            user_id=test_user.id, book_id=test_book.id, chapter_id=test_chapter.id,
            xp=0, for_date=date(2026, 4, 24), db_session=db,
        ) is None


class TestSaveReadingPositionEndpoint:
    @pytest.mark.smoke
    def test_chapter_complete_awards_xp_once(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        r1 = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 1.0, 'chapter': test_chapter.chap_num},
        )
        assert r1.status_code == 200
        data1 = r1.get_json()
        assert data1.get('chapter_completed') is True
        first_xp = data1.get('xp_earned', 0)
        assert first_xp > 0

        r2 = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 1.0, 'chapter': test_chapter.chap_num},
        )
        assert r2.status_code == 200
        data2 = r2.get_json()
        # Second call: was_incomplete is False, no new XP award
        assert not data2.get('chapter_completed', False)

        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).count()
        assert events == 1

    def test_progress_below_completion_no_xp(
        self, authenticated_client, db_session, test_user, test_chapter, test_book,
    ):
        r = authenticated_client.post(
            '/api/save-reading-position',
            json={'book_id': test_book.id, 'position': 0.5, 'chapter': test_chapter.chap_num},
        )
        assert r.status_code == 200
        events = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).count()
        assert events == 0

        progress = UserChapterProgress.query.filter_by(
            user_id=test_user.id, chapter_id=test_chapter.id
        ).first()
        assert progress is not None
        assert progress.offset_pct == 0.5

    def test_single_transaction_source_has_one_commit(self):
        """Source-level check: save_reading_position has exactly one
        db.session.commit() after refactor (single transaction boundary).
        """
        import inspect
        from app.books import api
        src = inspect.getsource(api.save_reading_position)
        assert src.count('db.session.commit()') == 1
