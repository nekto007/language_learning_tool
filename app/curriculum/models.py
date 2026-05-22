# app/curriculum/models.py

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, SmallInteger, String, Text, func
from sqlalchemy.orm import joinedload, relationship

from app.utils.db import db
from config.settings import PASSING_SCORE_PERCENT


class CEFRLevel(db.Model):
    """Model representing a CEFR language proficiency level (A0, A1, A2, B1, B2, C1, C2)"""
    __tablename__ = 'cefr_levels'

    id = Column(Integer, primary_key=True)
    code = Column(String(2), unique=True, nullable=False)  # A0, A1, A2, B1, B2, C1, C2
    name = Column(String(100), nullable=False)  # Pre-Beginner, Beginner, Elementary, etc.
    description = Column(Text)
    order = Column(Integer, default=0)  # For custom ordering
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    modules = relationship('Module', back_populates='level', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_cefr_levels_code', 'code'),
        Index('idx_cefr_levels_order', 'order'),
    )

    def __repr__(self):
        return f"<CEFRLevel {self.code}: {self.name}>"


class Module(db.Model):
    """Model representing a learning module within a CEFR level"""
    __tablename__ = 'modules'

    id = Column(Integer, primary_key=True)
    level_id = Column(Integer, ForeignKey('cefr_levels.id', ondelete='CASCADE'), nullable=False)
    number = Column(Integer, nullable=False)  # Module number within the level
    title = Column(String(200), nullable=False)
    description = Column(Text)
    raw_content = Column(JSON)
    prerequisites = Column(JSON)  # JSON array of prerequisite module IDs or conditions
    min_score_required = Column(Integer, default=PASSING_SCORE_PERCENT)  # Minimum score to unlock next module
    allow_skip_test = Column(Boolean, default=False)  # Allow skip test for this module
    input_mode = Column(String(50),
                        default='selection_only')  # Input difficulty: selection_only, selection_and_ordering, mixed, advanced
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    level = relationship('CEFRLevel', back_populates='modules')
    lessons = relationship('Lessons', back_populates='module', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_modules_level_number', 'level_id', 'number', unique=True),
        Index('idx_modules_level_id', 'level_id'),
        Index('idx_modules_number', 'number'),
    )

    def check_prerequisites(
        self, user_id: int, min_level_order: int | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Check if user meets prerequisites for this module.

        Args:
            user_id: target user.
            min_level_order: when provided, prerequisites that point to
                modules whose CEFR level is strictly below this order
                are ignored. Use the user's ``onboarding_level`` order
                so a placement-test C1 student isn't required to grind
                through A1-B2 modules they were placed past.

        Returns:
            tuple: (is_accessible, reasons_blocked)
        """
        reasons = []

        # No prerequisites mean always accessible
        if not self.prerequisites:
            return True, []

        # Collect all prerequisite module IDs and batch load them
        module_prereqs = [
            prereq for prereq in self.prerequisites
            if isinstance(prereq, dict) and prereq.get('type') == 'module'
        ]
        prereq_ids = [p['id'] for p in module_prereqs]

        if not prereq_ids:
            return True, []

        # Eager-load CEFRLevel so the optional min_level_order filter
        # doesn't fan out into N extra queries.
        prereq_modules = {
            m.id: m for m in (
                Module.query
                .filter(Module.id.in_(prereq_ids))
                .options(joinedload(Module.level))
                .all()
            )
        }

        # Check each prerequisite using pre-loaded modules
        for prereq in module_prereqs:
            prereq_module = prereq_modules.get(prereq['id'])
            if prereq_module is None:
                continue

            # Placement-aware skip: a C1 student shouldn't be told to
            # finish a B1 prereq they were never expected to study.
            if min_level_order is not None and prereq_module.level is not None:
                if (prereq_module.level.order or 0) < min_level_order:
                    continue

            # Check if user completed this module
            progress = self._get_module_completion(user_id, prereq['id'])
            min_score = prereq.get('min_score', PASSING_SCORE_PERCENT)

            if progress['progress_percent'] < 100:
                reasons.append(f"Complete module '{prereq_module.title}'")
            elif progress['avg_score'] < min_score:
                reasons.append(
                    f"Score {min_score}%+ in '{prereq_module.title}' (current: {progress['avg_score']:.0f}%)")

        return len(reasons) == 0, reasons

    def _get_module_completion(self, user_id: int, module_id: int) -> dict:
        """Get module completion stats for user."""
        from sqlalchemy import func

        lessons = Lessons.query.filter_by(module_id=module_id).all()
        if not lessons:
            return {'progress_percent': 0, 'avg_score': 0}

        lesson_ids = [l.id for l in lessons]
        stats = db.session.query(
            func.count(LessonProgress.id).label('completed'),
            func.avg(LessonProgress.score).label('avg_score')
        ).filter(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id.in_(lesson_ids),
            LessonProgress.status == 'completed'
        ).first()

        completed = stats.completed or 0
        avg_score = stats.avg_score or 0
        progress_percent = round((completed / len(lessons) * 100) if lessons else 0)

        return {
            'progress_percent': progress_percent,
            'avg_score': avg_score
        }

    def __repr__(self):
        return f"<Module {self.number}: {self.title} ({self.level.code if self.level else 'No Level'})>"


class Lessons(db.Model):
    """Model representing a lesson within a module"""
    __tablename__ = 'lessons'

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    number = Column(Integer, nullable=False)  # Lesson number within the module
    title = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False)  # vocabulary, grammar, quiz, matching, text, anki_cards, checkpoint
    description = Column(Text)
    order = Column(Integer, default=0)  # Order within the lesson
    content = Column(JSON)  # Flexible JSON content based on component type
    content_version = Column(Integer, default=1, nullable=False)  # Content schema version
    collection_id = Column(Integer, ForeignKey('collections.id', ondelete='SET NULL'))  # For vocabulary components
    book_id = Column(Integer, ForeignKey('book.id', ondelete='SET NULL'))  # For text components
    grammar_topic_id = Column(Integer, ForeignKey('grammar_topics.id', ondelete='SET NULL'))  # For grammar lessons
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    min_cards_required = Column(Integer, default=10)  # Минимум карточек для завершения
    min_accuracy_required = Column(Integer, default=80)  # Минимум процент правильных ответов

    @property
    def input_mode(self):
        """Get input mode from parent module"""
        return self.module.input_mode if self.module else 'mixed'

    @property
    def is_card_lesson(self):
        """Check if this is a card (SRS) lesson"""
        return self.type == 'card'

    def get_srs_settings(self):
        """Get SRS settings for this lesson"""
        if not self.is_card_lesson:
            return None

        # Default settings, can be overridden in content
        settings = {
            'min_cards_required': self.min_cards_required or 10,
            'min_accuracy_required': self.min_accuracy_required or 80,
            'new_cards_limit': 10,  # Максимум новых карточек за урок
            'show_hint_time': 7,  # Время до показа подсказки в секундах
        }

        # Override with content settings if available
        if self.content and isinstance(self.content, dict):
            settings.update(self.content.get('srs_settings', {}))

        return settings


    def validate_content_schema(self) -> tuple[bool, str]:
        """
        Validate content against schema for current version.

        Returns:
            tuple: (is_valid, error_message)
        """
        from app.curriculum.validators import LessonContentValidator
        from marshmallow import ValidationError

        try:
            return LessonContentValidator.validate(self.type, self.content)
        except ValidationError as e:
            return (False, str(e.messages), None)

    # Relationships
    module = relationship('Module', back_populates='lessons')
    collection = relationship('Collection', backref='lessons')
    book = relationship('Book', backref='lesson_components')
    grammar_topic = relationship('GrammarTopic', backref='curriculum_lessons', foreign_keys=[grammar_topic_id])
    lesson_progress = relationship(
        'LessonProgress',
        back_populates='lesson',
        cascade='all, delete-orphan'
    )
    grades = relationship(
        'LessonGrade',
        back_populates='lesson',
        cascade='all, delete-orphan'
    )
    attempts = relationship(
        'LessonAttempt',
        back_populates='lesson',
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('idx_lessons_module_number', 'module_id', 'number', unique=True),
        Index('idx_lessons_module_id', 'module_id'),
        Index('idx_lessons_type', 'type'),
        Index('idx_lessons_order', 'order'),
        Index('idx_lessons_collection_id', 'collection_id'),
        Index('idx_lessons_book_id', 'book_id'),
        Index('idx_lessons_grammar_topic_id', 'grammar_topic_id'),
        Index('idx_lessons_module_order', 'module_id', 'order'),
    )

    def __repr__(self):
        return f"<Lesson {self.number}: {self.title}>"


class LessonProgress(db.Model):
    """Model tracking user progress through individual lesson"""
    __tablename__ = 'lesson_progress'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(20), default='not_started')  # not_started, in_progress, completed
    score = Column(Float, default=0.0)  # Score for this lesson
    data = Column(JSON)  # Flexible JSON data for lesson-specific progress
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='progress')
    lesson = relationship('Lessons', back_populates='lesson_progress')
    attempts = relationship('LessonAttempt', back_populates='lesson_progress', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_lesson_progress_user_module', 'user_id', 'lesson_id', unique=True),
        Index('idx_lesson_progress_user_id', 'user_id'),
        Index('idx_lesson_progress_lesson_id', 'lesson_id'),
        Index('idx_lesson_progress_status', 'status'),
        Index('idx_lesson_progress_last_activity', 'last_activity'),
        Index('idx_lesson_progress_user_status', 'user_id', 'status'),
    )

    def __repr__(self):
        return f"<LessonProgress: Lesson {self.lesson_id} - {self.status}>"

    @property
    def rounded_score(self):
        """Returns score as a whole number"""
        return round(self.score) if self.score is not None else 0

    def set_score(self, value):
        """Sets score ensuring it's a whole number between 0 and 100"""
        if value is not None:
            self.score = max(0, min(100, round(float(value))))
        else:
            self.score = 0.0


class LessonAttempt(db.Model):
    """Model tracking individual attempts at lessons for analytics"""
    __tablename__ = 'lesson_attempts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    lesson_progress_id = Column(Integer, ForeignKey('lesson_progress.id', ondelete='CASCADE'))

    attempt_number = Column(Integer, nullable=False)  # 1, 2, 3, etc.
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime)
    time_spent_seconds = Column(Integer)  # Time spent in seconds

    score = Column(Float)  # Score achieved (0-100)
    passed = Column(Boolean)  # Whether passed (score >= passing_score)

    # Detailed analytics
    mistakes = Column(JSON)  # Array of mistakes with question IDs and answers
    correct_answers = Column(Integer, default=0)
    total_questions = Column(Integer, default=0)

    # Additional metadata
    device_info = Column(String(200))  # Browser/device info
    ip_address = Column(String(45))  # IPv4 or IPv6
    user_agent = Column(Text)

    # Relationships
    user = relationship('User', backref='lesson_attempts')
    lesson = relationship('Lessons', back_populates='attempts')
    lesson_progress = relationship('LessonProgress', back_populates='attempts')

    __table_args__ = (
        Index('idx_attempts_user_lesson', 'user_id', 'lesson_id'),
        Index('idx_attempts_user_id', 'user_id'),
        Index('idx_attempts_lesson_id', 'lesson_id'),
        Index('idx_attempts_started_at', 'started_at'),
        Index('idx_attempts_score', 'score'),
        Index('idx_attempts_passed', 'passed'),
    )

    def __repr__(self):
        return f"<LessonAttempt: User {self.user_id} - Lesson {self.lesson_id} - Attempt #{self.attempt_number}>"

    @classmethod
    def create_attempt(cls, user_id: int, lesson_id: int, lesson_progress_id: int = None):
        """Create a new attempt and determine attempt number."""
        # Get last attempt number
        last_attempt = db.session.query(func.max(cls.attempt_number)).filter(
            cls.user_id == user_id,
            cls.lesson_id == lesson_id
        ).scalar() or 0

        attempt = cls(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson_progress_id=lesson_progress_id,
            attempt_number=last_attempt + 1
        )
        db.session.add(attempt)
        return attempt

    def complete(self, score: float, mistakes: list = None, correct: int = 0, total: int = 0):
        """Mark attempt as completed with results."""
        self.completed_at = datetime.now(timezone.utc)
        self.score = score
        self.passed = score >= 70 if score is not None else False  # Default passing score
        self.mistakes = mistakes or []
        self.correct_answers = correct
        self.total_questions = total

        if self.started_at and self.completed_at:
            # Ensure both datetimes are timezone-aware
            started = self.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)

            completed = self.completed_at
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)

            delta = completed - started
            self.time_spent_seconds = int(delta.total_seconds())


