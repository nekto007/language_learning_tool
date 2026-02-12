# app/grammar_lab/models.py
"""
Database models for Grammar Lab module.

Models:
- GrammarTopic: Grammar topic (e.g., Present Perfect, Articles)
- GrammarExercise: Exercise for a topic
- UserGrammarProgress: User's progress on a topic
- GrammarAttempt: Individual exercise attempt
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.utils.db import db
from app.utils.types import JSONBCompat


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
    content = Column(JSONBCompat, nullable=False, default={})
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

    # Telegram mini-summary (2-4 bullets + example, for morning reminders)
    telegram_summary = Column(Text, nullable=True)

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
    content = Column(JSONBCompat, nullable=False)
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
            data['sentence'] = self.content.get('sentence') or self.content.get('question', '')

        # For transformation type
        if self.exercise_type == 'transformation':
            data['original'] = self.content.get('original') or self.content.get('question', '')

        # For translation type
        if self.exercise_type == 'translation':
            data['sentence'] = self.content.get('sentence', '')
            data['source_lang'] = self.content.get('source_lang', 'ru')
            data['target_lang'] = self.content.get('target_lang', 'en')

        # For true_false type
        if self.exercise_type == 'true_false':
            data['statement'] = self.content.get('statement') or self.content.get('question', '')

        if not hide_answer:
            data['correct_answer'] = self.content.get('correct_answer')
            data['alternatives'] = self.content.get('alternatives', [])
            data['explanation'] = self.content.get('explanation', '')

        return data


class UserGrammarTopicStatus(db.Model):
    """
    Minimal user status for a grammar topic.

    Only stores non-computable data:
    - theory_completed: whether user read the theory
    - xp_earned: accumulated XP (expensive to compute)

    All SRS data is in UserGrammarExercise (exercise-level).
    """
    __tablename__ = 'user_grammar_topic_status'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    topic_id = Column(Integer, ForeignKey('grammar_topics.id', ondelete='CASCADE'), nullable=False)

    # Theory status
    theory_completed = Column(Boolean, default=False)
    theory_completed_at = Column(DateTime)

    # Topic status: 'new', 'theory_completed', 'practicing', 'mastered'
    status = Column(String(20), default='new', nullable=False)

    # XP (stored to avoid expensive recalculation)
    xp_earned = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='grammar_topic_status')
    topic = relationship('GrammarTopic', backref='user_status')

    __table_args__ = (
        UniqueConstraint('user_id', 'topic_id', name='uq_user_grammar_topic_status'),
        Index('idx_user_grammar_topic_status_user', 'user_id'),
    )

    def __repr__(self):
        return f"<UserGrammarTopicStatus user={self.user_id} topic={self.topic_id}>"

    @classmethod
    def get_or_create(cls, user_id: int, topic_id: int):
        """Get existing status or create new one"""
        status = cls.query.filter_by(user_id=user_id, topic_id=topic_id).first()
        if not status:
            status = cls(user_id=user_id, topic_id=topic_id)
            db.session.add(status)
            db.session.flush()
        return status

    def add_xp(self, amount: int):
        """Add XP to this topic"""
        self.xp_earned = (self.xp_earned or 0) + amount

    def transition_to(self, new_status: str) -> bool:
        """Transition to new status if valid. Returns True if transitioned."""
        VALID_TRANSITIONS = {
            'new': ['theory_completed'],
            'theory_completed': ['practicing'],
            'practicing': ['mastered'],
            'mastered': ['practicing'],  # regression
        }
        if new_status in VALID_TRANSITIONS.get(self.status, []):
            self.status = new_status
            if new_status == 'theory_completed' and not self.theory_completed:
                self.theory_completed = True
                self.theory_completed_at = datetime.now(timezone.utc)
            return True
        return False

    def to_dict(self):
        """Convert to dictionary for JSON response"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'topic_id': self.topic_id,
            'status': self.status,
            'theory_completed': self.theory_completed,
            'theory_completed_at': self.theory_completed_at.isoformat() if self.theory_completed_at else None,
            'xp_earned': self.xp_earned or 0,
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


