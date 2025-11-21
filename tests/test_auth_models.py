"""
Tests for auth models
Тесты моделей аутентификации
"""
import pytest
import uuid
from app.auth.models import User


class TestUserModel:
    """Тесты модели User"""

    def test_create_user(self, app, db_session):
        """Тест создания пользователя"""
        with app.app_context():
            username = f'testuser_{uuid.uuid4().hex[:8]}'
            user = User(username=username, email=f'{username}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            assert user.id is not None
            assert user.username == username
            assert user.email == f'{username}@example.com'
            assert user.password_hash is not None
            assert user.salt is not None

    def test_set_password(self, app, db_session):
        """Тест установки пароля"""
        with app.app_context():
            user = User(username='testuser', email='test@example.com')
            user.set_password('mypassword')

            assert user.password_hash is not None
            assert user.salt is not None
            assert len(user.salt) == 32  # token_hex(16) creates 32 char hex string

    def test_check_password_correct(self, app, db_session):
        """Тест проверки правильного пароля"""
        with app.app_context():
            username = f'testuser_{uuid.uuid4().hex[:8]}'
            user = User(username=username, email=f'{username}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            assert user.check_password('password123') is True

    def test_check_password_incorrect(self, app, db_session):
        """Тест проверки неправильного пароля"""
        with app.app_context():
            username = f'testuser_{uuid.uuid4().hex[:8]}'
            user = User(username=username, email=f'{username}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            assert user.check_password('wrongpassword') is False

    def test_generate_telegram_token(self, app, db_session):
        """Тест генерации Telegram токена"""
        with app.app_context():
            from app.telegram.models import TelegramToken

            username = f'testuser_{uuid.uuid4().hex[:8]}'
            user = User(username=username, email=f'{username}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Create telegram token using new TelegramToken model
            token = TelegramToken.create_token(user.id, scope='read,write')
            assert token is not None
            assert len(token.token) == 64  # token_hex(32) creates 64 hex chars
            assert token.user_id == user.id
            assert token.is_valid()

    def test_get_word_status_new_word(self, app, db_session, test_user, test_word):
        """Тест получения статуса нового слова"""
        with app.app_context():
            status = test_user.get_word_status(test_word.id)
            assert status == 0  # новое слово

    def test_get_word_status_existing_word(self, app, db_session, test_user, test_word):
        """Тест получения статуса существующего слова"""
        with app.app_context():
            from app.study.models import UserWord

            # Создаем UserWord со статусом "learning"
            user_word = UserWord(user_id=test_user.id, word_id=test_word.id)
            user_word.status = 'learning'
            db_session.add(user_word)
            db_session.commit()

            status = test_user.get_word_status(test_word.id)
            assert status == 1  # изучаемое

    def test_set_word_status_create_new(self, app, db_session, test_user, test_word):
        """Тест установки статуса для нового слова"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Устанавливаем статус "learning"
            user_word = test_user.set_word_status(test_word.id, 1)

            assert user_word is not None
            assert user_word.status == 'learning'

            # Проверяем что созданы направления
            directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
            assert len(directions) == 2

    def test_set_word_status_to_zero_deletes(self, app, db_session, test_user, test_word):
        """Тест установки статуса 0 удаляет запись"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Сначала создаем слово
            test_user.set_word_status(test_word.id, 1)
            user_word = UserWord.query.filter_by(user_id=test_user.id, word_id=test_word.id).first()
            assert user_word is not None

            # Устанавливаем статус 0
            test_user.set_word_status(test_word.id, 0)

            # Проверяем что запись удалена
            user_word = UserWord.query.filter_by(user_id=test_user.id, word_id=test_word.id).first()
            assert user_word is None

    def test_set_word_status_mastered(self, app, db_session, test_user, test_word):
        """Тест установки статуса mastered"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Устанавливаем статус "mastered"
            user_word = test_user.set_word_status(test_word.id, 3)

            assert user_word is not None
            assert user_word.status == 'mastered'

            # Для mastered не создаются направления
            directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
            assert len(directions) == 0

    def test_set_word_status_from_mastered_to_learning(self, app, db_session, test_user, test_word):
        """Тест изменения статуса с mastered на learning"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Сначала устанавливаем mastered
            test_user.set_word_status(test_word.id, 3)

            # Затем изменяем на learning
            user_word = test_user.set_word_status(test_word.id, 1)

            assert user_word.status == 'learning'

            # Проверяем что созданы направления
            directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
            assert len(directions) == 2

    def test_get_recent_reading_progress(self, app, db_session, test_user, test_chapter):
        """Тест получения недавнего прогресса чтения"""
        with app.app_context():
            from app.books.models import UserChapterProgress

            # Создаем прогресс
            progress = UserChapterProgress(
                user_id=test_user.id,
                chapter_id=test_chapter.id,
                offset_pct=0.5
            )
            db_session.add(progress)
            db_session.commit()

            recent = test_user.get_recent_reading_progress(limit=3)
            assert len(recent) == 1
            assert recent[0].chapter_id == test_chapter.id

    def test_get_last_read_book(self, app, db_session, test_user, test_chapter):
        """Тест получения последней прочитанной книги"""
        with app.app_context():
            from app.books.models import UserChapterProgress

            # Создаем прогресс
            progress = UserChapterProgress(
                user_id=test_user.id,
                chapter_id=test_chapter.id,
                offset_pct=0.5
            )
            db_session.add(progress)
            db_session.commit()

            last_book = test_user.get_last_read_book()
            assert last_book is not None
            assert last_book.id == test_chapter.book_id

    def test_get_last_read_book_none(self, app, db_session, test_user):
        """Тест получения последней книги когда нет прогресса"""
        with app.app_context():
            last_book = test_user.get_last_read_book()
            assert last_book is None

    def test_get_reading_progress_count(self, app, db_session, test_user, test_book, test_chapter):
        """Тест подсчета книг с прогрессом чтения"""
        with app.app_context():
            from app.books.models import UserChapterProgress

            # Создаем прогресс для одной книги
            progress = UserChapterProgress(
                user_id=test_user.id,
                chapter_id=test_chapter.id,
                offset_pct=0.5
            )
            db_session.add(progress)
            db_session.commit()

            count = test_user.get_reading_progress_count()
            assert count == 1

    def test_is_active_property(self, app, db_session, test_user):
        """Тест свойства is_active"""
        with app.app_context():
            test_user.active = True
            assert test_user.is_active is True

            test_user.active = False
            assert test_user.is_active is False

    def test_get_id(self, app, db_session, test_user):
        """Тест метода get_id"""
        with app.app_context():
            user_id = test_user.get_id()
            assert user_id == str(test_user.id)
            assert isinstance(user_id, str)

    def test_user_repr(self, app, db_session, test_user):
        """Тест __repr__ метода"""
        with app.app_context():
            repr_str = repr(test_user)
            assert 'User' in repr_str
            assert test_user.username in repr_str

    def test_user_defaults(self, app, db_session):
        """Тест значений по умолчанию"""
        with app.app_context():
            username = f'newuser_{uuid.uuid4().hex[:8]}'
            user = User(username=username, email=f'{username}@example.com')
            user.set_password('password')
            db_session.add(user)
            db_session.commit()

            assert user.active is True
            assert user.is_admin is False
            assert user.created_at is not None
            assert user.last_login is None
