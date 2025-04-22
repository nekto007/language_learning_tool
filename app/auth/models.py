import secrets
from datetime import datetime

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
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    words = relationship("CollectionWords", secondary="user_word_status", back_populates="users")
    reading_progress = relationship("ReadingProgress", back_populates="user", lazy="dynamic",
                                    cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_email', 'email'),
    )

    def set_password(self, password):
        self.salt = secrets.token_hex(16)
        self.password_hash = generate_password_hash(password + self.salt)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password + self.salt)

    def get_word_status(self, word_id):
        """
        Получает статус слова для пользователя.
        Работает как с новой, так и со старой системой.

        Возвращает целое число для обратной совместимости:
        0 = новое, 1 = изучаемое, 2 = на повторении, 3 = изучено
        """
        # Сначала проверяем новую систему
        from app.study.models import UserWord
        user_word = UserWord.query.filter_by(
            user_id=self.id,
            word_id=word_id
        ).first()

        if user_word:
            from app.utils.db import convert_status_string_to_int
            return convert_status_string_to_int(user_word.status)

        # Если не найдено в новой системе, проверяем старую
        from app.utils.db import user_word_status, db
        query = db.select([user_word_status.c.status]).where(
            (user_word_status.c.user_id == self.id) &
            (user_word_status.c.word_id == word_id)
        )
        result = db.session.execute(query).fetchone()

        # Возвращаем статус или 0, если запись не найдена
        return result[0] if result else 0

    def set_word_status(self, word_id, status):
        """
        Устанавливает статус слова для пользователя.
        Обновляет как новую, так и старую систему.

        status: целое число (0 = новое, 1 = изучаемое, 2 = на повторении, 3 = изучено)
        """
        # Обновляем новую систему
        from app.study.models import UserWord, UserCardDirection
        from app.utils.db import convert_status_int_to_string, db

        status_string = convert_status_int_to_string(status)

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
            # Если статус изменился на 'mastered', можно удалить направления (опционально)
            elif status_string == 'mastered':
                # Решите, хотите ли вы удалять направления для выученных слов
                # UserCardDirection.query.filter_by(user_word_id=user_word.id).delete()
                pass

        # Обновляем старую систему
        from app.utils.db import user_word_status

        # Проверяем, существует ли запись
        query = db.select([user_word_status.c.id]).where(
            (user_word_status.c.user_id == self.id) &
            (user_word_status.c.word_id == word_id)
        )
        result = db.session.execute(query).fetchone()

        if result:
            # Обновляем существующую запись
            db.session.execute(
                user_word_status.update().where(
                    (user_word_status.c.user_id == self.id) &
                    (user_word_status.c.word_id == word_id)
                ).values(status=status)
            )
        elif status > 0:  # Создаем запись только для не-новых слов
            # Создаем новую запись
            db.session.execute(
                user_word_status.insert().values(
                    user_id=self.id,
                    word_id=word_id,
                    status=status
                )
            )

        db.session.commit()
        return user_word

    def get_recent_reading_progress(self, limit=3):
        from app.books.models import ReadingProgress
        return self.reading_progress.order_by(desc(ReadingProgress.last_read)).limit(limit).all()

    def get_last_read_book(self):
        from app.books.models import ReadingProgress
        return self.reading_progress.order_by(desc(ReadingProgress.last_read)).first()

    def get_reading_progress_count(self):
        return self.reading_progress.count()

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)