class ListeningAttempt(db.Model):
    """Tracks each dictation/audio_fill_blank submission for analytics."""
    __tablename__ = 'listening_attempts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    score = Column(Float, nullable=False)
    replay_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_listening_attempts_user_created', 'user_id', 'created_at'),
        Index('idx_listening_attempts_lesson', 'lesson_id'),
    )

    def __repr__(self) -> str:
        return f'<ListeningAttempt id={self.id} user={self.user_id} lesson={self.lesson_id} score={self.score}>'


class PronunciationAttempt(db.Model):
    """Tracks each pronunciation item attempt for analytics and weakness detection."""
    __tablename__ = 'pronunciation_attempts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    word = Column(db.String(200), nullable=False)
    recognized_text = Column(db.String(500), nullable=False, default='')
    matched = Column(db.Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_pronunciation_attempts_user_created', 'user_id', 'created_at'),
        Index('idx_pronunciation_attempts_word', 'word'),
    )

    def __repr__(self) -> str:
        return (
            f'<PronunciationAttempt id={self.id} user={self.user_id} '
            f'word="{self.word}" matched={self.matched}>'
        )


class UserWritingAttempt(db.Model):
    """Tracks each writing_prompt submission for analytics and history."""
    __tablename__ = 'user_writing_attempts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    response_text = Column(db.Text, nullable=False)
    word_count = Column(Integer, nullable=False, default=0)
    checklist_completed = Column(db.Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_writing_attempts_user_created', 'user_id', 'created_at'),
        Index('idx_writing_attempts_user_lesson', 'user_id', 'lesson_id'),
    )

    def __repr__(self) -> str:
        return (
            f'<UserWritingAttempt id={self.id} user={self.user_id} '
            f'lesson={self.lesson_id} words={self.word_count}>'
        )


