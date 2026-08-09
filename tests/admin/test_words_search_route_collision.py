"""Regression tests for ADM-001 (cross-zone audit 2026-08-08).

``admin.search_words_api`` (book-scoped, INNER JOIN on ``word_book_link``) and
``admin.api_words_search`` (general autocomplete) were both registered on
``/admin/api/words/search``. Registration order made the book-scoped one win, so
the quiz-deck editor — the only consumer of that URL — could never return a word
that is not linked to a book: 12 322 of 25 089 rows in production.
"""
from __future__ import annotations

import uuid

import pytest

from app.words.models import CollectionWords


@pytest.fixture
def unlinked_word(db_session):
    """A word with no ``word_book_link`` row — invisible to the book-scoped view."""
    word = CollectionWords(
        english_word=f'zzunlinked{uuid.uuid4().hex[:6]}',
        russian_word='несвязанное',
        level='B1',
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestRouteResolution:
    def test_words_search_resolves_to_the_general_autocomplete(self, app):
        adapter = app.url_map.bind('localhost')
        endpoint, _ = adapter.match('/admin/api/words/search')

        assert endpoint == 'admin.api_words_search'

    def test_book_scoped_search_has_its_own_url(self, app):
        adapter = app.url_map.bind('localhost')
        endpoint, _ = adapter.match('/admin/api/book-courses/words/search')

        assert endpoint == 'admin.search_words_api'

    def test_no_two_rules_share_a_url(self, app):
        seen: dict[str, list[str]] = {}
        for rule in app.url_map.iter_rules():
            key = f'{rule.rule}|{sorted(rule.methods)}'
            seen.setdefault(key, []).append(rule.endpoint)

        collisions = {k: v for k, v in seen.items() if len(v) > 1}
        assert '/admin/api/words/search|' not in ''.join(collisions), collisions


class TestAutocompleteReachesUnlinkedWords:
    def test_unlinked_word_is_returned(self, admin_client, unlinked_word):
        response = admin_client.get(
            f'/admin/api/words/search?q={unlinked_word.english_word[:8]}',
        )

        assert response.status_code == 200
        ids = [row['id'] for row in response.get_json()]
        assert unlinked_word.id in ids

    def test_words_without_translation_are_excluded(self, admin_client, db_session):
        blank = CollectionWords(
            english_word=f'zzblank{uuid.uuid4().hex[:6]}',
            russian_word='',
            level='B1',
        )
        db_session.add(blank)
        db_session.commit()

        response = admin_client.get(f'/admin/api/words/search?q={blank.english_word[:7]}')

        assert response.status_code == 200
        assert blank.id not in [row['id'] for row in response.get_json()]

    def test_limit_parameter_is_honoured(self, admin_client, db_session):
        prefix = f'zzlim{uuid.uuid4().hex[:5]}'
        for i in range(5):
            db_session.add(CollectionWords(
                english_word=f'{prefix}{i}', russian_word=f'слово{i}', level='A1',
            ))
        db_session.commit()

        response = admin_client.get(f'/admin/api/words/search?q={prefix}&limit=2')

        assert response.status_code == 200
        assert len(response.get_json()) == 2

    @pytest.mark.parametrize('bad_limit', ['abc', '-1', '0', '1.5'])
    def test_invalid_limit_is_a_400_not_a_500(self, admin_client, bad_limit):
        # `int(request.args.get('limit'))` raised straight into the error
        # handler, and a negative value travelled on into SQLAlchemy.
        response = admin_client.get(f'/admin/api/words/search?q=ru&limit={bad_limit}')

        assert response.status_code == 400

    def test_oversized_limit_is_clamped_not_rejected(self, admin_client):
        response = admin_client.get('/admin/api/words/search?q=ru&limit=9999')

        assert response.status_code == 200
        assert len(response.get_json()) <= 50


class TestBookScopedSearchStillWorks:
    def test_book_scoped_endpoint_responds(self, admin_client):
        response = admin_client.get('/admin/api/book-courses/words/search?q=ru')

        assert response.status_code == 200
        assert isinstance(response.get_json(), list)

    def test_templates_reference_it_by_endpoint_name(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'admin' / 'book_courses'
        for name in ('edit_vocabulary.html', 'edit_lesson.html'):
            source = (root / name).read_text(encoding='utf-8')
            assert "url_for('admin.search_words_api')" in source