class UserGrammarExercise(db.Model):
    """
    SRS state for a specific exercise per user.
    Analogous to UserCardDirection for words.

    Anki-like state machine:
        NEW → LEARNING → REVIEW ⟷ RELEARNING
    """
    __tablename__ = 'user_grammar_exercises'

    # Thresholds for mature/mastered (in days)
    MATURE_THRESHOLD_DAYS = 21
    MASTERED_THRESHOLD_DAYS = 180

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    exercise_id = Column(Integer, ForeignKey('grammar_exercises.id', ondelete='CASCADE'), nullable=False)

    # Anki-like card state: 'new', 'learning', 'review', 'relearning'
    state = Column(String(15), default='new', nullable=False)

    # Learning step index (0-based, for LEARNING and RELEARNING states)
    step_index = Column(Integer, default=0, nullable=False)

    # Lapse count (number of times exercise went from REVIEW to RELEARNING)
    lapses = Column(Integer, default=0, nullable=False)

    # SM-2 parameters
    ease_factor = Column(Float, default=2.5, nullable=False)
    interval = Column(Integer, default=0, nullable=False)  # days
    repetitions = Column(Integer, default=0, nullable=False)

    # Scheduling
    next_review = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_reviewed = Column(DateTime, nullable=True)
    first_reviewed = Column(DateTime, nullable=True)  # When exercise was first studied
    buried_until = Column(DateTime, nullable=True)  # Card won't be shown until this timestamp

    # Stats
    correct_count = Column(Integer, default=0, nullable=False)
    incorrect_count = Column(Integer, default=0, nullable=False)
    session_attempts = Column(Integer, default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='grammar_exercise_progress')
    exercise = relationship('GrammarExercise', backref='user_progress')

    __table_args__ = (
        UniqueConstraint('user_id', 'exercise_id', name='uq_user_grammar_exercise'),
        Index('idx_user_grammar_exercise_user', 'user_id'),
        Index('idx_user_grammar_exercise_next_review', 'user_id', 'next_review'),
        Index('idx_user_grammar_exercise_state', 'state'),
        Index('idx_user_grammar_exercise_buried', 'buried_until'),
    )

    def __init__(self, user_id, exercise_id):
        self.user_id = user_id
        self.exercise_id = exercise_id
        self.state = 'new'
        self.step_index = 0
        self.lapses = 0
        self.ease_factor = 2.5
        self.interval = 0
        self.repetitions = 0
        self.correct_count = 0
        self.incorrect_count = 0
        self.session_attempts = 0
        self.next_review = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<UserGrammarExercise user={self.user_id} exercise={self.exercise_id} state={self.state}>"

    @classmethod
    def get_or_create(cls, user_id: int, exercise_id: int):
        """Get existing progress or create new one"""
        progress = cls.query.filter_by(user_id=user_id, exercise_id=exercise_id).first()
        if not progress:
            progress = cls(user_id=user_id, exercise_id=exercise_id)
            db.session.add(progress)
            db.session.flush()
        return progress

    @property
    def is_due(self) -> bool:
        """Check if this exercise is due for review"""
        if not self.next_review:
            return True
        if self.next_review.tzinfo is None:
            next_review_aware = self.next_review.replace(tzinfo=timezone.utc)
        else:
            next_review_aware = self.next_review
        return datetime.now(timezone.utc) >= next_review_aware

    @property
    def is_buried(self) -> bool:
        """Check if this exercise is currently buried"""
        if not self.buried_until:
            return False
        if self.buried_until.tzinfo is None:
            buried_aware = self.buried_until.replace(tzinfo=timezone.utc)
        else:
            buried_aware = self.buried_until
        return datetime.now(timezone.utc) < buried_aware

    @property
    def is_mature(self) -> bool:
        """Exercise is mature if in review state with interval >= 21 days"""
        return self.state == 'review' and self.interval >= self.MATURE_THRESHOLD_DAYS

    @property
    def is_mastered(self) -> bool:
        """Exercise is mastered if in review state with interval >= 180 days"""
        return self.state == 'review' and self.interval >= self.MASTERED_THRESHOLD_DAYS

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage"""
        total = self.correct_count + self.incorrect_count
        if total == 0:
            return 0.0
        return round((self.correct_count / total) * 100, 1)

    def bury(self, hours: int = 24):
        """Bury this exercise - it won't be shown until the specified time"""
        self.buried_until = datetime.now(timezone.utc) + timedelta(hours=hours)

    def unbury(self):
        """Remove bury status from this exercise"""
        self.buried_until = None

    def to_dict(self):
        """Convert to dictionary for JSON response"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'exercise_id': self.exercise_id,
            'state': self.state,
            'step_index': self.step_index,
            'lapses': self.lapses,
            'ease_factor': self.ease_factor,
            'interval': self.interval,
            'repetitions': self.repetitions,
            'correct_count': self.correct_count,
            'incorrect_count': self.incorrect_count,
            'accuracy': self.accuracy,
            'is_due': self.is_due,
            'is_buried': self.is_buried,
            'is_mature': self.is_mature,
            'is_mastered': self.is_mastered,
            'next_review': self.next_review.isoformat() if self.next_review else None,
            'last_reviewed': self.last_reviewed.isoformat() if self.last_reviewed else None,
        }
