"""
Comprehensive tests for app/admin/routes/book_routes.py
Tests for book management routes (363 statements, currently 13% coverage)
Target: Increase to 60-70% coverage to add ~1% to overall project coverage
"""
import pytest
from unittest.mock import patch, MagicMock, mock_open
from flask import url_for


class TestBooksIndex:
    """Tests for books() - main books management page"""

    @patch('app.admin.routes.book_routes.render_template')
    @patch('app.admin.routes.book_routes.db.session')
    @patch('app.admin.routes.book_routes.Book')
    def test_books_index_success(self, mock_book, mock_session, mock_render, admin_client, mock_admin_user):
        """Test successful books index page load"""
        # Setup mock Book model with proper attribute support
        mock_book.query.count.return_value = 100

        # Mock words_total attribute for filter operations
        mock_words_total = MagicMock()
        mock_words_total.isnot.return_value = MagicMock()
        mock_words_total.__gt__ = MagicMock(return_value=MagicMock())  # Support > operator
        mock_words_total.desc.return_value = MagicMock()
        mock_book.words_total = mock_words_total

        # Mock filter chains
        mock_filter = MagicMock()
        mock_filter.count.return_value = 80
        mock_filter.order_by.return_value.limit.return_value.all.return_value = []
        mock_book.query.filter.return_value = mock_filter

        # Mock order_by chain for recent books
        mock_book.query.order_by.return_value.nullslast.return_value.limit.return_value.all.return_value = []

        # Mock db.session
        mock_session.query.return_value.scalar.return_value = 50000

        # Mock render_template to avoid caching MagicMock objects
        mock_render.return_value = '<html>books index</html>'

        # Execute
        response = admin_client.get('/admin/books')

        # Assert
        assert response.status_code == 200
        mock_render.assert_called_once()

    @patch('app.admin.routes.book_routes.Book')
    def test_books_index_error(self, mock_book, admin_client, mock_admin_user):
        """Test books index with database error"""
        mock_book.query.count.side_effect = Exception("Database error")

        response = admin_client.get('/admin/books', follow_redirects=False)

        assert response.status_code == 302  # Redirects to dashboard

    def test_books_index_requires_admin(self, client):
        """Test that books index requires admin authentication"""
        response = client.get('/admin/books')
        assert response.status_code == 302


class TestScrapeWebsite:
    """Tests for scrape_website() POST endpoint"""

    @patch('app.web.scraper.WebScraper')
    def test_scrape_website_success(self, mock_scraper_class, admin_client, mock_admin_user):
        """Test successful website scraping"""
        # Setup mock scraper instance
        mock_scraper = MagicMock()
        mock_scraper.scrape_website.return_value = [
            {'title': 'Book 1', 'author': 'Author 1'},
            {'title': 'Book 2', 'author': 'Author 2'}
        ]
        mock_scraper_class.return_value = mock_scraper

        response = admin_client.post(
            '/admin/books/scrape-website',
            json={'url': 'https://example.com', 'max_pages': 10}
        )

        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['scraped_count'] == 2

    def test_scrape_website_no_url(self, admin_client, mock_admin_user):
        """Test scraping without URL"""
        response = admin_client.post(
            '/admin/books/scrape-website',
            json={}
        )

        assert response.status_code == 400
        json_data = response.get_json()
        assert json_data['success'] is False

    @patch('app.web.scraper.WebScraper')
    def test_scrape_website_error(self, mock_scraper_class, admin_client, mock_admin_user):
        """Test scraping with error"""
        mock_scraper_class.side_effect = Exception("Scraping failed")

        response = admin_client.post(
            '/admin/books/scrape-website',
            json={'url': 'https://example.com'}
        )

        assert response.status_code == 500

    def test_scrape_website_requires_admin(self, client):
        """Test that scraping requires admin authentication"""
        response = client.post('/admin/books/scrape-website', json={'url': 'test'})
        assert response.status_code == 302


