"""PATCH /api/progress — chapter completion effects and monotonic offset.

Regression for the desktop-reader save path: it used to overwrite
``offset_pct`` (so re-opening a chapter rolled back completed progress)
and never awarded chapter XP / reading counters — those only fired from
``/api/save-reading-position`` (mobile reader).
"""
import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.xp_service import BOOK_CHAPTER_XP_EVENT_TYPE
from app.books.models import UserChapterProgress


def _patch_progress(client, book_id, chapter_id, offset_pct):
    return client.patch(
        '/api/progress',
        json={
            'book_id': book_id,
            'chapter_id': chapter_id,
            'offset_pct': offset_pct,
        },
    )


class TestPatchProgressCompletion:
    @pytest.mark.smoke
    def test_completing_chapter_awards_xp_and_counters(
        self, authenticated_client, test_user, test_book, test_chapter, db_session,
    ):
        response = _patch_progress(
            authenticated_client, test_book.id, test_chapter.id, 1.0,
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['chapter_completed'] is True
        assert data['xp_earned'] >= 50

        events = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type=BOOK_CHAPTER_XP_EVENT_TYPE,
        ).count()
        assert events == 1

        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_chapters_read == 1
        # Единственная глава книги прочитана → книга завершена.
        assert stats.total_books_completed == 1

    def test_offset_is_monotonic_and_no_double_count(
        self, authenticated_client, test_user, test_book, test_chapter, db_session,
    ):
        _patch_progress(authenticated_client, test_book.id, test_chapter.id, 1.0)

        # Скролл к началу / открытие на другом устройстве шлёт меньший offset.
        response = _patch_progress(
            authenticated_client, test_book.id, test_chapter.id, 0.05,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['offset_pct'] == 1.0
        assert 'chapter_completed' not in data

        progress = UserChapterProgress.query.filter_by(
            user_id=test_user.id, chapter_id=test_chapter.id,
        ).first()
        assert progress.offset_pct == 1.0

        # Повторное «дочитывание» не инкрементит счётчики второй раз.
        _patch_progress(authenticated_client, test_book.id, test_chapter.id, 1.0)
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_chapters_read == 1
        assert stats.total_books_completed == 1

    def test_partial_progress_no_completion(
        self, authenticated_client, test_user, test_book, test_chapter, db_session,
    ):
        response = _patch_progress(
            authenticated_client, test_book.id, test_chapter.id, 0.5,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert 'chapter_completed' not in data

        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats is None or (stats.total_chapters_read or 0) == 0
