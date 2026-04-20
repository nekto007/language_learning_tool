"""Tests for the linear book-reading slot.

Covers:
- No ``UserReadingPreference`` → "select-book" slot pointing at the modal.
- Preference present → slot reflects the chosen book and current chapter.
- ``completed`` is True when chapter progress today crosses the threshold.
- Defensive fallback when the preference points at a deleted book.
- Plan assembly includes a reading slot in ``baseline_slots``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.reading_slot import (
    READ_PROGRESS_THRESHOLD,
    build_reading_slot,
)
from app.utils.db import db as real_db


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'readslot_{suffix}',
        email=f'readslot_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_book(db_session, *, level: str = 'A2', chapters: int = 3, cover: str | None = None) -> Book:
    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Book {suffix}',
        author='Test Author',
        level=level,
        chapters_cnt=chapters,
        summary='A short summary.',
        cover_image=cover,
    )
    db_session.add(book)
    db_session.commit()
    for chap_num in range(1, chapters + 1):
        chap = Chapter(
            book_id=book.id,
            chap_num=chap_num,
            title=f'Chapter {chap_num}',
            words=100,
            text_raw='text...',
        )
        db_session.add(chap)
    db_session.commit()
    return book


def _set_preference(db_session, user: User, book: Book) -> UserReadingPreference:
    pref = UserReadingPreference(
        user_id=user.id,
        book_id=book.id,
        selected_at=datetime.now(timezone.utc),
    )
    db_session.add(pref)
    db_session.commit()
    return pref


def _record_chapter_progress(
    db_session,
    user: User,
    chapter: Chapter,
    *,
    offset_pct: float,
    when: datetime | None = None,
) -> UserChapterProgress:
    row = UserChapterProgress(
        user_id=user.id,
        chapter_id=chapter.id,
        offset_pct=offset_pct,
        updated_at=when or datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.commit()
    return row


class TestNoPreference:
    def test_first_entry_returns_select_book_slot(self, db_session):
        user = _make_user(db_session)

        slot = build_reading_slot(user.id, real_db)

        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'reading'
        assert slot.title == 'Выбрать книгу'
        assert slot.url == '#book-select-modal'
        assert slot.completed is False
        assert slot.data['needs_selection'] is True

    def test_to_dict_shape(self, db_session):
        user = _make_user(db_session)
        slot_dict = build_reading_slot(user.id, real_db).to_dict()
        assert set(slot_dict) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'reading'
        assert slot_dict['data']['needs_selection'] is True


class TestWithPreference:
    def test_preference_present_returns_book_slot(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session, level='A2', cover='/static/img/x.jpg')
        _set_preference(db_session, user, book)

        slot = build_reading_slot(user.id, real_db)

        assert slot.title == book.title
        assert slot.url == f'/read/{book.id}?from=linear_plan'
        assert slot.completed is False
        assert slot.data['book_id'] == book.id
        assert slot.data['book_level'] == 'A2'
        assert slot.data['cover_image'] == '/static/img/x.jpg'
        assert slot.data['needs_selection'] is False

    def test_current_chapter_reflects_latest_progress(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session, chapters=3)
        _set_preference(db_session, user, book)
        chapters = sorted(book.chapters, key=lambda c: c.chap_num)
        # Older progress on chapter 1, newer on chapter 2
        _record_chapter_progress(
            db_session, user, chapters[0],
            offset_pct=1.0,
            when=datetime.now(timezone.utc) - timedelta(days=5),
        )
        _record_chapter_progress(
            db_session, user, chapters[1],
            offset_pct=0.4,
            when=datetime.now(timezone.utc) - timedelta(days=4),
        )

        slot = build_reading_slot(user.id, real_db)

        assert slot.data['current_chapter_num'] == 2
        assert slot.data['current_chapter_title'] == chapters[1].title

    def test_deleted_book_falls_back_to_select(self, db_session, monkeypatch):
        """If db.session.get(Book, ...) returns None — for example a stale
        session cache after a deletion — the slot defensively falls back
        to the select-book mode rather than rendering with empty title."""
        user = _make_user(db_session)
        book = _make_book(db_session)
        _set_preference(db_session, user, book)

        original_get = real_db.session.get

        def _stub_get(model, pk, *args, **kwargs):
            if model is Book and pk == book.id:
                return None
            return original_get(model, pk, *args, **kwargs)

        monkeypatch.setattr(real_db.session, 'get', _stub_get)

        slot = build_reading_slot(user.id, real_db)
        assert slot.title == 'Выбрать книгу'
        assert slot.url == '#book-select-modal'


class TestCompletedToday:
    def test_completed_when_progress_today_above_threshold(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        _set_preference(db_session, user, book)
        chapter = book.chapters[0]
        _record_chapter_progress(
            db_session, user, chapter,
            offset_pct=READ_PROGRESS_THRESHOLD + 0.01,
            when=datetime.now(timezone.utc),
        )

        slot = build_reading_slot(user.id, real_db)
        assert slot.completed is True

    def test_not_completed_when_progress_below_threshold(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        _set_preference(db_session, user, book)
        chapter = book.chapters[0]
        _record_chapter_progress(
            db_session, user, chapter,
            offset_pct=0.01,
            when=datetime.now(timezone.utc),
        )

        slot = build_reading_slot(user.id, real_db)
        assert slot.completed is False

    def test_not_completed_when_progress_was_yesterday(self, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        _set_preference(db_session, user, book)
        chapter = book.chapters[0]
        _record_chapter_progress(
            db_session, user, chapter,
            offset_pct=0.5,
            when=datetime.now(timezone.utc) - timedelta(days=1, hours=2),
        )

        slot = build_reading_slot(user.id, real_db)
        assert slot.completed is False


class TestPlanIntegration:
    def test_get_linear_plan_includes_reading_slot(self, db_session):
        from app.daily_plan.linear.plan import get_linear_plan

        user = _make_user(db_session)
        payload = get_linear_plan(user.id, real_db)
        kinds = [s['kind'] for s in payload['baseline_slots']]
        assert 'reading' in kinds
        reading = next(s for s in payload['baseline_slots'] if s['kind'] == 'reading')
        assert reading['data']['needs_selection'] is True

    def test_get_linear_plan_reading_slot_after_preference(self, db_session):
        from app.daily_plan.linear.plan import get_linear_plan

        user = _make_user(db_session)
        book = _make_book(db_session)
        _set_preference(db_session, user, book)

        payload = get_linear_plan(user.id, real_db)
        reading = next(s for s in payload['baseline_slots'] if s['kind'] == 'reading')
        assert reading['data']['needs_selection'] is False
        assert reading['data']['book_id'] == book.id
        assert reading['url'] == f'/read/{book.id}?from=linear_plan'
