from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint

db = SQLAlchemy()

# Word-Book relationship table
word_book_link = db.Table(
    'word_book_link',
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('word_id', Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False),
    Column('book_id', Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False),
    Column('frequency', Integer, default=1),
    UniqueConstraint('word_id', 'book_id', name='uq_word_book'),
    extend_existing=True
)

# User-Word status relationship table
user_word_status = db.Table(
    'user_word_status',
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    Column('word_id', Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False),
    Column('status', Integer, default=0, nullable=False),
    Column('last_updated', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    UniqueConstraint('user_id', 'word_id', name='uq_user_word'),
    Index('idx_user_word_status', 'user_id', 'word_id'),
    Index('idx_user_word_status_status', 'user_id', 'status'),
    extend_existing=True
)


def status_to_string(status_int):
    """
    Преобразует цифровой статус в строковый для новой модели UserWord

    0 = 'new' (новое слово)
    1 = 'learning' (изучаемое)
    2 = 'review' (на повторении)
    3 = 'mastered' (изучено)
    4 = другие значения (по умолчанию 'new')
    """
    status_map = {
        0: 'new',
        1: 'learning',
        2: 'review',
        3: 'mastered'
    }
    return status_map.get(status_int, 'new')


# Функция для преобразования статуса из нового формата (string) в старый формат (int)
def string_to_status(status_string):
    """
    Преобразует строковый статус в цифровой для обратной совместимости

    'new' = 0
    'learning' = 1
    'review' = 2
    'mastered' = 3
    """
    status_map = {
        'new': 0,
        'learning': 1,
        'review': 2,
        'mastered': 3
    }
    return status_map.get(status_string, 0)