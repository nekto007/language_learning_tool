from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint

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


# Удаляем определение user_word_status

def status_to_string(status_int):
    """
    Преобразует цифровой статус в строковый для модели UserWord

    0 = 'new' (новое слово)
    1 = 'learning' (изучаемое)
    2 = 'review' (на повторении)
    3 = 'mastered' (изучено)
    """
    status_map = {
        0: 'new',
        1: 'learning',
        2: 'review',
        3: 'mastered'
    }
    return status_map.get(status_int, 'new')


def string_to_status(status_string):
    """
    Преобразует строковый статус в цифровой для API совместимости

    'new' = 0
    'learning' = 1
    'review' = 2
    'mastered' = 3
    """
    status_map = {
        'new': 0,
        'learning': 1,
        'review': 2,
        'mastered': 3,
        'active': 3  # Alias for mastered
    }
    return status_map.get(status_string, 0)
