# app/curriculum/models/book_courses.py

import re
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Boolean
from sqlalchemy.orm import relationship
from app.utils.db import db


def generate_slug(text: str) -> str:
    """Generate URL-friendly slug from text"""
    # Lowercase and replace spaces with hyphens
    slug = text.lower().strip()
    # Remove special characters, keep only letters, numbers, spaces, hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)
    # Replace spaces with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    return slug


class BookCourse(db.Model):
    """Model representing a course based on a specific book"""
    __tablename__ = 'book_courses'

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey('book.id', ondelete='CASCADE'), nullable=False)
    slug = Column(String(250), unique=True, nullable=True)  # URL-friendly identifier
    title = Column(String(200), nullable=False)
    description = Column(Text)
    level = Column(String(10), nullable=False)  # A1, A2, B1, B2, C1, C2
    difficulty_score = Column(Float, default=0.0)  # 0-10 scale
    estimated_duration_weeks = Column(Integer, default=4)
    total_modules = Column(Integer, default=0)
    
    # Course metadata
    author_info = Column(JSON)  # Information about the book's author
    literary_themes = Column(JSON)  # Main themes explored
    language_features = Column(JSON)  # Grammar and vocabulary focus
    cultural_context = Column(JSON)  # Cultural and historical background
    
    # Course settings
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    requires_prerequisites = Column(Boolean, default=False)
    prerequisites = Column(JSON)  # List of required courses/levels
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    book = relationship('Book', backref='book_courses')
    modules = relationship('BookCourseModule', back_populates='course', cascade='all, delete-orphan')
    enrollments = relationship('BookCourseEnrollment', back_populates='course', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_book_courses_book_id', 'book_id'),
        Index('idx_book_courses_slug', 'slug'),
        Index('idx_book_courses_level', 'level'),
        Index('idx_book_courses_active', 'is_active'),
        Index('idx_book_courses_featured', 'is_featured'),
    )

    def __repr__(self):
        return f"<BookCourse {self.id}: {self.title} ({self.level})>"

    def generate_slug_from_book(self):
        """Generate slug from book title"""
        if self.book:
            self.slug = generate_slug(self.book.title)
        elif self.title:
            self.slug = generate_slug(self.title)
        return self.slug
    
    @property
    def completion_rate(self):
        """Calculate average completion rate across all enrollments"""
        if not self.enrollments:
            return 0.0
        
        total_progress = sum(enrollment.progress_percentage for enrollment in self.enrollments)
        return total_progress / len(self.enrollments)
    
    def get_module_by_number(self, module_number):
        """Get module by its number within the course"""
        return BookCourseModule.query.filter_by(
            course_id=self.id, 
            module_number=module_number
        ).first()


class BookCourseModule(db.Model):
    """Model representing a module within a book course"""
    __tablename__ = 'book_course_modules'

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey('book_courses.id', ondelete='CASCADE'), nullable=False)
    block_id = Column(Integer, ForeignKey('block.id', ondelete='CASCADE'), nullable=True)  # Reference to Block
    module_number = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    
    # Reading segment information
    start_position = Column(Integer, default=0)
    end_position = Column(Integer, default=0)
    estimated_reading_time = Column(Integer, default=30)  # in minutes
    
    # Module content
    learning_objectives = Column(JSON)  # What students will learn
    vocabulary_focus = Column(JSON)  # Key vocabulary for this module
    grammar_focus = Column(JSON)  # Grammar points covered
    literary_elements = Column(JSON)  # Literary devices, themes, etc.
    
    # Module structure - JSON containing lessons
    lessons_data = Column(JSON)  # Complete lesson structure
    
    # Module metadata
    difficulty_level = Column(String(10))  # A1, A2, B1, etc.
    order_index = Column(Integer, default=0)
    is_locked = Column(Boolean, default=False)  # Requires previous modules
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    course = relationship('BookCourse', back_populates='modules')
    block = relationship('Block', backref='course_modules')
    progress_records = relationship('BookModuleProgress', back_populates='module', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_book_course_modules_course_number', 'course_id', 'module_number', unique=True),
        Index('idx_book_course_modules_course_id', 'course_id'),
        Index('idx_book_course_modules_order', 'order_index'),
    )

    def __repr__(self):
        return f"<BookCourseModule {self.module_number}: {self.title}>"
    
    @property
    def total_lessons(self):
        """Get total number of lessons in this module"""
        if not self.lessons_data or not isinstance(self.lessons_data, dict):
            return 0
        return len(self.lessons_data.get('lessons', []))
    
    def get_lesson_by_number(self, lesson_number):
        """Get lesson data by lesson number"""
        if not self.lessons_data or not isinstance(self.lessons_data, dict):
            return None
        
        lessons = self.lessons_data.get('lessons', [])
        for lesson in lessons:
            if lesson.get('lesson_number') == lesson_number:
                return lesson
        return None