def save_writing_attempt(
    user_id: int,
    lesson_id: int,
    text: str,
    checklist_completed: bool,
    db_session,
) -> 'UserWritingAttempt':
    """Persist a writing attempt and return the new row.

    Word count is computed from the submitted text. Multiple attempts per
    lesson are allowed — each submission creates a new row.
    Caller owns the commit.
    """
    word_count = len(text.split()) if text.strip() else 0
    attempt = UserWritingAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        response_text=text,
        word_count=word_count,
        checklist_completed=checklist_completed,
    )
    db_session.session.add(attempt)
    db_session.session.flush()
    return attempt


class WordCollocation(db.Model):
    """Collocation phrases associated with a vocabulary word."""
    __tablename__ = 'word_collocations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)
    collocation_phrase = Column(Text, nullable=False)
    translation = Column(Text, nullable=False)
    example = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_word_collocations_word_id', 'word_id'),
    )

    def __repr__(self) -> str:
        return f'<WordCollocation id={self.id} word_id={self.word_id} phrase="{self.collocation_phrase}">'


def get_collocations_for_word(word_id: int, db_session) -> list['WordCollocation']:
    """Return all collocations for a given word, ordered by id."""
    return (
        db_session.session.query(WordCollocation)
        .filter(WordCollocation.word_id == word_id)
        .order_by(WordCollocation.id)
        .all()
    )


