# app/curriculum/models.py

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from app.utils.db import db


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
    min_score_required = Column(Integer, default=70)  # Minimum score to unlock next module
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

    def check_prerequisites(self, user_id: int) -> tuple[bool, list[str]]:
        """
        Check if user meets prerequisites for this module.

        Returns:
            tuple: (is_accessible, reasons_blocked)
        """
        reasons = []

        # No prerequisites mean always accessible
        if not self.prerequisites:
            return True, []

        # Check each prerequisite
        for prereq in self.prerequisites:
            if isinstance(prereq, dict):
                # Format: {"type": "module", "id": 5, "min_score": 80}
                if prereq.get('type') == 'module':
                    prereq_module = Module.query.get(prereq['id'])
                    if prereq_module:
                        # Check if user completed this module
                        progress = self._get_module_completion(user_id, prereq['id'])
                        min_score = prereq.get('min_score', 70)

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

    # def migrate_content_to_latest(self):
    #     """
    #     Migrate content to the latest schema version.
    #
    #     Returns:
    #         bool: True if migration was performed, False if already at latest version
    #     """
    #     from app.curriculum.services.content_migration_service import ContentMigrationService
    #
    #     current_version = self.content_version or 1
    #     latest_version = ContentMigrationService.LATEST_VERSION
    #
    #     if current_version >= latest_version:
    #         return False
    #
    #     try:
    #         # Migrate content
    #         migrated_content = ContentMigrationService.migrate_content(
    #             self.type,
    #             self.content,
    #             from_version=current_version,
    #             to_version=latest_version
    #         )
    #
    #         if migrated_content:
    #             self.content = migrated_content
    #             self.content_version = latest_version
    #             self.updated_at = datetime.now(timezone.utc)
    #             return True
    #
    #         return False
    #
    #     except Exception as e:
    #         import logging
    #         logger = logging.getLogger(__name__)
    #         logger.error(f"Failed to migrate content for lesson {self.id}: {str(e)}")
    #         return False

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


class ModuleSkipTest(db.Model):
    """Model for skip tests that allow users to bypass modules"""
    __tablename__ = 'module_skip_tests'

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)

    # Test content
    content = Column(JSON, nullable=False)  # Quiz-like format with questions
    passing_score = Column(Integer, default=80, nullable=False)
    time_limit_minutes = Column(Integer, default=30)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    module = relationship('Module', backref='skip_test')
    attempts = relationship('SkipTestAttempt', back_populates='skip_test', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_skip_tests_module', 'module_id'),
    )

    def __repr__(self):
        return f"<ModuleSkipTest: Module {self.module_id} - {self.title}>"


class SkipTestAttempt(db.Model):
    """Model tracking skip test attempts"""
    __tablename__ = 'skip_test_attempts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    module_id = Column(Integer, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    skip_test_id = Column(Integer, ForeignKey('module_skip_tests.id', ondelete='CASCADE'), nullable=False)

    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime)
    score = Column(Float)
    passed = Column(Boolean)

    # Detailed results
    answers = Column(JSON)  # User's answers
    time_spent_seconds = Column(Integer)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='skip_test_attempts')
    module = relationship('Module', backref='skip_test_attempts_rel')
    skip_test = relationship('ModuleSkipTest', back_populates='attempts')

    __table_args__ = (
        Index('idx_skip_attempts_user_module', 'user_id', 'module_id'),
        Index('idx_skip_attempts_passed', 'passed'),
    )

    def __repr__(self):
        return f"<SkipTestAttempt: User {self.user_id} - Module {self.module_id}>"

    def complete(self, score: float, answers: dict):
        """Mark attempt as completed."""
        self.completed_at = datetime.now(timezone.utc)
        self.score = score
        self.passed = score >= (self.skip_test.passing_score if self.skip_test else 80)
        self.answers = answers

        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            self.time_spent_seconds = int(delta.total_seconds())
