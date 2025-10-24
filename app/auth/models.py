import secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, desc
from sqlalchemy.orm import relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.utils.db import db


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(120), unique=True)
    password_hash = Column(Text, nullable=False)
    salt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime)
    active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    telegram_api_token = Column(String(64), unique=True, nullable=True)

    # # Связь со словами теперь через UserWord
    # words = relationship("CollectionWords",
    #                      secondary="user_words",
    #                      primaryjoin="User.id == UserWord.user_id",
    #                      secondaryjoin="UserWord.word_id == CollectionWords.id",
    #                      backref="users")


    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_email', 'email'),
        Index('idx_user_telegram_token', 'telegram_api_token'),
    )

    def set_password(self, password):
        self.salt = secrets.token_hex(16)
        self.password_hash = generate_password_hash(password + self.salt)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password + self.salt)

    def generate_telegram_token(self):
        """Generate a new Telegram API token for this user"""
        self.telegram_api_token = secrets.token_urlsafe(32)
        return self.telegram_api_token

    def get_word_status(self, word_id):
        """
        Получает статус слова для пользователя.
        Возвращает целое число для API совместимости:
        0 = новое, 1 = изучаемое, 2 = на повторении, 3 = изучено
        """
        from app.study.models import UserWord
        from app.utils.db import string_to_status

        user_word = UserWord.query.filter_by(
            user_id=self.id,
            word_id=word_id
        ).first()

        if user_word:
            return string_to_status(user_word.status)
        return 0

    def set_word_status(self, word_id, status):
        """
        Устанавливает статус слова для пользователя.

        status: целое число (0 = новое, 1 = изучаемое, 2 = на повторении, 3 = изучено)
        """
        from app.study.models import UserWord, UserCardDirection
        from app.utils.db import status_to_string, db

        status_string = status_to_string(status)

        user_word = UserWord.query.filter_by(user_id=self.id, word_id=word_id).first()

        if not user_word and status > 0:  # Создаем запись только если статус не "новое"
            user_word = UserWord(user_id=self.id, word_id=word_id)
            db.session.add(user_word)
            db.session.flush()  # Чтобы получить ID

            # Создаем направления для слова, если статус требует их наличия
            if status_string != 'mastered':  # Для 'mastered' не создаем направления
                for direction_str in ['eng-rus', 'rus-eng']:
                    direction = UserCardDirection(
                        user_word_id=user_word.id,
                        direction=direction_str
                    )
                    db.session.add(direction)

        # Если статус 0 и запись существует, удаляем её
        if status == 0 and user_word:
            # Удаляем связанные направления
            UserCardDirection.query.filter_by(user_word_id=user_word.id).delete()
            # Удаляем запись UserWord
            db.session.delete(user_word)
        elif user_word:
            # Устанавливаем статус
            old_status = user_word.status
            user_word.status = status_string

            # Если статус изменился с 'mastered' на другой, создаем направления
            if old_status == 'mastered' and status_string != 'mastered':
                # Проверяем, есть ли у слова направления
                directions_count = UserCardDirection.query.filter_by(user_word_id=user_word.id).count()
                if directions_count == 0:
                    # Создаем направления, если их нет
                    for direction_str in ['eng-rus', 'rus-eng']:
                        direction = UserCardDirection(
                            user_word_id=user_word.id,
                            direction=direction_str
                        )
                        db.session.add(direction)

        db.session.commit()
        return user_word

    def get_recent_reading_progress(self, limit=3):
        """Get recent chapter reading progress"""
        from app.books.models import UserChapterProgress
        return UserChapterProgress.query.filter_by(
            user_id=self.id
        ).order_by(desc(UserChapterProgress.updated_at)).limit(limit).all()

    def get_last_read_book(self):
        """Get last read book from chapter progress"""
        from app.books.models import UserChapterProgress, Chapter, Book
        latest_progress = UserChapterProgress.query.filter_by(
            user_id=self.id
        ).join(Chapter).join(Book).order_by(
            desc(UserChapterProgress.updated_at)
        ).first()
        return latest_progress.chapter.book if latest_progress else None

    def get_reading_progress_count(self):
        """Get count of books with reading progress"""
        from app.books.models import UserChapterProgress, Chapter, Book
        return db.session.query(Book.id).join(Chapter).join(
            UserChapterProgress
        ).filter(UserChapterProgress.user_id == self.id).distinct().count()

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)
    
    def __repr__(self):
        return f'<User {self.username}>'