class VocabAnnotation(db.Model):
    """User personal notes on vocabulary words."""
    __tablename__ = 'vocab_annotations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)
    note = Column(Text, nullable=False)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_vocab_annotations_user_word', 'user_id', 'word_id', unique=True),
        Index('idx_vocab_annotations_user_id', 'user_id'),
    )

    def __repr__(self) -> str:
        return f'<VocabAnnotation id={self.id} user={self.user_id} word={self.word_id}>'


def get_annotation_for_word(user_id: int, word_id: int, db_session) -> 'VocabAnnotation | None':
    """Return the user's annotation for a word, or None."""
    return (
        db_session.session.query(VocabAnnotation)
        .filter(VocabAnnotation.user_id == user_id, VocabAnnotation.word_id == word_id)
        .first()
    )


def save_annotation(user_id: int, word_id: int, note: str, db_session) -> 'VocabAnnotation':
    """Upsert a user annotation for a word. Caller owns the commit."""
    annotation = (
        db_session.session.query(VocabAnnotation)
        .filter(VocabAnnotation.user_id == user_id, VocabAnnotation.word_id == word_id)
        .first()
    )
    if annotation is None:
        annotation = VocabAnnotation(user_id=user_id, word_id=word_id, note=note)
        db_session.session.add(annotation)
    else:
        annotation.note = note
        annotation.added_at = datetime.now(timezone.utc)
    db_session.session.flush()
    return annotation


