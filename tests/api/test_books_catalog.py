"""Tests for /api/books/catalog and /api/books/select endpoints.

Covers:
- GET /api/books/catalog filters books to the user's level window (±1).
- GET respects ``?level=`` override.
- POST /api/books/select persists ``UserReadingPreference`` and returns
  the refreshed reading slot.
- POST handles invalid book_id with a 400/404, never persists.
- Auth is required (anonymous → 401).
"""
from __future__ import annotations

import uuid

import pytest

from app.books.models import Book
from app.curriculum.models import CEFRLevel
from app.daily_plan.linear.models import UserReadingPreference
from app.utils.db import db as real_db


def _make_book(db_session, level: str, *, chapters: int = 3) -> Book:
    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Book {level} {suffix}',
        author='Author',
        level=level,
        chapters_cnt=chapters,
        summary=f'Summary {suffix}',
    )
    db_session.add(book)
    db_session.commit()
    return book


def _ensure_level(db_session, code: str, order: int) -> CEFRLevel:
    existing = CEFRLevel.query.filter_by(code=code).first()
    if existing:
        return existing
    level = CEFRLevel(code=code, name=code, description='desc', order=order)
    db_session.add(level)
    db_session.commit()
    return level


@pytest.fixture
def cefr_levels(db_session):
    levels = {
        'A0': _ensure_level(db_session, 'A0', 0),
        'A1': _ensure_level(db_session, 'A1', 1),
        'A2': _ensure_level(db_session, 'A2', 2),
        'B1': _ensure_level(db_session, 'B1', 3),
        'B2': _ensure_level(db_session, 'B2', 4),
    }
    return levels


class TestCatalogEndpoint:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/books/catalog')
        assert resp.status_code == 401

    def test_filters_to_user_level_window(self, authenticated_client, db_session, cefr_levels, test_user):
        a1 = _make_book(db_session, 'A1')
        a2 = _make_book(db_session, 'A2')
        b1 = _make_book(db_session, 'B1')
        b2 = _make_book(db_session, 'B2')

        test_user.onboarding_level = 'A2'
        db_session.commit()

        resp = authenticated_client.get('/api/books/catalog')
        assert resp.status_code == 200
        data = resp.get_json()
        ids = {b['id'] for b in data['books']}
        # Window is A1, A2, B1 — B2 excluded.
        assert a1.id in ids
        assert a2.id in ids
        assert b1.id in ids
        assert b2.id not in ids

    def test_respects_level_query_override(self, authenticated_client, db_session, cefr_levels):
        b1 = _make_book(db_session, 'B1')
        b2 = _make_book(db_session, 'B2')
        a0 = _make_book(db_session, 'A0')

        resp = authenticated_client.get('/api/books/catalog?level=B1')
        assert resp.status_code == 200
        data = resp.get_json()
        ids = {b['id'] for b in data['books']}
        # Window is A2, B1, B2 — A0 excluded.
        assert b1.id in ids
        assert b2.id in ids
        assert a0.id not in ids
        assert data['user_level'] == 'B1'

    def test_skips_books_with_zero_chapters(self, authenticated_client, db_session, cefr_levels, test_user):
        empty = _make_book(db_session, 'A2', chapters=0)
        good = _make_book(db_session, 'A2', chapters=2)
        test_user.onboarding_level = 'A2'
        db_session.commit()

        resp = authenticated_client.get('/api/books/catalog?level=A2')
        ids = {b['id'] for b in resp.get_json()['books']}
        assert good.id in ids
        assert empty.id not in ids

    def test_response_includes_metadata_fields(self, authenticated_client, db_session, cefr_levels):
        book = _make_book(db_session, 'A2')
        resp = authenticated_client.get('/api/books/catalog?level=A2')
        data = resp.get_json()
        match = next(b for b in data['books'] if b['id'] == book.id)
        for key in ('title', 'author', 'level', 'summary', 'cover_image', 'chapters_cnt'):
            assert key in match


class TestSelectEndpoint:
    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/books/select', json={'book_id': 1})
        assert resp.status_code == 401

    def test_invalid_book_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post('/api/books/select', json={'book_id': 'oops'})
        assert resp.status_code == 400

    def test_unknown_book_id_returns_404(self, authenticated_client):
        resp = authenticated_client.post('/api/books/select', json={'book_id': 9999999})
        assert resp.status_code == 404

    def test_select_persists_preference_and_returns_slot(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        book = _make_book(db_session, 'A2')

        resp = authenticated_client.post('/api/books/select', json={'book_id': book.id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['slot']['kind'] == 'reading'
        assert data['slot']['data']['book_id'] == book.id
        assert data['slot']['data']['needs_selection'] is False

        pref = UserReadingPreference.query.filter_by(user_id=test_user.id).first()
        assert pref is not None
        assert pref.book_id == book.id

    def test_select_updates_existing_preference(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        book_a = _make_book(db_session, 'A2')
        book_b = _make_book(db_session, 'A2')

        resp1 = authenticated_client.post('/api/books/select', json={'book_id': book_a.id})
        assert resp1.status_code == 200
        resp2 = authenticated_client.post('/api/books/select', json={'book_id': book_b.id})
        assert resp2.status_code == 200

        prefs = UserReadingPreference.query.filter_by(user_id=test_user.id).all()
        assert len(prefs) == 1
        assert prefs[0].book_id == book_b.id
