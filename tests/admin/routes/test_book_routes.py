"""
Comprehensive tests for app/admin/routes/book_routes.py
Tests for book management routes (363 statements, currently 13% coverage)
Target: Increase to 60-70% coverage to add ~1% to overall project coverage
"""
import io
import os
import pytest
from unittest.mock import patch, MagicMock, mock_open
from flask import url_for
from werkzeug.datastructures import FileStorage

from app.admin.services.book_processing_service import (
    ALLOWED_BOOK_EXTENSIONS,
    BookUploadError,
    save_uploaded_book_file,
)


class TestBooksIndex:
    """Tests for books() - main books management page"""

    @pytest.mark.smoke
    def test_books_index_success(self, admin_client, mock_admin_user):
        response = admin_client.get('/admin/books')
        assert response.status_code == 200
        assert b'books-query' in response.data

    def test_books_index_requires_admin(self, client):
        """Test that books index requires admin authentication"""
        response = client.get('/admin/books')
        assert response.status_code == 302


class TestScrapeWebsite:
    """Tests for scrape_website() POST endpoint"""

    def test_legacy_scrape_points_at_working_file_import(self, admin_client, mock_admin_user):
        response = admin_client.post('/admin/books/scrape-website', json={'url': 'https://example.invalid'})
        assert response.status_code == 410
        assert response.get_json()['upload_url'] == '/admin/books/add'
        assert admin_client.get(response.get_json()['upload_url']).status_code == 200

    def test_scrape_website_requires_admin(self, client):
        """Test that scraping requires admin authentication"""
        response = client.post('/admin/books/scrape-website', json={'url': 'test'})
        assert response.status_code == 302


class TestUpdateBookStatistics:
    """Tests for update_book_statistics() POST endpoint"""

    def test_update_statistics_corrects_chapters_without_changing_date(
        self, admin_client, db_session, mock_admin_user,
    ):
        from datetime import datetime

        from app.books.models import Book, Chapter

        legacy_date = datetime(2020, 1, 1)
        book = Book(title='Statistics fixture', author='Test', chapters_cnt=70, created_at=legacy_date)
        book.chapters.append(Chapter(chap_num=1, title='Chapter', text_raw='A story.', words=2))
        db_session.add(book)
        db_session.commit()

        response = admin_client.post('/admin/books/update-statistics', json={'book_id': book.id})
        assert response.status_code == 200
        assert response.get_json()['updated_count'] == 1
        db_session.refresh(book)
        assert book.chapters_cnt == 1
        assert book.created_at.replace(tzinfo=None) == legacy_date

    def test_update_statistics_error(self, admin_client, mock_admin_user):
        response = admin_client.post('/admin/books/update-statistics', json={'book_id': []})
        assert response.status_code == 400
        assert response.get_json()['success'] is False

    def test_update_statistics_requires_admin(self, client):
        """Test that update statistics requires admin authentication"""
        response = client.post('/admin/books/update-statistics')
        assert response.status_code == 302


class TestProcessPhrasalVerbs:
    """Tests for process_phrasal_verbs() POST endpoint"""

    @patch('app.admin.routes.book_routes.db.session')
    @patch('app.admin.routes.book_routes.CollectionWords')
    def test_process_phrasal_verbs_success(self, mock_words_class, mock_session, admin_client, mock_admin_user):
        """Test successful phrasal verbs processing with text input"""
        # Setup mock base word
        mock_word = MagicMock()
        mock_word.id = 1

        # First call returns base word, second call returns None (phrasal verb doesn't exist)
        mock_words_class.query.filter_by.return_value.first.side_effect = [mock_word, None]

        phrasal_data = "look up;искать;in dictionary;I look up words;Я ищу слова"
        response = admin_client.post(
            '/admin/books/process-phrasal-verbs',
            data={'phrasal_verbs_text': phrasal_data}
        )

        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert 'processed_count' in json_data

    def test_process_phrasal_verbs_no_data(self, admin_client, mock_admin_user):
        """Test phrasal verbs processing without data"""
        response = admin_client.post('/admin/books/process-phrasal-verbs', data={})

        assert response.status_code == 400
        json_data = response.get_json()
        assert json_data['success'] is False

    def test_process_phrasal_verbs_requires_admin(self, client):
        """Test that process phrasal verbs requires admin authentication"""
        response = client.post('/admin/books/process-phrasal-verbs')
        assert response.status_code == 302


