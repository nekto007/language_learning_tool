# app/words/models.py

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from app.utils.db import db


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
    frequency_rank = Column(Integer, default=0)

    books = relationship("Book", secondary="word_book_link", back_populates="words")
    phrasal_verbs = relationship("PhrasalVerb", back_populates="base_word")

    topics = relationship("Topic", secondary="topic_words", back_populates="words")
    collections = relationship("Collection", secondary="collection_words_link", back_populates="words")

    __table_args__ = (
        Index('idx_collection_words_english_word', 'english_word'),
        Index('idx_collection_words_frequency_rank', 'frequency_rank'),
    )


class Topic(db.Model):
    __tablename__ = 'topics'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    words = relationship('CollectionWords', secondary='topic_words', back_populates='topics')
    creator = relationship('User', backref='created_topics')

    def __repr__(self):
        return f"<Topic {self.name}>"


class TopicWord(db.Model):
    __tablename__ = 'topic_words'

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('topics.id', ondelete='CASCADE'))
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'))

    __table_args__ = (
        Index('idx_topic_words_topic_id', 'topic_id'),
        Index('idx_topic_words_word_id', 'word_id'),
    )


class Collection(db.Model):
    __tablename__ = 'collections'

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    words = relationship('CollectionWords', secondary='collection_words_link', back_populates='collections')
    creator = relationship('User', backref='created_collections')

    def __repr__(self):
        return f"<Collection {self.name}>"

    @hybrid_property
    def word_count(self) -> int:
        """Возвращает количество слов в коллекции"""
        return len(self.words)

    @word_count.expression
    def word_count(cls):
        """Позволяет сортировать/фильтровать напрямую в SQL."""
        return (
            select(func.count(collection_words.c.word_id))
            .where(collection_words.c.collection_id == cls.id)
            .correlate(cls)
            .label("word_count")
        )

    @property
    def topics(self):
        """Возвращает список уникальных тем из слов коллекции"""
        topics_set = set()
        for word in self.words:
            for topic in word.topics:
                topics_set.add(topic)
        return list(topics_set)


class CollectionWordLink(db.Model):
    __tablename__ = 'collection_words_link'

    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey('collections.id', ondelete='CASCADE'))
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'))

    __table_args__ = (
        Index('idx_collection_words_link_collection_id', 'collection_id'),
        Index('idx_collection_words_link_word_id', 'word_id'),
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
