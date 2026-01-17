# app/books/models.py

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Float, CheckConstraint, Enum as SQLAEnum, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.utils.db import db
from app.utils.types import JSONBCompat, TSVectorCompat


class TaskType(Enum):
    reading_mcq = 'reading_mcq'
    match_headings = 'match_headings'
    open_cloze = 'open_cloze'
    word_formation = 'word_formation'
    keyword_transform = 'keyword_transform'
    grammar_sheet = 'grammar_sheet'
    vocabulary = 'vocabulary'
    reading_passage = 'reading_passage'
    final_test = 'final_test'


class Book(db.Model):
    __tablename__ = 'book'

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), unique=True, nullable=True)  # Used for both book and course identification
    title = Column(String(255), nullable=False)
    author = Column(String(255), nullable=False)
    chapters_cnt = Column(Integer, nullable=False)
    lang = Column(String(10), default='en')
    level = Column(String(2), nullable=True)
    summary = Column(Text)  # Book annotation/description
    words_total = Column(Integer, default=0)
    unique_words = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    cover_image = Column(String(255))
    
    # Course generation fields
    create_course = Column(db.Boolean, default=False, nullable=False)

    words = relationship("CollectionWords", secondary="word_book_link", back_populates="books")
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    blocks = relationship("Block", back_populates="book", cascade="all, delete-orphan")


class Chapter(db.Model):
    """One chapter of a book"""
    __tablename__ = 'chapter'

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False)
    chap_num = Column(Integer, nullable=False)  # 1...17
    title = Column(String(255), nullable=False)
    words = Column(Integer, nullable=False)
    text_raw = Column(Text, nullable=False)  # Full chapter text
    audio_url = Column(Text)  # Optional S3 URL for audio
    ts_idx = Column(TSVectorCompat)  # Full-text search index
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    book = relationship("Book", back_populates="chapters")
    blocks = relationship("Block", secondary="block_chapter", back_populates="chapters")
    progress = relationship("UserChapterProgress", back_populates="chapter", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('book_id', 'chap_num', name='uix_book_chapter'),
        Index('idx_chapter_fts', 'ts_idx', postgresql_using='gin'),
    )


# Модель для отслеживания прогресса чтения

class Bookmark(db.Model):
    """
    Bookmarks for reading positions in books
    """
    __tablename__ = 'bookmarks'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    book_id = Column(Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False)

    name = Column(String(255), nullable=False)
    position = Column(Integer, default=0)  # Position in pixels for scrolling
    context = Column(Text)  # Short text snippet for context
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref=db.backref('bookmarks', lazy='dynamic'))
    book = relationship('Book', backref=db.backref('bookmarks', lazy='dynamic'))

    __table_args__ = (
        Index('idx_bookmarks_user', 'user_id'),
        Index('idx_bookmarks_book', 'book_id'),
        Index('idx_bookmarks_user_book', 'user_id', 'book_id'),
    )


class Block(db.Model):
    """Examination block = 2-3 chapters"""
    __tablename__ = 'block'

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False)
    block_num = Column(Integer, nullable=False)
    grammar_key = Column(String(100), nullable=False)  # 'Present_Perfect_vs_Past_Simple'
    focus_vocab = Column(String(100))  # Topic tag
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    book = relationship("Book", back_populates="blocks")
    chapters = relationship("Chapter", secondary="block_chapter", back_populates="blocks")
    tasks = relationship("Task", back_populates="block", cascade="all, delete-orphan")
    vocabulary = relationship("BlockVocab", back_populates="block", cascade="all, delete-orphan")
    progress = relationship("UserBlockProgress", back_populates="block", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('book_id', 'block_num', name='uix_book_block'),
    )


class BlockChapter(db.Model):
    """N:M relationship between blocks and chapters"""
    __tablename__ = 'block_chapter'

    block_id = Column(Integer, ForeignKey('block.id', ondelete='CASCADE'), primary_key=True)
    chapter_id = Column(Integer, ForeignKey('chapter.id', ondelete='CASCADE'), primary_key=True)


class Task(db.Model):
    """Any exercise, stored as nested JSONB"""
    __tablename__ = 'task'

    id = Column(Integer, primary_key=True, autoincrement=True)
    block_id = Column(Integer, ForeignKey('block.id', ondelete='CASCADE'), nullable=True)  # Nullable for daily lesson tasks
    task_type = Column(SQLAEnum(TaskType, name='task_enum'), nullable=False)  # TaskType enum values
    payload = Column(JSONBCompat, nullable=False)  # Structure depends on task_type
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    block = relationship("Block", back_populates="tasks")
    daily_lesson = relationship("DailyLesson", back_populates="task", uselist=False)
    answers = relationship("UserTaskAnswer", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        # Partial unique index: (block_id, task_type) unique only when block_id is NOT NULL
        Index('uix_block_task_type_partial', 'block_id', 'task_type',
              unique=True, postgresql_where=text('block_id IS NOT NULL')),
        Index('idx_task_type', 'task_type'),
    )


class BlockVocab(db.Model):
    """15-20 'new' words for a block"""
    __tablename__ = 'block_vocab'

    block_id = Column(Integer, ForeignKey('block.id', ondelete='CASCADE'), primary_key=True)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), primary_key=True)
    freq = Column(Integer, nullable=False)
    
    # Relationships
    block = relationship("Block", back_populates="vocabulary")
    word = relationship("CollectionWords", backref="block_vocab_entries")


class UserChapterProgress(db.Model):
    """Reading position within a chapter"""
    __tablename__ = 'user_chapter_progress'

    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    chapter_id = Column(Integer, ForeignKey('chapter.id', ondelete='CASCADE'), primary_key=True)
    offset_pct = Column(Float, nullable=False)  # 0.0 to 1.0
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", backref="chapter_progress")
    chapter = relationship("Chapter", back_populates="progress")
    
    __table_args__ = (
        CheckConstraint('offset_pct >= 0 AND offset_pct <= 1', name='check_offset_pct'),
        Index('idx_progress_user', 'user_id'),
    )


class UserBlockProgress(db.Model):
    """Block test results"""
    __tablename__ = 'user_block_progress'

    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    block_id = Column(Integer, ForeignKey('block.id', ondelete='CASCADE'), primary_key=True)
    score_pct = Column(Float, nullable=False)
    attempts = Column(Integer, default=1)
    passed_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", backref="block_progress")
    block = relationship("Block", back_populates="progress")


class UserTaskAnswer(db.Model):
    """Individual task answers"""
    __tablename__ = 'user_task_answer'

    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    task_id = Column(Integer, ForeignKey('task.id', ondelete='CASCADE'), primary_key=True)
    answer = Column(JSONBCompat)  # Arbitrary format
    score = Column(Float)  # 0-100
    answered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", backref="task_answers")
    task = relationship("Task", back_populates="answers")
    
    __table_args__ = (
        Index('idx_task_answer_user', 'user_id'),
    )