class TestBookStatistics:
    """Tests for book_statistics() GET endpoint"""

    @patch('app.admin.routes.book_routes.render_template')
    @patch('app.admin.routes.book_routes.BookProcessingService.get_book_statistics')
    @patch('app.admin.routes.book_routes.CollectionWords')
    @patch('app.admin.routes.book_routes.db.session')
    @patch('app.admin.routes.book_routes.Book')
    def test_book_statistics_success(self, mock_book, mock_session, mock_collection_words, mock_get_stats, mock_render, admin_client, mock_admin_user):
        """Test successful book statistics retrieval"""
        # Mock BookProcessingService response
        mock_get_stats.return_value = {
            'total_books': 100,
            'books_with_stats': 80,
            'total_words': 50000
        }

        # Mock Book queries - Mock words_total AND unique_words attributes properly
        mock_words_total = MagicMock()
        mock_words_total.isnot = MagicMock(return_value=MagicMock())
        mock_words_total.__gt__ = MagicMock(return_value=MagicMock())
        mock_words_total.desc = MagicMock(return_value=MagicMock())
        mock_book.words_total = mock_words_total

        mock_unique_words = MagicMock()
        mock_unique_words.isnot = MagicMock(return_value=MagicMock())
        mock_unique_words.__gt__ = MagicMock(return_value=MagicMock())
        mock_unique_words.desc = MagicMock(return_value=MagicMock())
        mock_book.unique_words = mock_unique_words

        # Mock query chains to return empty lists
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_book.query = mock_query

        # Mock db.session queries
        mock_result = MagicMock()
        mock_result.total_books = 100
        mock_result.words_total = 50000
        mock_result.unique_words = 10000
        mock_result.avg_words = 500
        mock_result.avg_unique = 100
        mock_session.query.return_value.first.return_value = mock_result

        # Mock phrasal verb query (now uses CollectionWords)
        mock_collection_words.id = MagicMock()
        mock_collection_words.get_download = MagicMock()
        mock_collection_words.item_type = MagicMock()

        # Mock render_template to avoid caching
        mock_render.return_value = '<html>statistics</html>'

        response = admin_client.get('/admin/books/statistics')

        assert response.status_code == 200
        mock_render.assert_called_once()

    @patch('app.admin.routes.book_routes.url_for')
    @patch('app.admin.routes.book_routes.BookProcessingService.get_book_statistics')
    def test_book_statistics_error(self, mock_get_stats, mock_url_for, admin_client, mock_admin_user):
        """Test book statistics with service error"""
        mock_get_stats.return_value = {'error': 'Stats error'}
        mock_url_for.return_value = '/admin/books'

        response = admin_client.get('/admin/books/statistics', follow_redirects=False)

        assert response.status_code == 302

    def test_book_statistics_requires_admin(self, client):
        """Test that book statistics requires admin authentication"""
        response = client.get('/admin/books/statistics')
        assert response.status_code == 302


class TestExtractBookMetadata:
    """Tests for extract_book_metadata() POST endpoint"""

    @patch('os.remove')
    @patch('os.makedirs')
    @patch('app.admin.routes.book_routes.extract_file_metadata')
    def test_extract_metadata_success(self, mock_extract, mock_makedirs, mock_remove, admin_client, mock_admin_user, tmp_path):
        """Test successful metadata extraction from uploaded file"""
        mock_extract.return_value = {
            'title': 'Test Book',
            'author': 'Test Author',
            'language': 'en'
        }

        # Create a test file
        test_file = tmp_path / "test_book.epub"
        test_file.write_bytes(b"fake epub content")

        with open(test_file, 'rb') as f:
            response = admin_client.post(
                '/admin/books/extract-metadata',
                data={'file': (f, 'test_book.epub')},
                content_type='multipart/form-data'
            )

        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['metadata']['title'] == 'Test Book'

    def test_extract_metadata_no_file(self, admin_client, mock_admin_user):
        """Test metadata extraction without file"""
        response = admin_client.post(
            '/admin/books/extract-metadata',
            data={},
            content_type='multipart/form-data'
        )

        assert response.status_code == 400
        json_data = response.get_json()
        assert json_data['success'] is False

    @patch('app.admin.routes.book_routes.extract_file_metadata')
    def test_extract_metadata_error(self, mock_extract, admin_client, mock_admin_user, tmp_path):
        """Test metadata extraction with processing error"""
        mock_extract.side_effect = Exception("Extraction failed")

        test_file = tmp_path / "bad_book.epub"
        test_file.write_bytes(b"corrupt data")

        with open(test_file, 'rb') as f:
            response = admin_client.post(
                '/admin/books/extract-metadata',
                data={'file': (f, 'bad_book.epub')},
                content_type='multipart/form-data'
            )

        assert response.status_code == 500

    def test_extract_metadata_requires_admin(self, client, tmp_path):
        """Test that extract metadata requires admin authentication"""
        test_file = tmp_path / "test.epub"
        test_file.write_bytes(b"test")

        with open(test_file, 'rb') as f:
            response = client.post(
                '/admin/books/extract-metadata',
                data={'file': (f, 'test.epub')},
                content_type='multipart/form-data'
            )
        assert response.status_code == 302


