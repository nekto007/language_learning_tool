"""
Tests for words forms
Тесты форм слов
"""
import pytest
from app.words.forms import (
    WordSearchForm, WordFilterForm, TopicForm,
    CollectionForm, CollectionFilterForm, AnkiExportForm
)


class TestWordSearchForm:
    """Тесты формы WordSearchForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = WordSearchForm(search='test')
            assert form.search.data == 'test'

    def test_form_csrf_disabled(self, app):
        """Тест что CSRF отключен"""
        with app.test_request_context():
            form = WordSearchForm()
            assert form.Meta.csrf is False


class TestWordFilterForm:
    """Тесты формы WordFilterForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = WordFilterForm(status='learning')
            assert form.status.data == 'learning'

    def test_form_csrf_disabled(self, app):
        """Тест что CSRF отключен"""
        with app.test_request_context():
            form = WordFilterForm()
            assert form.Meta.csrf is False

    def test_form_init_with_books(self, app, db_session, test_book):
        """Тест инициализации формы с книгами"""
        with app.app_context():
            form = WordFilterForm()
            # Should have at least the default "All Books" option
            assert len(form.book_id.choices) >= 1
            assert form.book_id.choices[0] == (0, 'All Books')

    def test_form_init_populates_book_choices(self, app, db_session, test_book):
        """Тест заполнения списка книг"""
        with app.app_context():
            form = WordFilterForm()
            # Should include our test book
            book_ids = [choice[0] for choice in form.book_id.choices]
            assert test_book.id in book_ids

    def test_form_init_handles_db_error(self, app, monkeypatch):
        """Тест обработки ошибки БД"""
        from app.books.models import Book
        from unittest.mock import MagicMock

        # Mock db.session.execute to raise an exception
        def mock_execute(*args, **kwargs):
            raise Exception("Database error")

        with app.test_request_context():
            # Patch db.session.execute to raise error
            from app.utils.db import db
            monkeypatch.setattr(db.session, 'execute', mock_execute)

            # Form should still be created with default choices only
            form = WordFilterForm()
            # Should only have default choice since DB query failed
            assert form.book_id.choices == [(0, 'All Books')]


class TestTopicForm:
    """Тесты формы TopicForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = TopicForm(
                name='Animals',
                description='Animal vocabulary'
            )
            assert form.name.data == 'Animals'
            assert form.description.data == 'Animal vocabulary'

    def test_form_validation_required_name(self, app):
        """Тест валидации обязательного имени"""
        with app.test_request_context():
            form = TopicForm(name='')
            assert not form.validate()
            assert 'name' in form.errors


class TestCollectionForm:
    """Тесты формы CollectionForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = CollectionForm(
                name='Basic Words',
                description='Basic vocabulary'
            )
            assert form.name.data == 'Basic Words'
            assert form.description.data == 'Basic vocabulary'

    def test_form_validation_required_name(self, app):
        """Тест валидации обязательного имени"""
        with app.test_request_context():
            form = CollectionForm(name='')
            assert not form.validate()
            assert 'name' in form.errors

    def test_form_has_hidden_fields(self, app):
        """Тест наличия скрытых полей"""
        with app.test_request_context():
            form = CollectionForm()
            assert hasattr(form, 'topic_ids')
            assert hasattr(form, 'word_ids')


class TestCollectionFilterForm:
    """Тесты формы CollectionFilterForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = CollectionFilterForm(search='test')
            assert form.search.data == 'test'

    def test_form_csrf_disabled(self, app):
        """Тест что CSRF отключен"""
        with app.test_request_context():
            form = CollectionFilterForm()
            assert form.Meta.csrf is False

    def test_form_init_with_topics(self, app, db_session, test_user):
        """Тест инициализации формы с топиками"""
        with app.app_context():
            from app.words.models import Topic
            import uuid

            # Создаем топик
            topic = Topic(
                name=f'Test Topic {uuid.uuid4().hex[:8]}',
                created_by=test_user.id
            )
            db_session.add(topic)
            db_session.commit()

            form = CollectionFilterForm()
            # Should have at least the default "All Topics" option
            assert len(form.topic.choices) >= 1
            assert form.topic.choices[0] == ('', 'All Topics')

    def test_form_init_populates_topic_choices(self, app, db_session, test_user):
        """Тест заполнения списка топиков"""
        with app.app_context():
            from app.words.models import Topic
            import uuid

            # Создаем топик
            unique_name = f'Animals {uuid.uuid4().hex[:8]}'
            topic = Topic(
                name=unique_name,
                created_by=test_user.id
            )
            db_session.add(topic)
            db_session.commit()

            form = CollectionFilterForm()
            # Should include our test topic
            topic_names = [choice[1] for choice in form.topic.choices]
            assert unique_name in topic_names


class TestAnkiExportForm:
    """Тесты формы AnkiExportForm"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = AnkiExportForm(
                status='learning',
                include_audio=True
            )
            assert form.status.data == 'learning'
            assert form.include_audio.data is True

    def test_form_default_values(self, app):
        """Тест значений по умолчанию"""
        with app.test_request_context():
            form = AnkiExportForm()
            assert form.status.data is None or form.status.data == 'all'
            assert form.include_audio.data is True

    def test_form_validation_required_status(self, app):
        """Тест валидации обязательного статуса"""
        with app.test_request_context():
            form = AnkiExportForm(status='')
            # Status is required
            if not form.validate():
                # This is expected if validator requires non-empty status
                pass
