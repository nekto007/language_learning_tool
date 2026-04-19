"""SQLAlchemy models for the linear daily plan feature."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship

from app.utils.db import db
from app.utils.types import JSONBCompat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserReadingPreference(db.Model):
    """Selected reading book per user for the linear daily plan reading slot."""

    __tablename__ = 'user_reading_preference'

    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
        nullable=False,
    )
    book_id = Column(
        Integer,
        ForeignKey('book.id', ondelete='CASCADE'),
        nullable=False,
    )
    selected_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship('User', backref='reading_preference')
    book = relationship('Book')

    __table_args__ = (
        Index('idx_user_reading_preference_book', 'book_id'),
    )

    def __repr__(self) -> str:
        return f'<UserReadingPreference user={self.user_id} book={self.book_id}>'


class QuizErrorLog(db.Model):
    """One row per incorrect quiz answer, surfaced later via the error-review slot."""

    __tablename__ = 'quiz_error_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    lesson_id = Column(
        Integer,
        ForeignKey('lessons.id', ondelete='CASCADE'),
        nullable=False,
    )
    question_payload = Column(JSONBCompat, nullable=False)
    answered_wrong_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship('User', backref='quiz_error_logs')
    lesson = relationship('Lessons')

    __table_args__ = (
        Index('idx_quiz_error_log_user_resolved', 'user_id', 'resolved_at'),
        Index('idx_quiz_error_log_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self) -> str:
        return f'<QuizErrorLog id={self.id} user={self.user_id} resolved={self.resolved_at is not None}>'


class GrammarTheoryView(db.Model):
    """Records when a grammar theory panel is shown inside a curriculum lesson."""

    __tablename__ = 'grammar_theory_view'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    topic_id = Column(
        Integer,
        ForeignKey('grammar_topics.id', ondelete='CASCADE'),
        nullable=False,
    )
    lesson_id = Column(
        Integer,
        ForeignKey('lessons.id', ondelete='CASCADE'),
        nullable=False,
    )
    shown_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship('User', backref='grammar_theory_views')
    topic = relationship('GrammarTopic')
    lesson = relationship('Lessons')

    __table_args__ = (
        Index('idx_grammar_theory_view_user_lesson', 'user_id', 'lesson_id'),
    )

    def __repr__(self) -> str:
        return (
            f'<GrammarTheoryView id={self.id} user={self.user_id} '
            f'topic={self.topic_id} lesson={self.lesson_id}>'
        )