class TestCleanupBooks:
    """Tests for cleanup_books() GET/POST endpoint"""

    def test_cleanup_books_get(self, admin_client, mock_admin_user):
        response = admin_client.get('/admin/books/cleanup')
        assert response.status_code == 200
        assert b'text=missing' in response.data

    def test_cleanup_books_old_bulk_action_leaves_book(self, admin_client, db_session, mock_admin_user):
        from app.books.models import Book

        book = Book(title='Empty cleanup fixture', author='Test', chapters_cnt=0)
        db_session.add(book)
        db_session.commit()
        response = admin_client.post('/admin/books/cleanup', data={'action': 'remove_empty_books'})
        assert response.status_code == 303
        assert db_session.get(Book, book.id) is not None

    def test_cleanup_books_requires_admin(self, client):
        """Test that cleanup books requires admin authentication"""
        response = client.get('/admin/books/cleanup')
        assert response.status_code == 302


class TestAddBook:
    """Tests for add_book() GET/POST endpoint"""

    def test_add_book_get(self, admin_client, mock_admin_user):
        """Test GET add book form"""
        response = admin_client.get('/admin/books/add')

        assert response.status_code == 200

    def test_add_book_persists_an_unmarked_text_file(self, admin_client, db_session, mock_admin_user, monkeypatch):
        from app.admin.services.book_processing_service import BookProcessingService
        from app.books.models import Book

        monkeypatch.setattr(BookProcessingService, 'start_background_chapter_processing', MagicMock())
        response = admin_client.post('/admin/books/add', data={
            'title': 'Plain book', 'author': 'Test Author', 'level': 'A1',
            'file': (io.BytesIO(b'A book starts here.\n\nIt ends here.'), 'story.txt'),
        })
        assert response.status_code == 303
        book = db_session.query(Book).filter_by(title='Plain book').one()
        assert response.location.endswith(f'/books/{book.id}/chapters')
        assert not book.is_published
        assert book.chapters[0].text_raw == 'A book starts here.\n\nIt ends here.'

    def test_add_book_requires_admin(self, client):
        """Test that add book requires admin authentication"""
        response = client.get('/admin/books/add')
        assert response.status_code == 302


class TestSaveUploadedBookFile:
    """Direct tests for the safe-upload helper in book_processing_service."""

    def _file_storage(self, name: str, payload: bytes) -> FileStorage:
        return FileStorage(stream=io.BytesIO(payload), filename=name)

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(BookUploadError):
            save_uploaded_book_file(None, temp_dir=str(tmp_path))

    def test_rejects_empty_filename(self, tmp_path):
        fs = self._file_storage('', b'irrelevant')
        with pytest.raises(BookUploadError):
            save_uploaded_book_file(fs, temp_dir=str(tmp_path))

    def test_rejects_disallowed_extension(self, tmp_path):
        fs = self._file_storage('malicious.exe', b'MZ\x90\x00binary')
        with pytest.raises(BookUploadError) as exc:
            save_uploaded_book_file(fs, temp_dir=str(tmp_path))
        assert '.exe' in str(exc.value) or 'exe' in str(exc.value)

    def test_rejects_oversize_file(self, tmp_path):
        fs = self._file_storage('book.txt', b'x' * 1024)
        with pytest.raises(BookUploadError) as exc:
            save_uploaded_book_file(fs, temp_dir=str(tmp_path), max_size_bytes=10)
        assert 'превышает' in str(exc.value).lower() or 'мб' in str(exc.value).lower()

    def test_rejects_empty_content(self, tmp_path):
        fs = self._file_storage('book.txt', b'')
        with pytest.raises(BookUploadError):
            save_uploaded_book_file(fs, temp_dir=str(tmp_path))

    def test_path_traversal_filename_sanitised(self, tmp_path):
        """secure_filename strips traversal segments; final path must be inside temp_dir."""
        fs = self._file_storage('../../../etc/passwd.txt', b'hello world')
        saved_path, safe_name, ext = save_uploaded_book_file(fs, temp_dir=str(tmp_path))
        assert ext == '.txt'
        # The saved file resolves inside the requested temp dir.
        assert os.path.realpath(saved_path).startswith(os.path.realpath(str(tmp_path)))
        # And the saved filename contains no path separators.
        assert os.path.basename(saved_path) != safe_name
        assert os.path.splitext(saved_path)[1] == ext
        assert '..' not in safe_name and '/' not in safe_name and '\\' not in safe_name

    def test_happy_path_persists_file(self, tmp_path):
        fs = self._file_storage('chapter.fb2', b'<fb2>data</fb2>')
        saved_path, safe_name, ext = save_uploaded_book_file(fs, temp_dir=str(tmp_path))
        assert ext == '.fb2'
        assert safe_name.endswith('.fb2')
        assert os.path.exists(saved_path)
        with open(saved_path, 'rb') as fh:
            assert fh.read() == b'<fb2>data</fb2>'

    def test_allowed_extensions_constants(self):
        # Sanity: the constant exposes the canonical book formats.
        assert {'txt', 'fb2', 'epub', 'pdf', 'docx'}.issubset(ALLOWED_BOOK_EXTENSIONS)