class BookCourseEnrollment(db.Model):
    """Model tracking user enrollment in book courses"""
    __tablename__ = 'book_course_enrollments'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    course_id = Column(Integer, ForeignKey('book_courses.id', ondelete='CASCADE'), nullable=False)
    
    # Enrollment status
    status = Column(String(20), default='active')  # active, completed, paused, dropped
    progress_percentage = Column(Float, default=0.0)  # 0-100
    current_module_id = Column(Integer, ForeignKey('book_course_modules.id'), nullable=True)
    
    # Timestamps
    enrolled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    
    # Learning analytics
    total_study_time = Column(Integer, default=0)  # in minutes
    words_learned = Column(Integer, default=0)
    reading_speed = Column(Float, default=0.0)  # words per minute
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    course = relationship('BookCourse', back_populates='enrollments')
    user = relationship('User', backref='book_course_enrollments')
    current_module = relationship('BookCourseModule', foreign_keys=[current_module_id])
    module_progress = relationship('BookModuleProgress', back_populates='enrollment', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_book_enrollments_user_course', 'user_id', 'course_id', unique=True),
        Index('idx_book_enrollments_user_id', 'user_id'),
        Index('idx_book_enrollments_course_id', 'course_id'),
        Index('idx_book_enrollments_status', 'status'),
    )

    def __repr__(self):
        return f"<BookCourseEnrollment User {self.user_id} - Course {self.course_id}>"


class BookModuleProgress(db.Model):
    """Model tracking user progress through book course modules"""
    __tablename__ = 'book_module_progress'

    id = Column(Integer, primary_key=True)
    enrollment_id = Column(Integer, ForeignKey('book_course_enrollments.id', ondelete='CASCADE'), nullable=False)
    module_id = Column(Integer, ForeignKey('book_course_modules.id', ondelete='CASCADE'), nullable=False)
    
    # Progress tracking
    status = Column(String(20), default='not_started')  # not_started, in_progress, completed
    progress_percentage = Column(Float, default=0.0)  # 0-100
    current_lesson_number = Column(Integer, default=1)
    
    # Reading progress
    reading_position = Column(Integer, default=0)  # Current position in text
    reading_time_spent = Column(Integer, default=0)  # in minutes
    
    # Performance metrics
    vocabulary_score = Column(Float, default=0.0)
    comprehension_score = Column(Float, default=0.0)
    overall_score = Column(Float, default=0.0)
    
    # Lesson completion data
    lessons_completed = Column(JSON)  # List of completed lesson numbers
    lesson_scores = Column(JSON)  # Scores for each lesson
    
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    enrollment = relationship('BookCourseEnrollment', back_populates='module_progress')
    module = relationship('BookCourseModule', back_populates='progress_records')

    __table_args__ = (
        Index('idx_book_module_progress_enrollment_module', 'enrollment_id', 'module_id', unique=True),
        Index('idx_book_module_progress_enrollment_id', 'enrollment_id'),
        Index('idx_book_module_progress_module_id', 'module_id'),
        Index('idx_book_module_progress_status', 'status'),
    )

    def __repr__(self):
        return f"<BookModuleProgress Enrollment {self.enrollment_id} - Module {self.module_id}>"
    
    def mark_lesson_completed(self, lesson_number, score=None):
        """Mark a lesson as completed with optional score"""
        if not self.lessons_completed:
            self.lessons_completed = []
        
        if lesson_number not in self.lessons_completed:
            self.lessons_completed.append(lesson_number)
        
        if score is not None:
            if not self.lesson_scores:
                self.lesson_scores = {}
            self.lesson_scores[str(lesson_number)] = score
        
        # Update progress percentage based on completed lessons
        total_lessons = self.module.total_lessons
        if total_lessons > 0:
            self.progress_percentage = (len(self.lessons_completed) / total_lessons) * 100
            
            # Mark module as completed if all lessons are done
            if len(self.lessons_completed) >= total_lessons:
                self.status = 'completed'
                if not self.completed_at:
                    self.completed_at = datetime.now(timezone.utc)
        
        self.last_activity = datetime.now(timezone.utc)