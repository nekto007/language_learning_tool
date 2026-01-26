"""
Collection/Topic Service - manages word collections and topics

Responsibilities:
- Collection/Topic listing with filtering
- Adding collections/topics to user's study list
- User progress tracking
- Efficient bulk queries to avoid N+1
"""
from typing import List, Dict, Optional
from sqlalchemy import func, or_

from app.utils.db import db
from app.study.models import UserWord
from app.words.models import CollectionWords, Collection, Topic
from app.study.services.srs_service import get_user_word_ids


class CollectionTopicService:
    """Service for managing collections and topics"""

    @staticmethod
    def get_collections_with_stats(user_id: int, topic_id: Optional[int] = None,
                                   search: Optional[str] = None) -> List[Dict]:
        """
        Get collections with user progress statistics

        Args:
            user_id: User ID
            topic_id: Optional topic filter
            search: Optional search query

        Returns:
            List of collections with stats
        """
        # Base query
        query = Collection.query

        # Apply topic filter
        if topic_id:
            query = query.join(
                db.Table('collection_words_link'),
                Collection.id == db.Table('collection_words_link').c.collection_id
            ).join(
                CollectionWords,
                db.Table('collection_words_link').c.word_id == CollectionWords.id
            ).join(
                db.Table('topic_words'),
                CollectionWords.id == db.Table('topic_words').c.word_id
            ).filter(
                db.Table('topic_words').c.topic_id == topic_id
            ).group_by(Collection.id)

        # Apply search
        if search:
            query = query.filter(
                or_(
                    Collection.name.ilike(f'%{search}%'),
                    Collection.description.ilike(f'%{search}%')
                )
            )

        collections = query.order_by(Collection.name).all()

        # Bulk load user word statuses
        user_word_ids = get_user_word_ids(user_id)

        # Add stats to each collection
        result = []
        for collection in collections:
            words_in_study = sum(1 for word in collection.words if word.id in user_word_ids)

            result.append({
                'collection': collection,
                'word_count': len(collection.words),
                'words_in_study': words_in_study,
                'topics': collection.topics
            })

        return result

    @staticmethod
    def get_collection_words_with_status(collection_id: int, user_id: int) -> List[Dict]:
        """
        Get collection words with user learning status

        Returns:
            List of words with is_studying flag
        """
        collection = Collection.query.get(collection_id)
        if not collection:
            return []

        words = collection.words

        # Bulk load user word statuses
        word_ids = [w.id for w in words]
        user_word_ids = get_user_word_ids(user_id, word_ids)

        # Add status to each word
        result = []
        for word in words:
            result.append({
                'word': word,
                'is_studying': word.id in user_word_ids
            })

        return result

    @staticmethod
    def add_collection_to_study(collection_id: int, user_id: int) -> tuple[int, str]:
        """
        Add all words from collection to user's study list

        Returns:
            Tuple of (added_count, message)
        """
        collection = Collection.query.get(collection_id)
        if not collection:
            return 0, "Collection not found"

        words = collection.words

        # Bulk check existing words
        word_ids = [w.id for w in words]
        existing_word_ids = get_user_word_ids(user_id, word_ids)

        # Add new words
        added_count = 0
        for word in words:
            if word.id not in existing_word_ids:
                user_word = UserWord(user_id=user_id, word_id=word.id)
                db.session.add(user_word)
                added_count += 1

        if added_count > 0:
            db.session.commit()

        return added_count, f'{added_count} words added' if added_count > 0 else 'All words already in study list'

    @staticmethod
    def get_topics_with_stats(user_id: int) -> List[Dict]:
        """
        Get all topics with user progress statistics

        Returns:
            List of topics with stats
        """
        topics = Topic.query.order_by(Topic.name).all()

        # Bulk load user word statuses
        user_word_ids = get_user_word_ids(user_id)

        # Add stats to each topic
        result = []
        for topic in topics:
            word_count = len(topic.words)
            words_in_study = sum(1 for word in topic.words if word.id in user_word_ids)

            result.append({
                'topic': topic,
                'word_count': word_count,
                'words_in_study': words_in_study
            })

        return result

    @staticmethod
    def get_topic_words_with_status(topic_id: int, user_id: int) -> tuple[Optional[Topic], List[Dict], List]:
        """
        Get topic words with user learning status and related collections

        Returns:
            Tuple of (topic, words_with_status, related_collections)
        """
        topic = Topic.query.get(topic_id)
        if not topic:
            return None, [], []

        words = topic.words

        # Bulk load user word statuses
        word_ids = [w.id for w in words]
        user_word_ids = get_user_word_ids(user_id, word_ids)

        # Add status to each word
        words_with_status = []
        for word in words:
            words_with_status.append({
                'word': word,
                'is_studying': word.id in user_word_ids
            })

        # Get related collections
        related_collections = db.session.query(Collection).join(
            db.Table('collection_words_link'),
            Collection.id == db.Table('collection_words_link').c.collection_id
        ).join(
            CollectionWords,
            db.Table('collection_words_link').c.word_id == CollectionWords.id
        ).join(
            db.Table('topic_words'),
            CollectionWords.id == db.Table('topic_words').c.word_id
        ).filter(
            db.Table('topic_words').c.topic_id == topic_id
        ).group_by(
            Collection.id
        ).order_by(
            Collection.name
        ).all()

        return topic, words_with_status, related_collections

    @staticmethod
    def add_topic_to_study(topic_id: int, user_id: int) -> tuple[int, str]:
        """
        Add all words from topic to user's study list

        Returns:
            Tuple of (added_count, message)
        """
        topic = Topic.query.get(topic_id)
        if not topic:
            return 0, "Topic not found"

        words = topic.words

        # Bulk check existing words
        word_ids = [w.id for w in words]
        existing_word_ids = get_user_word_ids(user_id, word_ids)

        # Add new words
        added_count = 0
        for word in words:
            if word.id not in existing_word_ids:
                user_word = UserWord(user_id=user_id, word_id=word.id)
                db.session.add(user_word)
                added_count += 1

        if added_count > 0:
            db.session.commit()

        return added_count, f'{added_count} words added' if added_count > 0 else 'All words already in study list'
