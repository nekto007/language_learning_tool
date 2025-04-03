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
    # Changed from String to Text for unlimited length
    password_hash = Column(Text, nullable=False)
    salt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    active = Column(Boolean, default=True)

    words = relationship("CollectionWords", secondary="user_word_status", back_populates="users")
    # Добавление отношения к прогрессу чтения
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
        from app.utils.db import user_word_status
        stmt = db.select(user_word_status.c.status).where(
            (user_word_status.c.user_id == self.id) &
            (user_word_status.c.word_id == word_id)
        )
        result = db.session.execute(stmt).scalar()
        return result if result is not None else 0

    def set_word_status(self, word_id, status):
        from app.utils.db import user_word_status
        existing = db.session.execute(
            db.select(user_word_status).where(
                (user_word_status.c.user_id == self.id) &
                (user_word_status.c.word_id == word_id)
            )
        ).first()

        if existing:
            stmt = db.update(user_word_status).where(
                (user_word_status.c.user_id == self.id) &
                (user_word_status.c.word_id == word_id)
            ).values(status=status, last_updated=datetime.utcnow())
            db.session.execute(stmt)
        else:
            stmt = db.insert(user_word_status).values(
                user_id=self.id,
                word_id=word_id,
                status=status,
                last_updated=datetime.utcnow()
            )
            db.session.execute(stmt)

        db.session.commit()

    # Новые методы для работы с прогрессом чтения
    def get_recent_reading_progress(self, limit=3):
        """Получить последние записи прогресса чтения, отсортированные по дате"""
        from app.books.models import ReadingProgress
        return self.reading_progress.order_by(desc(ReadingProgress.last_read)).limit(limit).all()

    def get_last_read_book(self):
        """Получить книгу, которую пользователь читал последней"""
        from app.books.models import ReadingProgress
        return self.reading_progress.order_by(desc(ReadingProgress.last_read)).first()

    def get_reading_progress_count(self):
        """Получить количество книг, которые читает пользователь"""
        return self.reading_progress.count()

    # Flask-Login properties
    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)