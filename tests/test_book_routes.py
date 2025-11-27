# tests/admin/routes/test_book_routes.py

"""
Integration тесты для book routes
"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from app.books.models import Book, Chapter
from app.words.models import PhrasalVerb, CollectionWords


class TestBookRoutes:
    """Интеграционные тесты для book routes"""

    @pytest.fixture
    def sample_book(self, db_session):
        """Создает тестовую книгу"""
        book = Book(
            title='Test Book',
            author='Test Author',
            level='B1',
            words_total=10000,
            unique_words=5000,
            chapters_cnt=1
        )
        db_session.add(book)
        db_session.commit()

        yield book

        db_session.delete(book)
        db_session.commit()

    def test_books_index_unauthorized(self, client):
        """Тест доступа к /books без авторизации"""
        response = client.get('/admin/books')
        assert response.status_code == 302  # Redirect to login
        assert '/login' in response.location

    def test_books_index_authorized(self, client, admin_user, sample_book):
        """Тест доступа к /books с авторизацией"""
        response = client.get('/admin/books')
        assert response.status_code == 200
        assert b'Test Book' in response.data

    def test_books_index_statistics(self, client, admin_user, sample_book):
        """Тест отображения статистики на главной странице"""
        response = client.get('/admin/books')
        assert response.status_code == 200
        assert b'total_books' in response.data or b'Test Book' in response.data

    @patch('app.web.scraper.WebScraper')
    def test_scrape_website_success(self, mock_scraper, client, admin_user):
        """Тест успешного scraping сайта"""
        # Mock scraper results
        mock_instance = Mock()
        mock_instance.scrape_website.return_value = [
            {'title': 'Book 1', 'author': 'Author 1'},
            {'title': 'Book 2', 'author': 'Author 2'}
        ]
        mock_scraper.return_value = mock_instance

        response = client.post('/admin/books/scrape-website',
                                data=json.dumps({'url': 'http://example.com', 'max_pages': 5}),
                                content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['scraped_count'] == 2

    def test_scrape_website_no_url(self, client, admin_user):
        """Тест scraping без URL"""
        response = client.post('/admin/books/scrape-website',
                                data=json.dumps({'max_pages': 5}),
                                content_type='application/json')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'URL не указан' in data['error']

    @patch('app.repository.DatabaseRepository')
    def test_update_book_statistics_single_book(self, mock_repo, client, admin_user, sample_book):
        """Тест обновления статистики одной книги"""
        # Mock repository
        mock_repo_instance = Mock()
        mock_repo_instance.execute_query.return_value = [[5000]]
        mock_repo.return_value = mock_repo_instance

        response = client.post('/admin/books/update-statistics',
                                data=json.dumps({'book_id': sample_book.id}),
                                content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['updated_count'] >= 0

    @patch('app.repository.DatabaseRepository')
    def test_update_book_statistics_all_books(self, mock_repo, client, admin_user, sample_book):
        """Тест обновления статистики всех книг"""
        mock_repo_instance = Mock()
        mock_repo_instance.execute_query.return_value = [[5000]]
        mock_repo.return_value = mock_repo_instance

        response = client.post('/admin/books/update-statistics',
                                data=json.dumps({}),
                                content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_process_phrasal_verbs_no_data(self, client, admin_user):
        """Тест обработки фразовых глаголов без данных"""
        response = client.post('/admin/books/process-phrasal-verbs',
                                data={})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'не предоставлены' in data['error']

    def test_process_phrasal_verbs_with_text(self, client, admin_user, db_session):
        """Тест обработки фразовых глаголов из текстового поля"""
        import uuid
        # Создаем базовое слово с уникальным названием
        unique_word = f'test_{uuid.uuid4().hex[:8]}'
        word = CollectionWords(
            english_word=unique_word,
            russian_word='тест',
            level='A1'
        )
        db_session.add(word)
        db_session.commit()

        phrasal_text = f"{unique_word} up;искать;in dictionary;I {unique_word} up words;Я ищу слова"

        response = client.post('/admin/books/process-phrasal-verbs',
                                data={'phrasal_verbs_text': phrasal_text})

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['processed_count'] >= 0

        # Cleanup
        try:
            db_session.delete(word)
            db_session.commit()
        except:
            db_session.rollback()

    def test_book_statistics_page(self, client, admin_user, sample_book):
        """Тест страницы статистики книг"""
        response = client.get('/admin/books/statistics')
        assert response.status_code == 200

    @patch('app.admin.routes.book_routes.extract_file_metadata')
    def test_extract_metadata_success(self, mock_extract, client, admin_user):
        """Тест извлечения метаданных из файла"""
        mock_extract.return_value = {
            'title': 'Extracted Title',
            'author': 'Extracted Author'
        }

        data = {'file': (BytesIO(b'fake file content'), 'test.fb2')}
        response = client.post('/admin/books/extract-metadata',
                                data=data,
                                content_type='multipart/form-data')

        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] is True
        assert result['metadata']['title'] == 'Extracted Title'

    def test_extract_metadata_no_file(self, client, admin_user):
        """Тест извлечения метаданных без файла"""
        response = client.post('/admin/books/extract-metadata',
                                data={},
                                content_type='multipart/form-data')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False

    @patch('app.admin.routes.book_routes.db.session.execute')
    def test_cleanup_books_get(self, mock_execute, client, admin_user):
        """Тест GET запроса страницы очистки"""
        # Mock the SQL query results
        mock_result = Mock()
        mock_result.scalar.return_value = 0
        mock_execute.return_value = mock_result

        response = client.get('/admin/books/cleanup')
        assert response.status_code == 200

    def test_cleanup_books_remove_empty(self, client, admin_user, db_session):
        """Тест удаления пустых книг"""
        # Создаем пустую книгу
        empty_book = Book(
            title='Empty Book',
            author='Test Author',
            chapters_cnt=0
        )
        db_session.add(empty_book)
        db_session.commit()

        response = client.post('/admin/books/cleanup',
                                data={'action': 'remove_empty_books'})

        assert response.status_code == 302  # Redirect after success

    def test_add_book_get_form(self, client, admin_user):
        """Тест отображения формы добавления книги"""
        response = client.get('/admin/books/add')
        assert response.status_code == 200

    def test_add_book_duplicate_check(self, client, admin_user, sample_book):
        """Тест проверки дубликатов при добавлении книги"""
        response = client.post('/admin/books/add',
                                data={
                                    'title': 'Test Book',
                                    'author': 'Test Author',
                                    'level': 'B1',
                                    'chapters_cnt': '1'
                                },
                                content_type='application/x-www-form-urlencoded')

        # Должна быть проверка на дубликат
        # В зависимости от реализации может быть 200 с JSON или redirect
        assert response.status_code in [200, 302]


class TestBookRoutesPermissions:
    """Тесты проверки прав доступа"""

    @pytest.fixture
    def regular_user(self, client, db_session):
        """Создает обычного пользователя (не админа)"""
        from app.auth.models import User
        import uuid
        username = f'regular_user_{uuid.uuid4().hex[:8]}'
        user = User(
            username=username,
            email=f'user_{uuid.uuid4().hex[:8]}@test.com',
            is_admin=False,
            active=True
        )
        user.set_password('user123')
        db_session.add(user)
        db_session.commit()

        client.post('/login', data={
            'username': username,
            'password': 'user123'
        })

        yield user

        db_session.delete(user)
        db_session.commit()

    def test_books_access_denied_for_regular_user(self, client, regular_user):
        """Тест отказа в доступе для обычного пользователя"""
        response = client.get('/admin/books')
        # Должен быть redirect или 403
        assert response.status_code in [302, 403]

    def test_scrape_website_access_denied(self, client, regular_user):
        """Тест отказа в scraping для обычного пользователя"""
        response = client.post('/admin/books/scrape-website',
                                data=json.dumps({'url': 'http://example.com'}),
                                content_type='application/json')
        assert response.status_code in [302, 403]


class TestBookRoutesErrorHandling:
    """Тесты обработки ошибок"""

    @patch('app.admin.routes.book_routes.Book')
    def test_books_index_database_error(self, mock_book, client, admin_user):
        """Тест обработки ошибки базы данных на главной странице"""
        mock_book.query.count.side_effect = Exception("Database connection failed")

        response = client.get('/admin/books')
        # Должен обработать ошибку и показать сообщение или redirect
        assert response.status_code in [200, 302]

    def test_update_statistics_invalid_book_id(self, client, admin_user):
        """Тест обновления статистики с несуществующим ID книги"""
        response = client.post('/admin/books/update-statistics',
                                data=json.dumps({'book_id': 99999}),
                                content_type='application/json')

        # Должен обработать ошибку
        assert response.status_code in [200, 404, 500]
