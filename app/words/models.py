from app.utils.db import db
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime


class CollectionWords(db.Model):
    __tablename__ = 'collection_words'

    id = Column(Integer, primary_key=True, autoincrement=True)
    english_word = Column(String(255), unique=True, nullable=False)
    russian_word = Column(String(255))
    listening = Column(Text)
    sentences = Column(Text)
    level = Column(String(10))  # A1, A2, B1, B2, C1, C2
    brown = Column(Integer, default=0)
    get_download = Column(Integer, default=0)
    learning_status = Column(Integer, default=0)

    books = relationship("Book", secondary="word_book_link", back_populates="words")
    users = relationship("User", secondary="user_word_status", back_populates="words")
    phrasal_verbs = relationship("PhrasalVerb", back_populates="base_word")

    __table_args__ = (
        Index('idx_collection_words_english_word', 'english_word'),
        Index('idx_collection_words_learning_status', 'learning_status'),
    )


class PhrasalVerb(db.Model):
    __tablename__ = 'phrasal_verb'

    id = Column(Integer, primary_key=True, autoincrement=True)
    phrasal_verb = Column(String(255), unique=True, nullable=False)
    russian_translate = Column(String(255))
    using = Column(Text)
    sentence = Column(Text)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='SET NULL'))
    listening = Column(Text)
    get_download = Column(Integer, default=0)

    base_word = relationship("CollectionWords", back_populates="phrasal_verbs")