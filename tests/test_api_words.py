"""Integration tests for Words API endpoints"""
import pytest
from datetime import datetime, UTC
import uuid


@pytest.fixture
def test_words(db_session, test_user):
    """Create test words"""
    from app.words.models import CollectionWords

    words = []
    for i in range(10):
        word = CollectionWords(
            english_word=f'apiword{i}_{uuid.uuid4().hex[:6]}',
            russian_word=f'апислово{i}',
            level='A2',
            sentences=f'Test sentence {i}',
            listening='test audio',
            brown=i * 10,
            get_download=i
        )
        db_session.add(word)
        words.append(word)

    db_session.commit()
    return words


@pytest.fixture
def user_words_with_status(db_session, test_user, test_words):
    """Create UserWord records with different statuses"""
    from app.study.models import UserWord

    statuses = ['new', 'learning', 'review', 'mastered']
    for i, word in enumerate(test_words[:4]):
        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.status = statuses[i]  # Override default 'new' status
        db_session.add(user_word)

    db_session.commit()
    return test_words[:4]


class TestGetWords:
    """Test GET /api/words endpoint"""

    def test_get_words_list(self, authenticated_client, test_words):
        """Test getting paginated word list"""
        response = authenticated_client.get('/api/words')

        assert response.status_code == 200
        data = response.get_json()

        assert 'words' in data
        assert 'total' in data
        assert 'page' in data
        assert 'per_page' in data
        assert 'total_pages' in data
        assert data['page'] == 1
        assert len(data['words']) > 0

    def test_get_words_with_pagination(self, authenticated_client, test_words):
        """Test pagination parameters"""
        response = authenticated_client.get('/api/words?page=1&per_page=5')

        assert response.status_code == 200
        data = response.get_json()

        assert data['per_page'] == 5
        assert len(data['words']) <= 5

    def test_get_words_by_status(self, authenticated_client, user_words_with_status):
        """Test filtering by word status"""
        # Status 1 = learning
        response = authenticated_client.get('/api/words?status=1')

        assert response.status_code == 200
        data = response.get_json()

        # Should return only learning words
        assert 'words' in data

    def test_get_words_by_letter(self, authenticated_client, test_words):
        """Test filtering by first letter"""
        first_letter = test_words[0].english_word[0]
        response = authenticated_client.get(f'/api/words?letter={first_letter}')

        assert response.status_code == 200
        data = response.get_json()

        assert 'words' in data
        for word in data['words']:
            assert word['english_word'][0].lower() == first_letter.lower()

    def test_get_words_with_search(self, authenticated_client, test_words):
        """Test search functionality"""
        search_term = test_words[0].english_word[:5]
        response = authenticated_client.get(f'/api/words?search={search_term}')

        assert response.status_code == 200
        data = response.get_json()

        assert 'words' in data

    def test_get_words_without_auth(self, client):
        """Test endpoint requires authentication"""
        response = client.get('/api/words')

        assert response.status_code == 401


