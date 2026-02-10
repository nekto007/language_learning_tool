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

            # Устанавливаем статус "new" (status=1 maps to 'new')
            user_word = test_user.set_word_status(test_word.id, 1)

            assert user_word is not None
            assert user_word.status == 'new'

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
        """Тест установки статуса 'уже знаю' (review с высоким интервалом)"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Устанавливаем статус "уже знаю" (status=3 maps to 'review' with high interval)
            user_word = test_user.set_word_status(test_word.id, 3)

            assert user_word is not None
            assert user_word.status == 'review'

            # Для "уже знаю" создаются направления с высоким интервалом
            directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
            assert len(directions) == 2
            # Проверяем что интервал высокий (180 дней)
            for direction in directions:
                assert direction.state == 'review'
                assert direction.interval == UserWord.MASTERED_THRESHOLD_DAYS

    def test_set_word_status_from_mastered_to_new(self, app, db_session, test_user, test_word):
        """Тест изменения статуса с 'уже знаю' на status=1 (не меняет фактический статус из-за recalculate)"""
        with app.app_context():
            from app.study.models import UserWord, UserCardDirection

            # Сначала устанавливаем "уже знаю" (status=3 -> 'review' с высоким интервалом)
            test_user.set_word_status(test_word.id, 3)

            # Затем вызываем set_word_status с status=1
            # Но recalculate_status() пересчитывает статус на основе карточек,
            # которые остаются в 'review' состоянии с высоким интервалом
            user_word = test_user.set_word_status(test_word.id, 1)

            # Статус остаётся 'review' т.к. recalculate_status() определяет его по карточкам
            assert user_word.status == 'review'

            # Направления уже были созданы при status=3
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
