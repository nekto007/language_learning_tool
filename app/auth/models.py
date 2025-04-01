import secrets
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String
from sqlalchemy.orm import relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.utils.db import db


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(120), unique=True)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    active = Column(Boolean, default=True)

    words = relationship("CollectionWords", secondary="user_word_status", back_populates="users")

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

    # Flask-Login properties
    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)