class TestGetWord:
    """Test GET /api/words/<id> endpoint"""

    def test_get_word_details(self, authenticated_client, test_words):
        """Test getting single word details"""
        word_id = test_words[0].id

        response = authenticated_client.get(f'/api/words/{word_id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['id'] == word_id
        assert data['english_word'] == test_words[0].english_word
        assert data['russian_word'] == test_words[0].russian_word
        assert 'status' in data
        assert 'books' in data
        assert 'topics' in data
        assert 'collections' in data
        assert 'level' in data
        assert 'brown' in data

    def test_get_nonexistent_word(self, authenticated_client):
        """Test getting non-existent word returns 404"""
        response = authenticated_client.get('/api/words/999999')

        assert response.status_code == 404


class TestUpdateWordStatus:
    """Test POST /api/update-word-status endpoint"""

    def test_update_word_status_success(self, authenticated_client, test_words, db_session):
        """Test successfully updating word status"""
        word_id = test_words[0].id

        response = authenticated_client.post(
            '/api/update-word-status',
            json={'word_id': word_id, 'status': 1}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['status'] == 'learning'

    def test_update_word_status_missing_fields(self, authenticated_client):
        """Test error when missing required fields"""
        response = authenticated_client.post(
            '/api/update-word-status',
            json={'word_id': 1}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'error' in data

    def test_update_word_status_invalid_word(self, authenticated_client):
        """Test error when word doesn't exist"""
        response = authenticated_client.post(
            '/api/update-word-status',
            json={'word_id': 999999, 'status': 1}
        )

        assert response.status_code == 404
        data = response.get_json()

        assert data['success'] is False

    def test_update_word_status_invalid_json(self, authenticated_client):
        """Test error with invalid JSON"""
        response = authenticated_client.post(
            '/api/update-word-status',
            data='not json',
            content_type='application/json'
        )

        assert response.status_code == 400


class TestBatchUpdateStatus:
    """Test POST /api/batch-update-status endpoint"""

    def test_batch_update_success(self, authenticated_client, test_words, db_session):
        """Test successfully updating multiple word statuses"""
        word_ids = [word.id for word in test_words[:3]]

        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': word_ids, 'status': 'learning'}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['updated_count'] == 3
        assert data['total_count'] == 3

    def test_batch_update_invalid_status(self, authenticated_client, test_words):
        """Test error with invalid status"""
        word_ids = [test_words[0].id]

        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': word_ids, 'status': 'invalid_status'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'Invalid status' in data['error']

    def test_batch_update_missing_words(self, authenticated_client):
        """Test error when some words don't exist"""
        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': [999999, 999998], 'status': 'learning'}
        )

        assert response.status_code == 404
        data = response.get_json()

        assert data['success'] is False
        assert 'not found' in data['error']

    def test_batch_update_missing_fields(self, authenticated_client):
        """Test error when missing required fields"""
        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': []}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False


class TestSearchWords:
    """Test GET /api/search endpoint"""

    def test_search_words_by_english(self, client, test_words, db_session):
        """Test searching words by English text"""
        search_term = test_words[0].english_word[:6]
        response = client.get(f'/api/search?term={search_term}')

        assert response.status_code == 200
        data = response.get_json()

        assert isinstance(data, list)

    def test_search_words_by_russian(self, client, test_words):
        """Test searching words by Russian text"""
        response = client.get('/api/search?term=апислово')

        assert response.status_code == 200
        data = response.get_json()

        assert isinstance(data, list)

    def test_search_words_too_short(self, client):
        """Test search with term too short returns empty"""
        response = client.get('/api/search?term=a')

        assert response.status_code == 200
        data = response.get_json()

        assert data == []

    def test_search_words_no_term(self, client):
        """Test search with no term returns empty"""
        response = client.get('/api/search')

        assert response.status_code == 200
        data = response.get_json()

        assert data == []


class TestUpdateSingleWordStatus:
    """Test POST /api/words/<id>/status endpoint"""

    def test_update_single_word_status_success(self, authenticated_client, test_words):
        """Test successfully updating single word status"""
        word_id = test_words[0].id

        response = authenticated_client.post(
            f'/api/words/{word_id}/status',
            json={'status': 'learning'}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['status'] == 'learning'

    def test_update_single_word_status_invalid(self, authenticated_client, test_words):
        """Test error with invalid status"""
        word_id = test_words[0].id

        response = authenticated_client.post(
            f'/api/words/{word_id}/status',
            json={'status': 'invalid'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False

    def test_update_single_word_nonexistent(self, authenticated_client):
        """Test updating non-existent word"""
        response = authenticated_client.post(
            '/api/words/999999/status',
            json={'status': 'learning'}
        )

        assert response.status_code == 404

    def test_update_single_word_missing_status(self, authenticated_client, test_words):
        """Test error when missing status"""
        word_id = test_words[0].id

        response = authenticated_client.post(
            f'/api/words/{word_id}/status',
            json={}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False


class TestGetUserWordsStatus:
    """Test POST /api/user-words-status endpoint"""

    def test_get_user_words_status_success(self, authenticated_client, user_words_with_status):
        """Test getting statuses for multiple words"""
        word_ids = [word.id for word in user_words_with_status]

        response = authenticated_client.post(
            '/api/user-words-status',
            json={'word_ids': word_ids}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert 'words' in data
        assert len(data['words']) == len(word_ids)

        for word_status in data['words']:
            assert 'word_id' in word_status
            assert 'status' in word_status

    def test_get_user_words_status_empty_list(self, authenticated_client):
        """Test with empty word list"""
        response = authenticated_client.post(
            '/api/user-words-status',
            json={'word_ids': []}
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['words'] == []

    def test_get_user_words_status_invalid_json(self, authenticated_client):
        """Test error with invalid JSON"""
        response = authenticated_client.post(
            '/api/user-words-status',
            data='not json',
            content_type='application/json'
        )

        assert response.status_code == 400