class DailyStudyMinutes(db.Model):
    """Accumulates study time per user per day across all slot completions."""
    __tablename__ = 'daily_study_minutes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    study_date = Column(Date, nullable=False)
    minutes = Column(SmallInteger, nullable=False, default=0)

    __table_args__ = (
        Index('idx_daily_study_minutes_user_date', 'user_id', 'study_date', unique=True),
    )

    def __repr__(self) -> str:
        return f'<DailyStudyMinutes user={self.user_id} date={self.study_date} minutes={self.minutes}>'


def add_study_minutes(
    user_id: int,
    study_date,
    minutes: int,
    db_session,
) -> 'DailyStudyMinutes':
    """Add minutes to the user's study total for study_date.

    Upserts: increments existing row or creates a new one. Caller owns
    the commit.
    """
    row = (
        db_session.session.query(DailyStudyMinutes)
        .filter(DailyStudyMinutes.user_id == user_id, DailyStudyMinutes.study_date == study_date)
        .first()
    )
    if row is None:
        row = DailyStudyMinutes(user_id=user_id, study_date=study_date, minutes=minutes)
        db_session.session.add(row)
    else:
        row.minutes = (row.minutes or 0) + minutes
    db_session.session.flush()
    return row


def get_minutes_today(user_id: int, study_date, db_session) -> int:
    """Return total study minutes recorded for user on study_date."""
    row = (
        db_session.session.query(DailyStudyMinutes)
        .filter(DailyStudyMinutes.user_id == user_id, DailyStudyMinutes.study_date == study_date)
        .first()
    )
    return row.minutes if row else 0


class CulturalNote(db.Model):
    """Contextual cultural notes about word usage."""
    __tablename__ = 'cultural_notes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)
    note = Column(Text, nullable=False)
    context = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_cultural_notes_word_id', 'word_id'),
    )

    def __repr__(self) -> str:
        return f'<CulturalNote id={self.id} word_id={self.word_id} context="{self.context}">'


def get_cultural_notes_for_word(word_id: int, db_session) -> list['CulturalNote']:
    """Return all cultural notes for a given word, ordered by id."""
    return (
        db_session.session.query(CulturalNote)
        .filter(CulturalNote.word_id == word_id)
        .order_by(CulturalNote.id)
        .all()
    )


class LessonFeedback(db.Model):
    """User thumbs up/down feedback for a completed lesson. One row per user per lesson (upsert)."""
    __tablename__ = 'lesson_feedback'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
    rating = Column(SmallInteger, nullable=False)  # 1-5; thumbs down = 1, thumbs up = 5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index('idx_lesson_feedback_user_lesson', 'user_id', 'lesson_id', unique=True),
        Index('idx_lesson_feedback_lesson_id', 'lesson_id'),
    )

    def __repr__(self) -> str:
        return f'<LessonFeedback id={self.id} user_id={self.user_id} lesson_id={self.lesson_id} rating={self.rating}>'


def save_lesson_feedback(user_id: int, lesson_id: int, rating: int, comment: str | None, db_session) -> 'LessonFeedback':
    """Upsert lesson feedback for a user. Rating must be 1-5."""
    row = (
        db_session.session.query(LessonFeedback)
        .filter(LessonFeedback.user_id == user_id, LessonFeedback.lesson_id == lesson_id)
        .first()
    )
    if row is None:
        row = LessonFeedback(user_id=user_id, lesson_id=lesson_id, rating=rating, comment=comment)
        db_session.session.add(row)
    else:
        row.rating = rating
        row.comment = comment
    db_session.session.flush()
    return row


# Import LessonGrade to register it with SQLAlchemy
# This needs to be at the end of the file to avoid circular imports
from app.achievements.models import LessonGrade  # noqa: F401, E402

