"""Integration tests for Topics & Collections API endpoints"""
import pytest
from datetime import datetime, UTC


@pytest.fixture
def api_headers(test_user):
    """Create API authorization headers"""
    # For API login, we'll use authenticated_client instead
    # This is a placeholder - tests will use authenticated_client directly
    return {
        'Authorization': f'Bearer test_token',
        'Content-Type': 'application/json',
        'user_id': test_user.id
    }


@pytest.fixture
def test_topic(db_session, test_user):
    """Create test topic"""
    from app.words.models import Topic
    from datetime import datetime, UTC
    import uuid

    # Create unique name to avoid conflicts
    unique_suffix = uuid.uuid4().hex[:8]
    topic = Topic(
        name=f'Test Topic {unique_suffix}',
        description='Test topic description',
        created_by=test_user.id
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def test_collection(db_session, test_user):
    """Create test collection"""
    from app.words.models import Collection
    from datetime import datetime, UTC
    import uuid

    # Create unique name to avoid conflicts
    unique_suffix = uuid.uuid4().hex[:8]
    collection = Collection(
        name=f'Test Collection {unique_suffix}',
        description='Test collection description',
        created_by=test_user.id,
        created_at=datetime.now(UTC)
    )
    db_session.add(collection)
    db_session.commit()
    return collection


@pytest.fixture
def test_words(db_session, test_user):
    """Create test words"""
    from app.words.models import CollectionWords

    words = []
    for i in range(5):
        word = CollectionWords(
            english_word=f'testword{i}_{test_user.id}',  # Make unique per user
            russian_word=f'слово{i}',
            level='A1'
        )
        db_session.add(word)
        words.append(word)

    db_session.commit()
    return words


@pytest.fixture
def topic_with_words(db_session, test_topic, test_words):
    """Link words to topic"""
    from app.words.models import TopicWord

    for word in test_words:
        topic_word = TopicWord(
            topic_id=test_topic.id,
            word_id=word.id
        )
        db_session.add(topic_word)

    db_session.commit()
    return test_topic


@pytest.fixture
def collection_with_words(db_session, test_collection, test_words):
    """Link words to collection"""
    from app.words.models import CollectionWordLink

    for word in test_words:
        link = CollectionWordLink(
            collection_id=test_collection.id,
            word_id=word.id
        )
        db_session.add(link)

    db_session.commit()
    return test_collection


class TestGetTopics:
    """Test GET /api/topics endpoint"""

    def test_get_topics_list(self, authenticated_client, topic_with_words):
        """Test getting list of topics"""
        response = authenticated_client.get('/api/topics')

        assert response.status_code == 200
        data = response.get_json()

        assert 'topics' in data
        assert 'total' in data
        assert 'page' in data
        assert data['page'] == 1
        assert len(data['topics']) > 0

        # Check topic structure
        topic = data['topics'][0]
        assert 'id' in topic
        assert 'name' in topic
        assert 'word_count' in topic
        assert topic['word_count'] == 5

    def test_get_topics_with_search(self, authenticated_client, topic_with_words):
        """Test searching topics"""
        # Search by first word of topic name
        search_term = topic_with_words.name.split()[0]
        response = authenticated_client.get(f'/api/topics?search={search_term}')

        assert response.status_code == 200
        data = response.get_json()

        assert len(data['topics']) > 0
        assert search_term in data['topics'][0]['name']

    def test_get_topics_pagination(self, authenticated_client, topic_with_words):
        """Test topics pagination"""
        response = authenticated_client.get('/api/topics?page=1&per_page=2')

        assert response.status_code == 200
        data = response.get_json()

        assert data['per_page'] == 2
        assert 'total_pages' in data

    def test_get_topics_without_auth(self, client):
        """Test topics endpoint requires authentication"""
        response = client.get('/api/topics')

        assert response.status_code == 401


class TestGetTopic:
    """Test GET /api/topics/<id> endpoint"""

    def test_get_topic_details(self, authenticated_client, topic_with_words):
        """Test getting topic details"""
        response = authenticated_client.get(f'/api/topics/{topic_with_words.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['id'] == topic_with_words.id
        assert data['name'] == topic_with_words.name  # Use actual name
        assert data['description'] == 'Test topic description'
        assert data['word_count'] == 5
        assert 'words' in data
        assert len(data['words']) == 5
        assert 'creator' in data

    def test_get_topic_includes_words(self, authenticated_client, topic_with_words):
        """Test topic includes word list"""
        response = authenticated_client.get(f'/api/topics/{topic_with_words.id}')

        data = response.get_json()
        word = data['words'][0]

        assert 'id' in word
        assert 'english_word' in word
        assert 'russian_word' in word
        assert 'level' in word
        assert 'status' in word

    def test_get_nonexistent_topic(self, authenticated_client):
        """Test getting non-existent topic returns 404"""
        response = authenticated_client.get('/api/topics/99999')

        assert response.status_code == 404


class TestGetTopicWords:
    """Test GET /api/topics/<id>/words endpoint"""

    def test_get_topic_words(self, authenticated_client, topic_with_words):
        """Test getting topic words"""
        response = authenticated_client.get(f'/api/topics/{topic_with_words.id}/words')

        assert response.status_code == 200
        data = response.get_json()

        assert data['topic_id'] == topic_with_words.id
        assert data['topic_name'] == topic_with_words.name  # Use actual name
        assert len(data['words']) == 5
        assert data['total'] == 5

    def test_get_topic_words_pagination(self, authenticated_client, topic_with_words):
        """Test topic words pagination"""
        response = authenticated_client.get(
            f'/api/topics/{topic_with_words.id}/words?page=1&per_page=2',
        )

        assert response.status_code == 200
        data = response.get_json()

        assert len(data['words']) <= 2
        assert data['per_page'] == 2

    def test_get_words_for_nonexistent_topic(self, authenticated_client):
        """Test getting words for non-existent topic"""
        response = authenticated_client.get('/api/topics/99999/words')

        assert response.status_code == 404


class TestAddTopicToStudy:
    """Test POST /api/topics/<id>/add-to-study endpoint"""

    def test_add_topic_to_study(self, authenticated_client, topic_with_words, db_session):
        """Test adding topic words to study"""
        response = authenticated_client.post(
            f'/api/topics/{topic_with_words.id}/add-to-study',
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['topic_id'] == topic_with_words.id
        assert data['total_count'] == 5
        # added_count can be 0 if words already added in previous tests

    def test_add_topic_twice_no_duplicates(self, authenticated_client, topic_with_words, db_session):
        """Test adding same topic twice doesn't create duplicates"""
        # First addition
        response1 = authenticated_client.post(
            f'/api/topics/{topic_with_words.id}/add-to-study',
        )
        assert response1.status_code == 200
        data1 = response1.get_json()

        # Second addition
        response2 = authenticated_client.post(
            f'/api/topics/{topic_with_words.id}/add-to-study',
        )
        assert response2.status_code == 200
        data2 = response2.get_json()

        # No new words should be added on second attempt
        assert data2['added_count'] == 0

    def test_add_nonexistent_topic_to_study(self, authenticated_client):
        """Test adding non-existent topic returns 404"""
        response = authenticated_client.post('/api/topics/99999/add-to-study')

        assert response.status_code == 404


class TestGetCollections:
    """Test GET /api/collections endpoint"""

    def test_get_collections_list(self, authenticated_client, collection_with_words):
        """Test getting list of collections"""
        response = authenticated_client.get('/api/collections')

        assert response.status_code == 200
        data = response.get_json()

        assert 'collections' in data
        assert 'total' in data
        assert len(data['collections']) > 0

        collection = data['collections'][0]
        assert 'id' in collection
        assert 'name' in collection
        assert 'word_count' in collection
        assert collection['word_count'] == 5

    def test_get_collections_with_search(self, authenticated_client, collection_with_words):
        """Test searching collections"""
        response = authenticated_client.get('/api/collections?search=Test')

        assert response.status_code == 200
        data = response.get_json()

        assert len(data['collections']) > 0

    def test_get_collections_by_topic(self, authenticated_client, topic_with_words,
                                      collection_with_words, db_session):
        """Test filtering collections by topic"""
        # Link collection words to topic
        from app.words.models import TopicWord, CollectionWordLink

        word_ids = [link.word_id for link in CollectionWordLink.query.filter_by(
            collection_id=collection_with_words.id
        ).all()]

        for word_id in word_ids[:2]:  # Link first 2 words
            if not TopicWord.query.filter_by(topic_id=topic_with_words.id, word_id=word_id).first():
                topic_word = TopicWord(topic_id=topic_with_words.id, word_id=word_id)
                db_session.add(topic_word)
        db_session.commit()

        response = authenticated_client.get(
            f'/api/collections?topic_id={topic_with_words.id}',
        )

        assert response.status_code == 200
        data = response.get_json()

        # Should find collection since it shares words with topic
        assert len(data['collections']) > 0

    def test_get_collections_pagination(self, authenticated_client, collection_with_words):
        """Test collections pagination"""
        response = authenticated_client.get('/api/collections?page=1&per_page=1')

        assert response.status_code == 200
        data = response.get_json()

        assert data['per_page'] == 1
        assert 'total_pages' in data


class TestGetCollection:
    """Test GET /api/collections/<id> endpoint"""

    def test_get_collection_details(self, authenticated_client, collection_with_words):
        """Test getting collection details"""
        response = authenticated_client.get(f'/api/collections/{collection_with_words.id}')

        assert response.status_code == 200
        data = response.get_json()

        assert data['id'] == collection_with_words.id
        assert data['name'] == collection_with_words.name  # Use actual name
        assert data['description'] == 'Test collection description'
        assert data['word_count'] == 5
        assert 'words' in data
        assert len(data['words']) == 5

    def test_get_collection_includes_creator(self, authenticated_client, collection_with_words):
        """Test collection includes creator info"""
        response = authenticated_client.get(f'/api/collections/{collection_with_words.id}')

        data = response.get_json()

        assert 'creator' in data
        if data['creator']:
            assert 'id' in data['creator']
            assert 'username' in data['creator']

    def test_get_nonexistent_collection(self, authenticated_client):
        """Test getting non-existent collection returns 404"""
        response = authenticated_client.get('/api/collections/99999')

        assert response.status_code == 404


class TestGetCollectionWords:
    """Test GET /api/collections/<id>/words endpoint"""

    def test_get_collection_words(self, authenticated_client, collection_with_words):
        """Test getting collection words"""
        response = authenticated_client.get(
            f'/api/collections/{collection_with_words.id}/words',
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['collection_id'] == collection_with_words.id
        assert data['collection_name'] == collection_with_words.name  # Use actual name
        assert len(data['words']) == 5
        assert data['total'] == 5

    def test_get_collection_words_pagination(self, authenticated_client, collection_with_words):
        """Test collection words pagination"""
        response = authenticated_client.get(
            f'/api/collections/{collection_with_words.id}/words?page=1&per_page=2',
        )

        assert response.status_code == 200
        data = response.get_json()

        assert len(data['words']) <= 2
        assert data['per_page'] == 2

    def test_get_words_for_nonexistent_collection(self, authenticated_client):
        """Test getting words for non-existent collection"""
        response = authenticated_client.get('/api/collections/99999/words')

        assert response.status_code == 404


class TestAddCollectionToStudy:
    """Test POST /api/collections/<id>/add-to-study endpoint"""

    def test_add_collection_to_study(self, authenticated_client, collection_with_words, db_session):
        """Test adding collection words to study"""
        response = authenticated_client.post(
            f'/api/collections/{collection_with_words.id}/add-to-study',
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert data['collection_id'] == collection_with_words.id
        assert data['total_count'] == 5
        # added_count can be 0 if words already added in previous tests

    def test_add_nonexistent_collection_to_study(self, authenticated_client):
        """Test adding non-existent collection returns 404"""
        response = authenticated_client.post('/api/collections/99999/add-to-study')

        assert response.status_code == 404


class TestGetWordTopics:
    """Test GET /api/words/<id>/topics endpoint"""

    def test_get_word_topics(self, authenticated_client, topic_with_words, test_words):
        """Test getting topics for a word"""
        word_id = test_words[0].id

        response = authenticated_client.get(f'/api/words/{word_id}/topics')

        assert response.status_code == 200
        data = response.get_json()

        assert data['word_id'] == word_id
        assert 'english_word' in data
        assert 'topics' in data
        assert len(data['topics']) > 0

        topic = data['topics'][0]
        assert 'id' in topic
        assert 'name' in topic
        assert topic['name'] == topic_with_words.name  # Use actual name

    def test_get_topics_for_nonexistent_word(self, authenticated_client):
        """Test getting topics for non-existent word"""
        response = authenticated_client.get('/api/words/99999/topics')

        assert response.status_code == 404


class TestGetWordCollections:
    """Test GET /api/words/<id>/collections endpoint"""

    def test_get_word_collections(self, authenticated_client, collection_with_words, test_words):
        """Test getting collections for a word"""
        word_id = test_words[0].id

        response = authenticated_client.get(f'/api/words/{word_id}/collections')

        assert response.status_code == 200
        data = response.get_json()

        assert data['word_id'] == word_id
        assert 'english_word' in data
        assert 'collections' in data
        assert len(data['collections']) > 0

        collection = data['collections'][0]
        assert 'id' in collection
        assert 'name' in collection
        assert collection['name'] == collection_with_words.name  # Use actual name

    def test_get_collections_for_nonexistent_word(self, authenticated_client):
        """Test getting collections for non-existent word"""
        response = authenticated_client.get('/api/words/99999/collections')

        assert response.status_code == 404
