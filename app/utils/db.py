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
