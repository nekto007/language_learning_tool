"""
Tests for words models
Тесты моделей слов
"""
import pytest
from app.words.models import Topic, Collection, CollectionWords


class TestTopicModel:
    """Тесты модели Topic"""

    def test_create_topic(self, app, db_session, test_user):
        """Тест создания топика"""
        with app.app_context():
            topic = Topic(
                name='Animals',
                created_by=test_user.id
            )
            db_session.add(topic)
            db_session.commit()

            assert topic.id is not None
            assert topic.name == 'Animals'

    def test_topic_repr(self, app, db_session, test_user):
        """Тест __repr__ метода"""
        with app.app_context():
            topic = Topic(
                name='Food',
                created_by=test_user.id
            )
            db_session.add(topic)
            db_session.commit()

            repr_str = repr(topic)
            assert 'Topic' in repr_str
            assert 'Food' in repr_str


class TestCollectionModel:
    """Тесты модели Collection"""

    def test_create_collection(self, app, db_session, test_user):
        """Тест создания коллекции"""
        with app.app_context():
            collection = Collection(
                name='Basic Vocabulary',
                description='Essential words',
                created_by=test_user.id
            )
            db_session.add(collection)
            db_session.commit()

            assert collection.id is not None
            assert collection.name == 'Basic Vocabulary'

    def test_collection_repr(self, app, db_session, test_user):
        """Тест __repr__ метода"""
        with app.app_context():
            collection = Collection(
                name='Advanced Words',
                created_by=test_user.id
            )
            db_session.add(collection)
            db_session.commit()

            repr_str = repr(collection)
            assert 'Collection' in repr_str
            assert 'Advanced Words' in repr_str

    def test_collection_word_count_property(self, app, db_session, test_user):
        """Тест свойства word_count"""
        with app.app_context():
            # Создаем коллекцию
            import uuid
            unique_id = uuid.uuid4().hex[:8]
            collection = Collection(
                name=f'Test Collection {unique_id}',
                created_by=test_user.id
            )
            db_session.add(collection)
            db_session.flush()

            # Создаем несколько слов и добавляем в коллекцию
            for i in range(3):
                word = CollectionWords(
                    english_word=f'word_{uuid.uuid4().hex[:8]}',
                    russian_word=f'слово_{i}',
                    level='A1'
                )
                db_session.add(word)
                collection.words.append(word)

            db_session.commit()

            # Проверяем word_count
            assert collection.word_count == 3

    def test_collection_topics_property(self, app, db_session, test_user):
        """Тест свойства topics"""
        with app.app_context():
            import uuid
            unique_suffix = uuid.uuid4().hex[:8]

            # Создаем коллекцию
            collection = Collection(
                name=f'Test Collection {unique_suffix}',
                created_by=test_user.id
            )
            db_session.add(collection)
            db_session.flush()

            # Создаем топики с уникальными именами
            topic1 = Topic(name=f'Animals_{unique_suffix}', created_by=test_user.id)
            topic2 = Topic(name=f'Food_{unique_suffix}', created_by=test_user.id)
            db_session.add_all([topic1, topic2])
            db_session.flush()

            # Создаем слова с топиками
            word1 = CollectionWords(
                english_word=f'cat_{uuid.uuid4().hex[:8]}',
                russian_word='кошка',
                level='A1'
            )
            word1.topics.append(topic1)

            word2 = CollectionWords(
                english_word=f'apple_{uuid.uuid4().hex[:8]}',
                russian_word='яблоко',
                level='A1'
            )
            word2.topics.append(topic2)

            collection.words.extend([word1, word2])
            db_session.add_all([word1, word2])
            db_session.commit()

            # Проверяем topics property
            topics_list = collection.topics
            assert len(topics_list) == 2
            topic_names = [t.name for t in topics_list]
            assert any('Animals' in name for name in topic_names)
            assert any('Food' in name for name in topic_names)
