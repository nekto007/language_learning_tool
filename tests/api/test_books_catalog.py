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
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.books.reading_session import UserReadingSession
from app.curriculum.models import CEFRLevel
from app.daily_plan.linear.models import UserReadingPreference
from app.study.models import StudySettings
from app.utils.db import db as real_db


def _make_book(db_session, level: str, *, chapters: int = 3) -> Book:
    suffix = uuid.uuid4().hex[:8]
    # public_domain keeps the book visible to test_user, who has no
    # ``books`` module granted — keeps the catalog test focused on level
    # filtering rather than rights gating.
    book = Book(
        title=f'Book {level} {suffix}',
        author='Author',
        level=level,
        chapters_cnt=chapters,
        summary=f'Summary {suffix}',
        rights_status='public_domain',
    )
    db_session.add(book)
    db_session.commit()
    return book


def _add_chapters(db_session, book: Book, count: int | None = None) -> list[Chapter]:
    chapters = []
    for i in range(1, (count or book.chapters_cnt) + 1):
        chapter = Chapter(
            book_id=book.id,
            chap_num=i,
            title=f'Chapter {i}',
            words=100,
            text_raw='Text',
        )
        db_session.add(chapter)
        chapters.append(chapter)
    db_session.commit()
    return chapters


def _complete_book(db_session, user_id: int, chapters: list[Chapter]) -> None:
    for chapter in chapters:
        db_session.add(UserChapterProgress(
            user_id=user_id,
            chapter_id=chapter.id,
            offset_pct=1.0,
        ))
    db_session.commit()


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


