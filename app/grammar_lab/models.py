# app/grammar_lab/models.py
"""
Database models for Grammar Lab module.

Models:
- GrammarTopic: Grammar topic (e.g., Present Perfect, Articles)
- GrammarExercise: Exercise for a topic
- UserGrammarProgress: User's progress on a topic
- GrammarAttempt: Individual exercise attempt
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.utils.db import db


class GrammarTopic(db.Model):
    """Grammar topic (e.g., Present Perfect, Articles)"""
    __tablename__ = 'grammar_topics'

    id = Column(Integer, primary_key=True)

    # Identification
    slug = Column(String(100), unique=True, nullable=False)  # "present-perfect"
    title = Column(String(200), nullable=False)               # "Present Perfect"
    title_ru = Column(String(200), nullable=False)            # "Настоящее совершённое"

    # Level and order
    level = Column(String(10), nullable=False)  # A1, A2, B1, B2, C1, C2
    order = Column(Integer, default=0)          # Order within level

    # Content (JSONB)
    content = Column(JSONB, nullable=False, default={})
    # {
    #   "introduction": "Brief introduction",
    #   "sections": [
    #     {
    #       "subtitle": "Formation",
    #       "description": "have/has + V3",
    #       "table": [{...}],
    #       "rules": [{...}],
    #       "examples": [{...}]
    #     }
    #   ],
    #   "important_notes": ["Note 1", ...],
    #   "common_mistakes": [{"wrong": "...", "correct": "...", "explanation": "..."}],
    #   "summary_table": {...},
    #   "related_topics": ["past-simple", "present-simple"]
    # }

    # Metadata
    estimated_time = Column(Integer, default=15)  # minutes to study
    difficulty = Column(Integer, default=1)        # 1-5 difficulty

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    exercises = relationship('GrammarExercise', back_populates='topic',
                            cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        Index('idx_grammar_topics_level', 'level'),
        Index('idx_grammar_topics_slug', 'slug'),
    )

    def __repr__(self):
        return f"<GrammarTopic {self.id}: {self.title} ({self.level})>"

    @property
    def exercise_count(self):
        return self.exercises.count()

    def to_dict(self, include_content=False):
        """Convert to dictionary for JSON response"""
        data = {
            'id': self.id,
            'slug': self.slug,
            'title': self.title,
            'title_ru': self.title_ru,
            'level': self.level,
            'order': self.order,
            'estimated_time': self.estimated_time,
            'difficulty': self.difficulty,
            'exercise_count': self.exercise_count
        }
        if include_content:
            data['content'] = self.content
        return data


class GrammarExercise(db.Model):
    """Exercise for a grammar topic"""
    __tablename__ = 'grammar_exercises'

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('grammar_topics.id', ondelete='CASCADE'), nullable=False)

    # Exercise type
    exercise_type = Column(String(50), nullable=False)
    # Types: fill_blank, multiple_choice, reorder, translation,
    #        error_correction, transformation, matching

    # Content (JSONB)
    content = Column(JSONB, nullable=False)
    # {
    #   "question": "I ___ (to be) a student.",
    #   "correct_answer": "am",
    #   "alternatives": ["I'm"],  # optional alternative correct answers
    #   "options": ["am", "is", "are", "be"],  # for multiple_choice
    #   "explanation": "With pronoun I, use am",
    #   "hint": "Optional hint",
    #   "audio_url": "path/to/audio.mp3"
    # }

    difficulty = Column(Integer, default=1)  # 1-3
    order = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    topic = relationship('GrammarTopic', back_populates='exercises')

    __table_args__ = (
        Index('idx_grammar_exercises_topic', 'topic_id'),
    )

    def __repr__(self):
        return f"<GrammarExercise {self.id}: {self.exercise_type}>"

    def to_dict(self, hide_answer=False):
        """Convert to dictionary for JSON response"""
        data = {
            'id': self.id,
            'topic_id': self.topic_id,
            'exercise_type': self.exercise_type,
            'difficulty': self.difficulty,
            'order': self.order,
            'question': self.content.get('question', ''),
            'options': self.content.get('options', []),
            'hint': self.content.get('hint'),
            'instruction': self.content.get('instruction', ''),
        }

        # For reorder type
        if self.exercise_type == 'reorder':
            data['words'] = self.content.get('words', [])

        # For matching type
        if self.exercise_type == 'matching':
            data['pairs'] = self.content.get('pairs', [])

        # For error_correction type
        if self.exercise_type == 'error_correction':
            data['sentence'] = self.content.get('sentence', '')

        # For transformation type
        if self.exercise_type == 'transformation':
            data['original'] = self.content.get('original', '')

        # For translation type
        if self.exercise_type == 'translation':
            data['sentence'] = self.content.get('sentence', '')
            data['source_lang'] = self.content.get('source_lang', 'ru')
            data['target_lang'] = self.content.get('target_lang', 'en')

        if not hide_answer:
            data['correct_answer'] = self.content.get('correct_answer')
            data['alternatives'] = self.content.get('alternatives', [])
            data['explanation'] = self.content.get('explanation', '')

        return data


class UserGrammarProgress(db.Model):
    """User's progress on a grammar topic"""
    __tablename__ = 'user_grammar_progress'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    topic_id = Column(Integer, ForeignKey('grammar_topics.id', ondelete='CASCADE'), nullable=False)

    # Study status
    theory_completed = Column(Boolean, default=False)
    theory_completed_at = Column(DateTime)

    # Practice (SRS-like system)
    mastery_level = Column(Integer, default=0)  # 0-5 (0=new, 5=mastered)
    correct_streak = Column(Integer, default=0)
    total_attempts = Column(Integer, default=0)
    correct_attempts = Column(Integer, default=0)

    # SRS parameters
    ease_factor = Column(Float, default=2.5)
    interval = Column(Integer, default=0)  # days until next review
    next_review = Column(DateTime)
    last_reviewed = Column(DateTime)

    # Error stats by exercise type
    error_stats = Column(JSONB, default={})
    # {"fill_blank": {"attempts": 10, "correct": 7}, ...}

    # XP and time
    xp_earned = Column(Integer, default=0)
    time_spent = Column(Integer, default=0)  # seconds

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='grammar_progress')
    topic = relationship('GrammarTopic', backref='user_progress')

    __table_args__ = (
        UniqueConstraint('user_id', 'topic_id', name='uq_user_grammar_topic'),
        Index('idx_user_grammar_progress_user', 'user_id'),
        Index('idx_user_grammar_progress_next_review', 'user_id', 'next_review'),
    )

    def __repr__(self):
        return f"<UserGrammarProgress user={self.user_id} topic={self.topic_id} level={self.mastery_level}>"

    @property
    def accuracy(self):
        """Calculate accuracy percentage"""
        if self.total_attempts == 0:
            return 0
        return round((self.correct_attempts / self.total_attempts) * 100, 1)

    @property
    def mastery_label(self):
        """Get human-readable mastery level label"""
        labels = {
            0: 'new',
            1: 'learning',
            2: 'reviewing',
            3: 'familiar',
            4: 'confident',
            5: 'mastered'
        }
        return labels.get(self.mastery_level, 'unknown')

    def to_dict(self):
        """Convert to dictionary for JSON response"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'topic_id': self.topic_id,
            'theory_completed': self.theory_completed,
            'mastery_level': self.mastery_level,
            'mastery_label': self.mastery_label,
            'correct_streak': self.correct_streak,
            'total_attempts': self.total_attempts,
            'correct_attempts': self.correct_attempts,
            'accuracy': self.accuracy,
            'xp_earned': self.xp_earned,
            'next_review': self.next_review.isoformat() if self.next_review else None,
            'last_reviewed': self.last_reviewed.isoformat() if self.last_reviewed else None
        }


class GrammarAttempt(db.Model):
    """Individual exercise attempt record"""
    __tablename__ = 'grammar_attempts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    exercise_id = Column(Integer, ForeignKey('grammar_exercises.id', ondelete='CASCADE'), nullable=False)

    # Result
    is_correct = Column(Boolean, nullable=False)
    user_answer = Column(Text)
    time_spent = Column(Integer)  # seconds

    # Context
    session_id = Column(String(100))  # for grouping attempts in a session
    source = Column(String(50))  # 'topic_practice', 'srs_review', 'daily_lesson'

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='grammar_attempts')
    exercise = relationship('GrammarExercise', backref='attempts')

    __table_args__ = (
        Index('idx_grammar_attempts_user', 'user_id'),
        Index('idx_grammar_attempts_exercise', 'exercise_id'),
        Index('idx_grammar_attempts_session', 'session_id'),
    )

    def __repr__(self):
        return f"<GrammarAttempt user={self.user_id} exercise={self.exercise_id} correct={self.is_correct}>"
