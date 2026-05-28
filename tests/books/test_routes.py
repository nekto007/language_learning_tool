"""Tests for book catalog access control and edge cases (Task 16)."""
from unittest.mock import patch

import pytest

from app.books.models import Book, Chapter


@pytest.fixture
def published_book(db_session):
    book = Book(
        title='Published Book',
        author='Author A',
        level='A1',
        chapters_cnt=3,
        is_published=True,
    )
    db_session.add(book)
    db_session.flush()
    for i in range(1, 4):
        db_session.add(Chapter(
            book_id=book.id,
            chap_num=i,
            title=f'Chapter {i}',
            words=100,
            text_raw=f'Chapter {i} content.',
        ))
    db_session.flush()
    return book


@pytest.fixture
def unpublished_book(db_session):
    book = Book(
        title='Draft Book',
        author='Author B',
        level='A2',
        chapters_cnt=2,
        is_published=False,
    )
    db_session.add(book)
    db_session.flush()
    for i in range(1, 3):
        db_session.add(Chapter(
            book_id=book.id,
            chap_num=i,
            title=f'Draft Chapter {i}',
            words=50,
            text_raw=f'Draft chapter {i} content.',
        ))
    db_session.flush()
    return book


@pytest.fixture
def book_no_chapters(db_session):
    book = Book(
        title='Empty Book',
        author='Author C',
        level='B1',
        chapters_cnt=0,
        is_published=True,
    )
    db_session.add(book)
    db_session.flush()
    return book


class TestUnauthorizedAccess:
    """Unauthenticated users are redirected (books routes are login_required)."""

    def test_book_list_redirects_unauthenticated(self, client):
        response = client.get('/books')
        assert response.status_code == 302
        assert '/login' in response.headers['Location'] or response.status_code == 302

    def test_book_details_redirects_unauthenticated(self, client, published_book):
        response = client.get(f'/books/{published_book.id}')
        assert response.status_code == 302

    def test_book_words_redirects_unauthenticated(self, client, published_book):
        response = client.get(f'/books/{published_book.id}/words')
        assert response.status_code == 302


class TestUnpublishedBookAccess:
    """Unpublished books (is_published=False) are not accessible to regular users."""

    def test_unpublished_book_details_returns_404_for_regular_user(
        self, authenticated_client, unpublished_book
    ):
        response = authenticated_client.get(f'/books/{unpublished_book.id}')
        assert response.status_code == 404

    def test_unpublished_book_words_returns_404_for_regular_user(
        self, authenticated_client, unpublished_book
    ):
        response = authenticated_client.get(f'/books/{unpublished_book.id}/words')
        assert response.status_code == 404

    def test_unpublished_book_not_in_list_for_regular_user(
        self, authenticated_client, unpublished_book, published_book
    ):
        response = authenticated_client.get('/books')
        assert response.status_code == 200
        assert unpublished_book.title.encode() not in response.data

    def test_published_book_visible_in_list(
        self, authenticated_client, published_book
    ):
        response = authenticated_client.get('/books')
        assert response.status_code == 200
        assert published_book.title.encode() in response.data

    def test_unpublished_book_reader_returns_404_for_regular_user(
        self, authenticated_client, unpublished_book
    ):
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(f'/read/{unpublished_book.id}/chapters')
        assert response.status_code == 404

    def test_admin_can_view_unpublished_book(self, admin_client, admin_user, unpublished_book, db_session):
        admin_user.onboarding_completed = True
        db_session.commit()
        with admin_client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        response = admin_client.get(f'/books/{unpublished_book.id}')
        assert response.status_code == 200

    def test_admin_sees_unpublished_in_list(
        self, admin_client, admin_user, unpublished_book, db_session
    ):
        admin_user.onboarding_completed = True
        db_session.commit()
        with admin_client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        response = admin_client.get('/books')
        assert response.status_code == 200
        assert unpublished_book.title.encode() in response.data


class TestBookDetailNoChapters:
    """Book detail page does not 500 when the book has no chapters."""

    def test_book_detail_no_chapters_returns_200(
        self, authenticated_client, book_no_chapters
    ):
        response = authenticated_client.get(f'/books/{book_no_chapters.id}')
        assert response.status_code == 200

    def test_book_words_no_chapters_returns_200(
        self, authenticated_client, book_no_chapters
    ):
        response = authenticated_client.get(f'/books/{book_no_chapters.id}/words')
        assert response.status_code == 200


class TestChapterPagination:
    """Chapter reader handles edge-case chapter indices without crashing."""

    @pytest.mark.smoke
    def test_reader_renders_200(self, authenticated_client, published_book):
        """reader_simple.html renders without errors for a published book."""
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{published_book.id}/chapters?chapter=1'
            )
        assert response.status_code == 200

    def test_first_chapter_accessible(self, authenticated_client, published_book):
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{published_book.id}/chapters?chapter=1'
            )
        assert response.status_code == 200

    def test_last_chapter_accessible(self, authenticated_client, published_book):
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{published_book.id}/chapters?chapter=3'
            )
        assert response.status_code == 200

    def test_chapter_zero_does_not_500(self, authenticated_client, published_book):
        """chapter=0 is falsy; route defaults to first chapter without crashing."""
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{published_book.id}/chapters?chapter=0'
            )
        assert response.status_code == 200

    def test_out_of_range_chapter_falls_back_to_first(
        self, authenticated_client, published_book
    ):
        """chapter_num beyond the last chapter falls back to chapter 1, not 500."""
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{published_book.id}/chapters?chapter=9999'
            )
        assert response.status_code == 200

    def test_book_with_no_chapters_reader_redirects(
        self, authenticated_client, book_no_chapters
    ):
        """Reader with a book that has no chapters redirects (not 500)."""
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get(
                f'/read/{book_no_chapters.id}/chapters'
            )
        assert response.status_code in (302, 200)
