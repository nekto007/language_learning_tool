"""Integration tests for Books API endpoints"""
import pytest
import json
import uuid
from datetime import datetime, UTC


@pytest.fixture
def test_book(db_session):
    """Create a test book"""
    from app.books.models import Book

    book = Book(
        title=f'Test Book {uuid.uuid4().hex[:6]}',
        author='Test Author',
        chapters_cnt=5,
        words_total=100,
        unique_words=80,
        created_at=datetime.now(UTC)
    )
    db_session.add(book)
    db_session.commit()
    return book


@pytest.fixture
def test_chapter(db_session, test_book):
    """Create test chapter"""
    from app.books.models import Chapter

    chapter = Chapter(
        book_id=test_book.id,
        chap_num=1,
        title='Test Chapter 1',
        text_raw='Test chapter content',
        words=50
    )
    db_session.add(chapter)
    db_session.commit()
    return chapter


@pytest.fixture
def test_block(db_session, test_book):
    """Create test block"""
    from app.books.models import Block

    block = Block(
        book_id=test_book.id,
        block_num=1,
        grammar_key='test_grammar'
    )
    db_session.add(block)
    db_session.commit()
    return block


@pytest.fixture
def test_task(db_session, test_block):
    """Create test task"""
    from app.books.models import Task, TaskType

    task = Task(
        block_id=test_block.id,
        task_type=TaskType.reading_mcq,
        payload={'question': 'What is this?', 'answer': 'test'}
    )
    db_session.add(task)
    db_session.commit()
    return task


class TestGetBooks:
    """Test GET /api/books endpoint"""

    def test_get_books_list(self, authenticated_client, test_book):
        """Test getting list of all books"""
        response = authenticated_client.get('/api/books')

        assert response.status_code == 200
        data = response.get_json()

        assert 'books' in data
        assert len(data['books']) > 0
        assert any(book['title'] == test_book.title for book in data['books'])

    def test_get_books_without_auth(self, client, test_book):
        """Test endpoint requires authentication"""
        response = client.get('/api/books')

        assert response.status_code == 401


class TestGetBook:
    """Test GET /api/books/<id> endpoint"""

    def test_get_book_details(self, authenticated_client, test_book):
        """Test getting single book details"""
        response = authenticated_client.get(f'/api/books/{test_book.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['id'] == test_book.id
        assert data['title'] == test_book.title
        assert data['words_total'] == 100
        assert data['unique_words'] == 80
        assert 'word_stats' in data

    def test_get_nonexistent_book(self, authenticated_client):
        """Test getting non-existent book returns 404"""
        response = authenticated_client.get('/api/books/999999')

        assert response.status_code == 404


class TestGetChaptersByBookId:
    """Test GET /api/books/<id>/chapters endpoint"""

    def test_get_chapters_list(self, authenticated_client, test_book, test_chapter):
        """Test getting chapters for a book"""
        response = authenticated_client.get(f'/api/books/{test_book.id}/chapters')

        assert response.status_code == 200
        data = response.get_json()

        # API returns array directly, not wrapped in 'chapters' key
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]['num'] == 1
        assert data[0]['title'] == 'Test Chapter 1'

    def test_get_chapters_for_nonexistent_book(self, authenticated_client):
        """Test getting chapters for non-existent book"""
        response = authenticated_client.get('/api/books/999999/chapters')

        assert response.status_code == 404


