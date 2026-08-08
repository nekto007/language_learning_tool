"""Regression tests for SEC-002 (cross-zone audit 2026-08-08).

``/books/<id>/read?from=…`` rendered the raw query parameter into three ``href``
attributes of ``reader_simple.html``, so an external URL (or a ``javascript:``
payload) survived into the "Назад" control. Every candidate now goes through
``get_safe_redirect_url``.
"""
from __future__ import annotations

import pytest

from app.books.models import Book, Chapter
from app.books.routes import _safe_back_url, _same_host_path


@pytest.fixture
def public_book(db_session):
    book = Book(
        title='Reader Book', author='A', level='A1', chapters_cnt=1,
        rights_status='public_domain', is_published=True,
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(Chapter(
        book_id=book.id, chap_num=1, title='Ch 1',
        text_raw='Some chapter text.', words=3,
    ))
    db_session.flush()
    return book


class TestSafeBackUrlHelper:
    @pytest.mark.parametrize('hostile', [
        'https://evil.example/login',
        '//evil.example/login',
        'javascript:alert(1)',
        r'/\evil.example',
        'evil.example',
    ])
    def test_hostile_candidates_fall_back_to_the_book_page(self, app, hostile):
        with app.test_request_context('/'):
            assert _safe_back_url(hostile, 7) == '/books/7'

    def test_relative_path_survives(self, app):
        with app.test_request_context('/'):
            assert _safe_back_url('/curriculum/module/3', 7) == '/curriculum/module/3'

    def test_missing_candidate_falls_back(self, app):
        with app.test_request_context('/'):
            assert _safe_back_url(None, 7) == '/books/7'


class TestSameHostPath:
    def test_external_referrer_is_dropped(self, app):
        with app.test_request_context('/', base_url='http://localhost'):
            assert _same_host_path('https://evil.example/curriculum') is None

    def test_same_host_referrer_becomes_relative(self, app):
        with app.test_request_context('/', base_url='http://localhost'):
            assert _same_host_path('http://localhost/curriculum/module/3?x=1') == \
                '/curriculum/module/3?x=1'


def _back_link_targets(html: str) -> list[str]:
    """Every ``href`` the reader renders for its three "Назад" controls."""
    import re

    return re.findall(r'<a\s+href="([^"]*)"[^>]*class="rdr-back-btn"', html) + \
        re.findall(r'<a\s+href="([^"]*)"\s*\n\s*class="rdr-', html)


class TestReaderRendersOnlySafeBackUrl:
    def test_external_from_never_reaches_a_back_link(self, authenticated_client, public_book):
        response = authenticated_client.get(
            f'/books/{public_book.id}/read?from=https://evil.example/login',
        )

        assert response.status_code == 200
        targets = _back_link_targets(response.get_data(as_text=True))
        assert targets, 'no back links rendered — test would pass vacuously'
        assert all(t == f'/books/{public_book.id}' for t in targets)

    def test_javascript_from_never_reaches_a_back_link(self, authenticated_client, public_book):
        response = authenticated_client.get(
            f'/books/{public_book.id}/read?from=javascript:alert(1)',
        )

        assert response.status_code == 200
        targets = _back_link_targets(response.get_data(as_text=True))
        assert targets
        assert not any(t.startswith('javascript:') for t in targets)

    def test_external_referrer_never_reaches_a_back_link(self, authenticated_client, public_book):
        response = authenticated_client.get(
            f'/books/{public_book.id}/read',
            headers={'Referer': 'https://evil.example/curriculum'},
        )

        assert response.status_code == 200
        targets = _back_link_targets(response.get_data(as_text=True))
        assert targets
        assert all('evil.example' not in t for t in targets)

    def test_relative_from_still_works(self, authenticated_client, public_book):
        response = authenticated_client.get(
            f'/books/{public_book.id}/read?from=/curriculum/module/3',
        )

        assert response.status_code == 200
        targets = _back_link_targets(response.get_data(as_text=True))
        assert targets
        assert all(t == '/curriculum/module/3' for t in targets)
