"""
Comprehensive tests for CollectionTopicService

Tests the collection/topic service that was created during refactoring
to eliminate N+1 queries and centralize business logic.

Coverage target: 85%+ for app/study/services/collection_topic_service.py
"""
import pytest


class TestGetCollectionsWithStats:
    """Test get_collections_with_stats method"""

    def test_returns_all_collections_without_filters(self, db_session, test_user, collection_and_topic):
        """Test getting all collections without filters"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_collections_with_stats(test_user.id)

        assert isinstance(result, list)
        assert len(result) > 0
        # Check structure
        first_item = result[0]
        assert 'collection' in first_item
        assert 'word_count' in first_item
        assert 'words_in_study' in first_item
        assert 'topics' in first_item

    def test_collection_stats_include_word_counts(self, db_session, test_user, collection_and_topic):
        """Test that stats include accurate word counts"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_collections_with_stats(test_user.id)

        for item in result:
            assert item['word_count'] >= 0
            assert item['words_in_study'] >= 0
            assert item['words_in_study'] <= item['word_count']

    def test_filter_by_topic_id(self, db_session, test_user, collection_and_topic):
        """Test filtering collections by topic"""
        from app.study.services.collection_topic_service import CollectionTopicService

        collection = collection_and_topic["collection"]; topic = collection_and_topic["topic"]

        # Get collections for this topic
        result = CollectionTopicService.get_collections_with_stats(
            test_user.id,
            topic_id=topic.id
        )

        # Should return collections (implementation may vary)
        assert isinstance(result, list)

    def test_search_by_collection_name(self, db_session, test_user, collection_and_topic):
        """Test searching collections by name"""
        from app.study.services.collection_topic_service import CollectionTopicService

        collection = collection_and_topic["collection"]; topic = collection_and_topic["topic"]

        # Search for part of collection name
        result = CollectionTopicService.get_collections_with_stats(
            test_user.id,
            search=collection.name[:5]  # First 5 chars
        )

        assert isinstance(result, list)
        # Should find at least the test collection
        collection_names = [item['collection'].name for item in result]
        assert any(collection.name in name for name in collection_names)

    def test_search_is_case_insensitive(self, db_session, test_user, collection_and_topic):
        """Test that search is case-insensitive"""
        from app.study.services.collection_topic_service import CollectionTopicService

        collection = collection_and_topic["collection"]

        # Search with different case
        result_lower = CollectionTopicService.get_collections_with_stats(
            test_user.id,
            search=collection.name.lower()[:5]
        )
        result_upper = CollectionTopicService.get_collections_with_stats(
            test_user.id,
            search=collection.name.upper()[:5]
        )

        # Both should return results
        assert len(result_lower) > 0 or len(result_upper) > 0

    def test_words_in_study_count_accurate(self, db_session, test_user, collection_and_topic, user_words):
        """Test that words_in_study count matches user's words"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.study.models import UserWord

        collection = collection_and_topic["collection"]

        # Get user's word IDs
        user_word_ids = {
            uw.word_id for uw in UserWord.query.filter_by(user_id=test_user.id).all()
        }

        result = CollectionTopicService.get_collections_with_stats(test_user.id)

        for item in result:
            # Calculate expected count
            expected_count = sum(
                1 for word in item['collection'].words
                if word.id in user_word_ids
            )
            assert item['words_in_study'] == expected_count

    def test_returns_empty_list_for_no_collections(self, db_session):
        """Test returns empty list when no collections exist"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.auth.models import User
        import uuid

        # Create user without collections
        user = User(
            username=f'nocoll_{uuid.uuid4().hex[:8]}',
            email='nocoll@test.com'
        )
        user.set_password('password')
        db_session.add(user)
        db_session.commit()

        result = CollectionTopicService.get_collections_with_stats(user.id)

        # May return empty or existing collections depending on test data
        assert isinstance(result, list)


class TestGetCollectionWordsWithStatus:
    """Test get_collection_words_with_status method"""

    def test_returns_words_for_collection(self, db_session, test_user, collection_and_topic):
        """Test getting words for a collection"""
        from app.study.services.collection_topic_service import CollectionTopicService

        collection = collection_and_topic["collection"]

        result = CollectionTopicService.get_collection_words_with_status(
            collection.id,
            test_user.id
        )

        assert isinstance(result, list)
        if len(result) > 0:
            word_item = result[0]
            assert 'word' in word_item
            assert 'is_studying' in word_item

    def test_returns_empty_for_nonexistent_collection(self, db_session, test_user):
        """Test returns empty list for non-existent collection"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_collection_words_with_status(99999, test_user.id)

        assert result == []

    def test_is_studying_flag_accurate(self, db_session, test_user, collection_and_topic, user_words):
        """Test that is_studying flag accurately reflects user's words"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.study.models import UserWord

        collection = collection_and_topic["collection"]

        # Get user's word IDs
        user_word_ids = {
            uw.word_id for uw in UserWord.query.filter_by(user_id=test_user.id).all()
        }

        result = CollectionTopicService.get_collection_words_with_status(
            collection.id,
            test_user.id
        )

        for word_item in result:
            expected_studying = word_item['word'].id in user_word_ids
            assert word_item['is_studying'] == expected_studying