class TestExtractMetadataUploadGuard:
    """Verify that extract_book_metadata enforces the safe-upload guard."""

    def test_extract_metadata_rejects_disallowed_extension(self, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/books/extract-metadata',
            data={'file': (io.BytesIO(b'bad'), 'evil.exe')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body['success'] is False

    def test_extract_metadata_rejects_empty_filename(self, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/books/extract-metadata',
            data={'file': (io.BytesIO(b'data'), '')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400


class TestAddBookUploadGuard:
    """Verify add_book enforces the safe-upload guard for the file field."""

    def test_add_book_rejects_disallowed_extension(self, admin_client, mock_admin_user):
        # Use JSON header so route returns JSON 400 (easier to assert on).
        response = admin_client.post(
            '/admin/books/add',
            data={
                'title': 'X',
                'author': 'Y',
                'level': 'A1',
                'format_type': 'enhanced',
                'file': (io.BytesIO(b'malicious'), 'shell.exe'),
            },
            content_type='multipart/form-data',
            headers={'Content-Type': 'multipart/form-data'},
        )
        # WTForms FileAllowed validator runs first, so request is rejected
        # before reaching our service guard — either way the upload is refused
        # and no book record / temp file is created. We assert the request did
        # not succeed (no redirect to books list).
        assert response.status_code in (200, 400)
        # The response must NOT be a 302 to /admin/books (which would mean accepted).
        if response.status_code == 302:
            assert '/admin/books' not in response.location


class TestBackgroundProcessingLaunchers:
    """Smoke-test the background-processing helpers stay daemonic and named."""

    def test_start_background_chapter_processing(self, app):
        from app.admin.services.book_processing_service import BookProcessingService

        with patch('app.books.safe_processors.safe_process_book_chapters_words') as mock_fn:
            mock_fn.return_value = {'status': 'success'}
            thread = BookProcessingService.start_background_chapter_processing(app, 42)
            thread.join(timeout=5)
            assert thread.daemon is True
            assert thread.name == 'BookChapterProcessor-42'

    def test_start_background_word_processing(self, app):
        from app.admin.services.book_processing_service import BookProcessingService

        with patch('app.books.safe_processors.safe_process_book_words') as mock_fn:
            mock_fn.return_value = {'status': 'success'}
            thread = BookProcessingService.start_background_word_processing(app, 7, '<p>x</p>')
            thread.join(timeout=5)
            assert thread.daemon is True
            assert thread.name == 'BookWordProcessor-7'


class TestEditBookChaptersCount:
    """The edit template now reads book.chapters_cnt (avoids loading chapter rows)."""

    def test_template_uses_chapters_cnt(self):
        path = os.path.join(
            os.path.dirname(__file__), '..', '..', '..',
            'app', 'templates', 'admin', 'books', 'edit.html',
        )
        with open(os.path.normpath(path), 'r', encoding='utf-8') as fh:
            tpl = fh.read()
        assert 'book.chapters_cnt' in tpl
        # Guard against regressing to the lazy-load count.
        assert 'book.chapters|length' not in tpl