class TestUpdateBookStatistics:
    """Tests for update_book_statistics() POST endpoint"""

    @patch('app.repository.DatabaseRepository')
    @patch('app.admin.routes.book_routes.Book')
    def test_update_statistics_success(self, mock_book, mock_repo_class, admin_client, mock_admin_user):
        """Test successful statistics update"""
        # Setup mock books
        mock_book_obj = MagicMock()
        mock_book_obj.id = 1
        mock_book.query.all.return_value = [mock_book_obj]

        # Setup mock repository
        mock_repo = MagicMock()
        mock_repo.execute_query.return_value = [[100]]  # Mock word count result
        mock_repo_class.return_value = mock_repo

        response = admin_client.post('/admin/books/update-statistics', json={})

        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['updated_count'] >= 0

    @patch('app.admin.routes.book_routes.Book')
    def test_update_statistics_error(self, mock_book, admin_client, mock_admin_user):
        """Test statistics update with error - DatabaseRepository error is caught per-book"""
        # Setup mock to raise exception when querying books (outer try-except)
        mock_book.query.all.side_effect = Exception("Database query failed")

        response = admin_client.post('/admin/books/update-statistics', json={})

        # Should return 500 when outer exception occurs
        assert response.status_code == 500

    def test_update_statistics_requires_admin(self, client):
        """Test that update statistics requires admin authentication"""
        response = client.post('/admin/books/update-statistics')
        assert response.status_code == 302


class TestProcessPhrasalVerbs:
    """Tests for process_phrasal_verbs() POST endpoint"""

    @patch('app.admin.routes.book_routes.db.session')
    @patch('app.words.models.PhrasalVerb')
    @patch('app.words.models.CollectionWords')
    def test_process_phrasal_verbs_success(self, mock_words_class, mock_phrasal_class, mock_session, admin_client, mock_admin_user):
        """Test successful phrasal verbs processing with text input"""
        # Setup mock base word
        mock_word = MagicMock()
        mock_word.id = 1
        mock_words_class.query.filter_by.return_value.first.return_value = mock_word

        # Setup mock phrasal verb (doesn't exist yet)
        mock_phrasal_class.query.filter_by.return_value.first.return_value = None

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
    @patch('app.admin.routes.book_routes.PhrasalVerb')
    @patch('app.admin.routes.book_routes.db.session')
    @patch('app.admin.routes.book_routes.Book')
    def test_book_statistics_success(self, mock_book, mock_session, mock_phrasal, mock_get_stats, mock_render, admin_client, mock_admin_user):
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

        # Mock phrasal verb query
        mock_phrasal_result = MagicMock()
        mock_phrasal.id = MagicMock()
        mock_phrasal.get_download = MagicMock()

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

    @patch('app.admin.routes.book_routes.render_template')
    @patch('app.admin.routes.book_routes.Book')
    @patch('app.admin.routes.book_routes.db.session')
    def test_cleanup_books_get(self, mock_session, mock_book, mock_render, admin_client, mock_admin_user):
        """Test GET cleanup books page"""
        # Mock database query results with regular int values (not MagicMock)
        mock_session.execute.return_value.scalar.side_effect = [10, 5]

        # Mock Book count
        mock_book.query.count.return_value = 100

        # Mock render_template to return a simple response (avoids caching issues)
        mock_render.return_value = '<html>cleanup page</html>'

        response = admin_client.get('/admin/books/cleanup')

        assert response.status_code == 200
        # Verify render_template was called with correct stats
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][0] == 'admin/books/cleanup.html'
        assert 'stats' in call_args[1]

    @patch('app.admin.routes.book_routes.Book')
    @patch('app.admin.routes.book_routes.db.session')
    def test_cleanup_books_post_success(self, mock_session, mock_book, admin_client, mock_admin_user):
        """Test POST cleanup books - delete orphaned books"""
        mock_book_obj = MagicMock()
        mock_book_obj.id = 1
        mock_book_obj.file_path = None

        mock_book.query.filter.return_value.all.return_value = [mock_book_obj]

        response = admin_client.post('/admin/books/cleanup', follow_redirects=False)

        assert response.status_code == 302
        assert response.location.endswith('/admin/books/cleanup')

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

    @patch('app.books.parsers.process_uploaded_book')
    @patch('werkzeug.utils.secure_filename')
    def test_add_book_post_success(self, mock_secure, mock_process, admin_client, mock_admin_user, tmp_path):
        """Test POST add book with text content"""
        mock_secure.return_value = 'test_book.txt'
        mock_process.return_value = {
            'content': '<p>Test content</p>',
            'word_count': 100,
            'unique_words': 50
        }

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("This is test content for the book")

        with open(test_file, 'rb') as f:
            data = {
                'title': 'Test Book',
                'author': 'Test Author',
                'level': 'A1',
                'file': (f, 'test.txt'),
                'format_type': 'text'
            }

            response = admin_client.post(
                '/admin/books/add',
                data=data,
                follow_redirects=False,
                content_type='multipart/form-data'
            )

            # Should redirect after successful add
            assert response.status_code in [200, 302]

    def test_add_book_requires_admin(self, client):
        """Test that add book requires admin authentication"""
        response = client.get('/admin/books/add')
        assert response.status_code == 302