class TestGetChapter:
    """Test GET /api/books/<id>/chapters/<num> endpoint"""

    def test_get_chapter_content(self, authenticated_client, test_book, test_chapter):
        """Test getting chapter with content"""
        response = authenticated_client.get(
            f'/api/books/{test_book.id}/chapters/{test_chapter.chap_num}'
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['id'] == test_chapter.id
        assert data['num'] == test_chapter.chap_num
        assert data['title'] == test_chapter.title
        assert 'text' in data

    def test_get_nonexistent_chapter(self, authenticated_client, test_book):
        """Test getting non-existent chapter"""
        response = authenticated_client.get(f'/api/books/{test_book.id}/chapters/999')

        assert response.status_code == 404


class TestGetChapterDetails:
    """Test GET /api/chapters/<id> endpoint"""

    def test_get_chapter_by_id(self, authenticated_client, test_chapter):
        """Test getting chapter details by ID"""
        response = authenticated_client.get(f'/api/chapters/{test_chapter.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['chapter']['id'] == test_chapter.id
        assert data['chapter']['num'] == test_chapter.chap_num

    def test_get_nonexistent_chapter_by_id(self, authenticated_client):
        """Test getting non-existent chapter by ID"""
        response = authenticated_client.get('/api/chapters/999999')

        assert response.status_code == 404


class TestGetBlock:
    """Test GET /api/blocks/<id> endpoint"""

    def test_get_block_details(self, authenticated_client, test_block):
        """Test getting block details"""
        response = authenticated_client.get(f'/api/blocks/{test_block.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['block']['id'] == test_block.id
        assert 'task_types' in data['block']

    def test_get_nonexistent_block(self, authenticated_client):
        """Test getting non-existent block"""
        response = authenticated_client.get('/api/blocks/999999')

        assert response.status_code == 404


class TestGetBlockTasks:
    """Test GET /api/blocks/<id>/tasks endpoint"""

    def test_get_block_tasks(self, authenticated_client, test_block, test_task):
        """Test getting tasks for a block"""
        response = authenticated_client.get(f'/api/blocks/{test_block.id}/tasks')

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert 'tasks' in data
        assert len(data['tasks']) > 0
        # Task type is TaskType.reading_mcq from fixture
        assert data['tasks'][0]['task_type'] == 'reading_mcq'

    def test_get_tasks_for_nonexistent_block(self, authenticated_client):
        """Test getting tasks for non-existent block"""
        response = authenticated_client.get('/api/blocks/999999/tasks')

        assert response.status_code == 404


class TestGetTask:
    """Test GET /api/tasks/<id> endpoint"""

    def test_get_task_details(self, authenticated_client, test_task):
        """Test getting task details"""
        response = authenticated_client.get(f'/api/tasks/{test_task.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['task']['id'] == test_task.id
        assert 'payload' in data['task']

    def test_get_nonexistent_task(self, authenticated_client):
        """Test getting non-existent task"""
        response = authenticated_client.get('/api/tasks/999999')

        assert response.status_code == 404


class TestGetBookProgress:
    """Test GET /api/books/<id>/progress endpoint"""

    def test_get_book_progress(self, authenticated_client, test_book, test_chapter, test_user, db_session):
        """Test getting progress for a book"""
        from app.books.models import UserChapterProgress

        # Create some progress
        progress = UserChapterProgress(
            user_id=test_user.id,
            chapter_id=test_chapter.id,
            offset_pct=0.5
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(f'/api/books/{test_book.id}/progress')

        assert response.status_code == 200
        data = response.get_json()

        # API returns chapters_read, current_chapter, offset_pct
        assert 'chapters_read' in data or 'current_chapter' in data

    def test_get_progress_for_nonexistent_book(self, authenticated_client):
        """Test getting progress for non-existent book"""
        response = authenticated_client.get('/api/books/999999/progress')

        assert response.status_code == 404


class TestUpdateProgress:
    """Test PATCH /api/progress endpoint"""

    def test_update_chapter_progress(self, authenticated_client, test_chapter, test_book, db_session):
        """Test updating chapter progress"""
        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': test_book.id,
                'chapter_id': test_chapter.id,
                'offset_pct': 0.75
            }
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['offset_pct'] == 0.75

    def test_update_progress_missing_fields(self, authenticated_client):
        """Test error when missing required fields"""
        response = authenticated_client.patch(
            '/api/progress',
            json={'chapter_id': 1}
        )

        assert response.status_code == 400

    def test_update_progress_invalid_chapter(self, authenticated_client):
        """Test error with invalid chapter ID"""
        response = authenticated_client.patch(
            '/api/progress',
            json={
                'book_id': 1,
                'chapter_id': 999999,
                'offset_pct': 0.5
            }
        )

        # API returns 404 when chapter not found
        assert response.status_code == 404


class TestAddToLearning:
    """Test POST /api/add-to-learning endpoint"""

    def test_add_word_to_learning(self, authenticated_client, db_session):
        """Test adding word to learning list"""
        from app.words.models import CollectionWords

        # Create test word
        word = CollectionWords(
            english_word=f'testword_{uuid.uuid4().hex[:6]}',
            russian_word='тестслово',
            level='A1'
        )
        db_session.add(word)
        db_session.commit()

        response = authenticated_client.post(
            '/api/add-to-learning',
            json={'word_id': word.id}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True

    def test_add_to_learning_missing_word_id(self, authenticated_client):
        """Test error when missing word_id"""
        response = authenticated_client.post(
            '/api/add-to-learning',
            json={}
        )

        assert response.status_code == 400

    def test_add_nonexistent_word_to_learning(self, authenticated_client):
        """Test adding non-existent word"""
        response = authenticated_client.post(
            '/api/add-to-learning',
            json={'word_id': 999999}
        )

        assert response.status_code == 404


class TestWordTranslation:
    """Test GET /api/word-translation/<word> endpoint"""

    def test_get_word_translation(self, authenticated_client, db_session):
        """Test getting word translation"""
        from app.words.models import CollectionWords

        # Create test word
        word = CollectionWords(
            english_word=f'unique_{uuid.uuid4().hex[:6]}',
            russian_word='уникальный',
            level='A2'
        )
        db_session.add(word)
        db_session.commit()

        response = authenticated_client.get(f'/api/word-translation/{word.english_word}')

        assert response.status_code == 200
        data = response.get_json()

        assert 'translation' in data or 'words' in data

    def test_get_translation_nonexistent_word(self, authenticated_client):
        """Test getting translation for non-existent word"""
        unique_word = f'nonexist_{uuid.uuid4().hex[:8]}'
        response = authenticated_client.get(f'/api/word-translation/{unique_word}')

        # Should return empty result or 404
        assert response.status_code in [200, 404]
