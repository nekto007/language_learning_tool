# app/curriculum/models/daily_lessons.py

from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.utils.db import db


class DailyLesson(db.Model):
    """Daily lesson slice - approximately 800 words of reading with associated tasks"""
    __tablename__ = 'daily_lessons'
    
    id = Column(Integer, primary_key=True)
    book_course_module_id = Column(Integer, ForeignKey('book_course_modules.id', ondelete='CASCADE'), nullable=False)
    slice_number = Column(Integer, nullable=False)  # Sequential number within module
    day_number = Column(Integer, nullable=False)  # Day 1, 2, 3... of the module
    
    # Text content
    slice_text = Column(Text, nullable=False)  # The actual 800-word slice
    word_count = Column(Integer, nullable=False)
    start_position = Column(Integer, nullable=False)  # Character position in original chapter
    end_position = Column(Integer, nullable=False)
    chapter_id = Column(Integer, ForeignKey('chapter.id', ondelete='CASCADE'), nullable=False)
    
    # Lesson configuration
    lesson_type = Column(String(50), nullable=False)  # vocabulary, reading_mcq, match_headings, etc.
    task_id = Column(Integer, ForeignKey('task.id', ondelete='SET NULL'), nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    module = relationship('BookCourseModule', backref='daily_lessons')
    chapter = relationship('Chapter')
    task = relationship('Task')
    vocabulary = relationship('SliceVocabulary', back_populates='daily_lesson', cascade='all, delete-orphan')
    progress_records = relationship('UserLessonProgress', back_populates='daily_lesson', cascade='all, delete-orphan')
    completion_events = relationship('LessonCompletionEvent', back_populates='daily_lesson', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_daily_lessons_module_day', 'book_course_module_id', 'day_number'),
        Index('idx_daily_lessons_available', 'available_at'),
    )
    
    def __repr__(self):
        return f"<DailyLesson {self.id}: Module {self.book_course_module_id} Day {self.day_number}>"
    
    @property
    def is_available(self):
        """Check if lesson is available for study"""
        if not self.available_at:
            return True
        return datetime.now(timezone.utc) >= self.available_at
    
    def get_vocabulary_words(self, limit=10):
        """Get vocabulary words for this slice, limited to specified number"""
        return (SliceVocabulary.query
                .filter_by(daily_lesson_id=self.id)
                .order_by(SliceVocabulary.frequency_in_slice.desc())
                .limit(limit)
                .all())
    
    def calculate_available_time(self, previous_lesson_completed_at=None, timezone_str='Europe/Amsterdam'):
        """Calculate when this lesson should become available"""
        if self.day_number == 1:
            # First lesson is immediately available
            return None
            
        if previous_lesson_completed_at:
            # 24 hours after previous lesson completion
            return previous_lesson_completed_at + timedelta(hours=24)
        else:
            # Default: available at 8:00 AM Amsterdam time on the lesson day
            from pytz import timezone as pytz_timezone
            tz = pytz_timezone(timezone_str)
            today = datetime.now(tz).date()
            lesson_date = today + timedelta(days=self.day_number - 1)
            return tz.localize(datetime.combine(lesson_date, datetime.min.time().replace(hour=8)))


class SliceVocabulary(db.Model):
    """Vocabulary words appearing in a specific daily lesson slice"""
    __tablename__ = 'slice_vocabulary'
    
    id = Column(Integer, primary_key=True)
    daily_lesson_id = Column(Integer, ForeignKey('daily_lessons.id', ondelete='CASCADE'), nullable=False)
    word_id = Column(Integer, ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)
    frequency_in_slice = Column(Integer, nullable=False)
    is_new = Column(Boolean, default=True)  # First appearance in course
    context_sentence = Column(Text)  # Example sentence from the slice
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    daily_lesson = relationship('DailyLesson', back_populates='vocabulary')
    word = relationship('CollectionWords')
    
    __table_args__ = (
        UniqueConstraint('daily_lesson_id', 'word_id', name='uq_slice_word'),
        Index('idx_slice_vocabulary_lesson', 'daily_lesson_id'),
    )


class UserLessonProgress(db.Model):
    """Track user progress through daily lessons"""
    __tablename__ = 'user_lesson_progress'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    daily_lesson_id = Column(Integer, ForeignKey('daily_lessons.id', ondelete='CASCADE'), nullable=False)
    enrollment_id = Column(Integer, ForeignKey('book_course_enrollments.id', ondelete='CASCADE'), nullable=False)

    # Progress tracking
    status = Column(String(20), default='not_started')  # not_started, in_progress, completed
    score = Column(Float)  # Percentage score for tasks
    time_spent = Column(Integer, default=0)  # in seconds

    # Timestamps
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    attempts = Column(Integer, default=0)

    # Extended metrics for analytics and adaptive learning
    errors_count = Column(Integer, default=0)  # Total number of errors in this lesson
    error_types = Column(JSONB)  # {'vocabulary': 2, 'grammar': 1, 'comprehension': 3}
    last_attempt_at = Column(DateTime(timezone=True))  # When last attempt was made
    review_intervals = Column(JSONB)  # [1, 3, 7, 14] - days between review attempts

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship('User')
    daily_lesson = relationship('DailyLesson', back_populates='progress_records')
    enrollment = relationship('BookCourseEnrollment')
    
    __table_args__ = (
        UniqueConstraint('user_id', 'daily_lesson_id', name='uq_user_lesson'),
        Index('idx_user_lesson_progress_user', 'user_id'),
        Index('idx_user_lesson_progress_enrollment', 'enrollment_id'),
    )
    
    def start_lesson(self):
        """Mark lesson as started"""
        if self.status == 'not_started':
            self.status = 'in_progress'
            self.started_at = datetime.now(timezone.utc)
            self.attempts += 1
    
    def complete_lesson(self, score=None, errors=None, error_breakdown=None):
        """Mark lesson as completed with optional score and error metrics"""
        self.status = 'completed'
        self.completed_at = datetime.now(timezone.utc)
        self.last_attempt_at = self.completed_at

        if score is not None:
            self.score = score

        # Track errors if provided
        if errors is not None:
            self.errors_count = (self.errors_count or 0) + errors

        if error_breakdown:
            # Merge error types with existing data
            current_errors = self.error_types or {}
            for error_type, count in error_breakdown.items():
                current_errors[error_type] = current_errors.get(error_type, 0) + count
            self.error_types = current_errors

        # Calculate time spent
        if self.started_at:
            time_delta = self.completed_at - self.started_at
            self.time_spent = int(time_delta.total_seconds())

        # Update review intervals tracking
        self._update_review_intervals()

    def _update_review_intervals(self):
        """Track intervals between review attempts for spaced repetition analysis"""
        if not self.review_intervals:
            self.review_intervals = []

        if self.completed_at and self.started_at:
            # Calculate days since first start
            first_attempt = self.review_intervals[0] if self.review_intervals else 0
            if len(self.review_intervals) > 0 and self.attempts > 1:
                # Calculate interval since last review
                # For simplicity, track attempt number as interval placeholder
                self.review_intervals.append(self.attempts)

    def record_error(self, error_type: str, count: int = 1):
        """Record an error during the lesson"""
        self.errors_count = (self.errors_count or 0) + count
        current_errors = self.error_types or {}
        current_errors[error_type] = current_errors.get(error_type, 0) + count
        self.error_types = current_errors
        self.last_attempt_at = datetime.now(timezone.utc)

    def get_weak_areas(self) -> list:
        """Identify weak areas based on error types"""
        if not self.error_types:
            return []

        # Sort by error count descending
        sorted_errors = sorted(
            self.error_types.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [error_type for error_type, count in sorted_errors if count > 0]


class LessonCompletionEvent(db.Model):
    """Track completion events for lessons"""
    __tablename__ = 'lesson_completion_events'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    daily_lesson_id = Column(Integer, ForeignKey('daily_lessons.id', ondelete='CASCADE'), nullable=False)
    event_type = Column(String(50), nullable=False)  # lesson_completed, quiz_submitted, vocabulary_studied
    event_data = Column(JSONB)  # Additional event-specific data
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship('User')
    daily_lesson = relationship('DailyLesson', back_populates='completion_events')
    
    __table_args__ = (
        Index('idx_lesson_events_user', 'user_id'),
        Index('idx_lesson_events_created', 'created_at'),
    )