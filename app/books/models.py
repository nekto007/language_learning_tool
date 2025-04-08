# app/books/models.py

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.utils.db import db


class Book(db.Model):
    __tablename__ = 'book'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), unique=True, nullable=False)
    author = Column(String(255), nullable=True)
    level = Column(String(2), nullable=True)
    total_words = Column(Integer, default=0)
    unique_words = Column(Integer, default=0)
    scrape_date = Column(DateTime, default=datetime.utcnow)
    content = Column(Text)
    cover_image = Column(String(255))

    words = relationship("CollectionWords", secondary="word_book_link", back_populates="books")


# Модель для отслеживания прогресса чтения
class ReadingProgress(db.Model):
    """
    Tracks a user's reading progress in books
    """
    __tablename__ = 'reading_progress'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    book_id = Column(Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False)

    # Текущая позиция в книге
    position = Column(Integer, default=0)  # Позиция в пикселях для прокрутки
    last_read = Column(DateTime, default=datetime.utcnow)

    # Связи - заменяем backref на back_populates
    user = relationship('User', back_populates='reading_progress')
    book = relationship('Book', backref=db.backref('reading_progress', lazy='dynamic'))

    # Обеспечиваем, чтобы у пользователя был только один прогресс на книгу
    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uix_user_book_progress'),
        Index('idx_reading_progress_user', 'user_id'),
        Index('idx_reading_progress_book', 'book_id'),
    )