def test_pilot_excerpt_is_counted_from_the_projected_text_and_does_not_choose_the_book(
    app: Flask, authenticated_client: FlaskClient, db_session: scoped_session, test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pilot = _make_book(db_session, 'A1')
    extra = _make_book(db_session, 'A1')
    pilot.slug, extra.slug = 'excerpt-pilot', 'another-open-book'
    pilot_chapters, _ = _add_chapters(db_session, pilot), _add_chapters(db_session, extra)
    pilot_chapters[0].text_raw = '\n \t '
    pilot_chapters[1].text_raw = ('The little boat crosses the river. ' * 45).strip() + ' Hidden ending.'
    db_session.commit()
    settings = StudySettings.get_settings(test_user.id)
    settings.reading_minutes_per_day = 0
    db_session.commit()
    picker = '/api/books/catalog?view=plan_picker'
    path = f'/api/books/{pilot.id}/plan-excerpt'
    assert authenticated_client.get(path).status_code == 404
    monkeypatch.setitem(app.config, 'BOOK_PLAN_EXCERPT_SLUG', pilot.slug)
    regular = authenticated_client.get('/api/books/catalog').json['books']
    assert all('plan_excerpt_url' not in row for row in regular)
    rows = {row['id']: row for row in authenticated_client.get(picker).json['books']}
    assert rows[pilot.id]['plan_excerpt_url'] == path and 'plan_excerpt_url' not in rows[extra.id]
    assert authenticated_client.get(f'/api/books/{extra.id}/plan-excerpt').status_code == 404
    response = authenticated_client.get(path)
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
    document = response.json
    excerpt = ' '.join(document['paragraphs'])
    assert document['level'] == 'A1' and document['chapter_title'] == 'Chapter 2'
    assert document['words'] == len(excerpt.split()) == 156 and document['minutes'] == 2
    assert excerpt.endswith('river.') and 'Hidden ending.' not in excerpt
    assert settings.reading_minutes_per_day == 0
    assert not UserReadingPreference.query.filter_by(user_id=test_user.id).count()
    assert not UserChapterProgress.query.filter_by(user_id=test_user.id).count()
    assert not UserReadingSession.query.filter_by(user_id=test_user.id).count()
    assert authenticated_client.post('/api/books/select', json={'book_id': pilot.id}).status_code == 200
    assert settings.reading_minutes_per_day == 5
    settings.reading_minutes_per_day = 9
    db_session.commit()
    assert authenticated_client.post('/api/books/select', json={'book_id': extra.id}).status_code == 200
    assert settings.reading_minutes_per_day == 9


@pytest.mark.parametrize('reason', ['draft', 'private', 'empty'])
def test_picker_and_direct_excerpt_hide_unavailable_pilot(
    app: Flask, authenticated_client: FlaskClient, db_session: scoped_session,
    monkeypatch: pytest.MonkeyPatch, reason: str,
) -> None:
    pilot = _make_book(db_session, 'A1', chapters=1)
    chapter, = _add_chapters(db_session, pilot)
    pilot.slug = 'unavailable-pilot'
    monkeypatch.setitem(app.config, 'BOOK_PLAN_EXCERPT_SLUG', pilot.slug)
    if reason == 'draft':
        pilot.is_published = False
    elif reason == 'private':
        pilot.rights_status = 'companion_only'
    else:
        chapter.text_raw = '\\n\t '
    db_session.commit()
    picker = authenticated_client.get('/api/books/catalog?view=plan_picker')
    assert picker.status_code == 200
    assert pilot.id not in [entry['id'] for entry in picker.json['books']]
    response = authenticated_client.get(f'/api/books/{pilot.id}/plan-excerpt')
    assert response.status_code == 404 and 'paragraphs' not in response.json


class TestCatalogEndpoint:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/books/catalog')
        assert resp.status_code == 401

    def test_filters_to_user_level_window(self, authenticated_client, db_session, cefr_levels, test_user):
        a1 = _make_book(db_session, 'A1')
        a2 = _make_book(db_session, 'A2')
        b1 = _make_book(db_session, 'B1')
        b2 = _make_book(db_session, 'B2')

        for book in (a1, a2, b1, b2):
            _add_chapters(db_session, book)
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
        for book in (a0, b1, b2):
            _add_chapters(db_session, book)

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
        empty = _make_book(db_session, 'A2', chapters=2)
        good = _make_book(db_session, 'A2', chapters=0)
        _add_chapters(db_session, good, 2)
        test_user.onboarding_level = 'A2'
        db_session.commit()

        resp = authenticated_client.get('/api/books/catalog?level=A2')
        ids = {b['id'] for b in resp.get_json()['books']}
        assert good.id in ids
        assert empty.id not in ids

    def test_response_includes_metadata_fields(self, authenticated_client, db_session, cefr_levels):
        book = _make_book(db_session, 'A2')
        _add_chapters(db_session, book)
        resp = authenticated_client.get('/api/books/catalog?level=A2')
        data = resp.get_json()
        match = next(b for b in data['books'] if b['id'] == book.id)
        for key in ('title', 'author', 'level', 'summary', 'cover_image', 'chapters_cnt'):
            assert key in match

    def test_excludes_completed_books(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        completed = _make_book(db_session, 'A2')
        available = _make_book(db_session, 'A2')
        _complete_book(db_session, test_user.id, _add_chapters(db_session, completed))
        _add_chapters(db_session, available)
        test_user.onboarding_level = 'A2'
        db_session.commit()

        resp = authenticated_client.get('/api/books/catalog?level=A2')
        assert resp.status_code == 200
        ids = {b['id'] for b in resp.get_json()['books']}
        assert completed.id not in ids
        assert available.id in ids


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

    def test_draft_book_returns_404_and_persists_nothing(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        """An unpublished book is invisible to the reader routes, so the
        selector must refuse it too — otherwise the required reading slot
        points at a permanent 404 and the day can never be secured."""
        book = _make_book(db_session, 'A2')
        book.is_published = False
        db_session.commit()

        resp = authenticated_client.post('/api/books/select', json={'book_id': book.id})
        assert resp.status_code == 404
        assert resp.get_json()['error'] == 'book_not_found'
        assert UserReadingPreference.query.filter_by(user_id=test_user.id).first() is None

    def test_select_persists_preference_and_returns_slot(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        book = _make_book(db_session, 'A2')
        # The slot only names a book that can actually be read: a title whose
        # ``chapters_cnt`` is not backed by Chapter rows is refused by
        # ``_book_is_actionable_for_reading`` and degrades to needs_selection.
        _add_chapters(db_session, book)

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
        _add_chapters(db_session, book_a)
        _add_chapters(db_session, book_b)

        resp1 = authenticated_client.post('/api/books/select', json={'book_id': book_a.id})
        assert resp1.status_code == 200
        resp2 = authenticated_client.post('/api/books/select', json={'book_id': book_b.id})
        assert resp2.status_code == 200

        prefs = UserReadingPreference.query.filter_by(user_id=test_user.id).all()
        assert len(prefs) == 1
        assert prefs[0].book_id == book_b.id

    def test_select_completed_book_returns_409(
        self, authenticated_client, db_session, cefr_levels, test_user,
    ):
        book = _make_book(db_session, 'A2')
        _complete_book(db_session, test_user.id, _add_chapters(db_session, book))

        resp = authenticated_client.post('/api/books/select', json={'book_id': book.id})
        assert resp.status_code == 409
        assert resp.get_json()['error'] == 'book_already_completed'
        assert UserReadingPreference.query.filter_by(user_id=test_user.id).first() is None