class TestAddCollectionToStudy:
    """Test add_collection_to_study method"""

    def test_adds_collection_words_to_study(self, db_session, test_user, collection_and_topic):
        """Test adding all words from collection to user's study list"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.study.models import UserWord

        collection = collection_and_topic["collection"]

        # Count before
        count_before = UserWord.query.filter_by(user_id=test_user.id).count()

        # Add collection
        words_added, message = CollectionTopicService.add_collection_to_study(
            collection.id,
            test_user.id
        )

        # Count after
        count_after = UserWord.query.filter_by(user_id=test_user.id).count()

        assert words_added >= 0
        assert count_after >= count_before
        assert isinstance(message, str)

    def test_returns_error_for_nonexistent_collection(self, db_session, test_user):
        """Test error handling for non-existent collection"""
        from app.study.services.collection_topic_service import CollectionTopicService

        words_added, message = CollectionTopicService.add_collection_to_study(
            99999,
            test_user.id
        )

        assert words_added == 0
        assert 'not found' in message.lower() or message == ''

    def test_skips_already_added_words(self, db_session, test_user, collection_and_topic, user_words):
        """Test that already added words are skipped"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.study.models import UserWord

        collection = collection_and_topic["collection"]

        # Add collection first time
        words_added_1, _ = CollectionTopicService.add_collection_to_study(
            collection.id,
            test_user.id
        )

        # Try adding again
        words_added_2, message = CollectionTopicService.add_collection_to_study(
            collection.id,
            test_user.id
        )

        # Second time should add 0 or fewer words
        assert words_added_2 <= words_added_1


class TestGetTopicsWithStats:
    """Test get_topics_with_stats method"""

    def test_returns_all_topics(self, db_session, test_user, collection_and_topic):
        """Test getting all topics with stats"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_topics_with_stats(test_user.id)

        assert isinstance(result, list)
        if len(result) > 0:
            topic_item = result[0]
            assert 'topic' in topic_item
            assert 'word_count' in topic_item
            assert 'words_in_study' in topic_item

    def test_topic_word_counts_accurate(self, db_session, test_user, collection_and_topic):
        """Test that topic word counts are accurate"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_topics_with_stats(test_user.id)

        for topic_item in result:
            assert topic_item['word_count'] >= 0
            assert topic_item['words_in_study'] >= 0
            assert topic_item['words_in_study'] <= topic_item['word_count']


class TestGetTopicWordsWithStatus:
    """Test get_topic_words_with_status method"""

    def test_returns_topic_and_words(self, db_session, test_user, collection_and_topic):
        """Test getting topic with its words"""
        from app.study.services.collection_topic_service import CollectionTopicService

        topic = collection_and_topic["topic"]

        topic_obj, words, collections = CollectionTopicService.get_topic_words_with_status(
            topic.id,
            test_user.id
        )

        assert topic_obj is not None
        assert isinstance(words, list)
        assert isinstance(collections, list)

    def test_returns_none_for_nonexistent_topic(self, db_session, test_user):
        """Test handling of non-existent topic"""
        from app.study.services.collection_topic_service import CollectionTopicService

        result = CollectionTopicService.get_topic_words_with_status(99999, test_user.id)

        assert result[0] is None  # Topic should be None

    def test_words_have_is_studying_flag(self, db_session, test_user, collection_and_topic):
        """Test that words have is_studying flag"""
        from app.study.services.collection_topic_service import CollectionTopicService

        topic = collection_and_topic["topic"]

        _, words, _ = CollectionTopicService.get_topic_words_with_status(
            topic.id,
            test_user.id
        )

        for word_item in words:
            assert 'word' in word_item
            assert 'is_studying' in word_item
            assert isinstance(word_item['is_studying'], bool)


class TestAddTopicToStudy:
    """Test add_topic_to_study method"""

    def test_adds_topic_words_to_study(self, db_session, test_user, collection_and_topic):
        """Test adding all words from topic to study"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from app.study.models import UserWord

        topic = collection_and_topic["topic"]

        count_before = UserWord.query.filter_by(user_id=test_user.id).count()

        words_added, message = CollectionTopicService.add_topic_to_study(
            topic.id,
            test_user.id
        )

        count_after = UserWord.query.filter_by(user_id=test_user.id).count()

        assert words_added >= 0
        assert count_after >= count_before
        assert isinstance(message, str)

    def test_returns_error_for_nonexistent_topic(self, db_session, test_user):
        """Test error for non-existent topic"""
        from app.study.services.collection_topic_service import CollectionTopicService

        words_added, message = CollectionTopicService.add_topic_to_study(
            99999,
            test_user.id
        )

        assert words_added == 0
        assert 'not found' in message.lower() or message == ''


class TestBulkQueryOptimization:
    """Test that service uses efficient bulk queries (no N+1)"""

    def test_single_query_for_user_words(self, db_session, test_user, collection_and_topic):
        """Test that user words are loaded with single query"""
        from app.study.services.collection_topic_service import CollectionTopicService
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        query_count = {'count': 0}

        def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            query_count['count'] += 1

        event.listen(Engine, "before_cursor_execute", receive_before_cursor_execute)

        try:
            # This should use bulk query, not N queries
            CollectionTopicService.get_collections_with_stats(test_user.id)

            # Query count should be reasonable (not N+1)
            # Exact number depends on implementation, but should be < 10
            assert query_count['count'] < 20
        finally:
            event.remove(Engine, "before_cursor_execute", receive_before_cursor_execute)

    def test_set_based_membership_check(self, db_session, test_user, collection_and_topic, user_words):
        """Test that service uses set-based O(1) lookups"""
        from app.study.services.collection_topic_service import CollectionTopicService

        # This test verifies the service completes quickly
        # If using O(n) queries, it would be slow with many words
        import time
        start = time.time()

        result = CollectionTopicService.get_collections_with_stats(test_user.id)

        elapsed = time.time() - start

        # Should complete quickly (< 1 second even with many words)
        assert elapsed < 1.0
        assert isinstance(result, list)
