# app/achievements/models.py
# Models for grading and statistics system
# Uses existing Achievement system from app.study.models for badges

from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, CHAR
from sqlalchemy.orm import backref, relationship

from app.utils.db import db
from app.utils.types import JSONBCompat


class LessonGrade(db.Model):
    """Model representing letter grades for lessons"""
    __tablename__ = 'lesson_grades'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)

    grade = Column(CHAR(1), nullable=False)  # A, B, C, D, F
    score = Column(Float, nullable=False)

    attempts_count = Column(Integer, default=1)
    best_attempt_score = Column(Float)

    earned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='lesson_grades')
    lesson = relationship('Lessons', back_populates='grades')

    __table_args__ = (
        Index('idx_lesson_grades_user_id', 'user_id'),
        Index('idx_lesson_grades_lesson_id', 'lesson_id'),
        Index('idx_lesson_grades_grade', 'grade'),
        Index('idx_lesson_grades_earned_at', 'earned_at'),
    )

    @staticmethod
    def calculate_grade(score: float) -> str:
        """Calculate letter grade from numeric score"""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'

    @property
    def grade_color(self) -> str:
        """Get color for grade display"""
        colors = {
            'A': '#10b981',  # green
            'B': '#3b82f6',  # blue
            'C': '#f59e0b',  # amber
            'D': '#f97316',  # orange
            'F': '#ef4444',  # red
        }
        return colors.get(self.grade, '#6b7280')

    @property
    def grade_name(self) -> str:
        """Get full name for grade"""
        names = {
            'A': 'Отлично',
            'B': 'Хорошо',
            'C': 'Удовлетворительно',
            'D': 'Слабо',
            'F': 'Неудовлетворительно'
        }
        return names.get(self.grade, 'Неизвестно')

    def __repr__(self):
        return f"<LessonGrade: User {self.user_id} - Lesson {self.lesson_id} - {self.grade}>"


class UserStatistics(db.Model):
    """Model for storing user statistics"""
    __tablename__ = 'user_statistics'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)

    # Overall stats
    total_lessons_completed = Column(Integer, default=0)
    total_score_sum = Column(Float, default=0)
    total_time_spent_minutes = Column(Integer, default=0)

    # Streaks
    current_streak_days = Column(Integer, default=0)
    longest_streak_days = Column(Integer, default=0)
    last_activity_date = Column(db.Date)

    # Grades count
    grade_a_count = Column(Integer, default=0)
    grade_b_count = Column(Integer, default=0)
    grade_c_count = Column(Integer, default=0)
    grade_d_count = Column(Integer, default=0)
    grade_f_count = Column(Integer, default=0)

    # Badges
    total_badges = Column(Integer, default=0)
    total_badge_points = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship('User', backref='statistics')

    def __repr__(self):
        return f"<UserStatistics: User {self.user_id}>"

    @property
    def average_score(self) -> float:
        """Calculate average score"""
        if self.total_lessons_completed > 0:
            return round(self.total_score_sum / self.total_lessons_completed, 1)
        return 0.0

    @property
    def total_grade_count(self) -> int:
        """Total number of graded lessons"""
        return (self.grade_a_count + self.grade_b_count + self.grade_c_count +
                self.grade_d_count + self.grade_f_count)


class StreakCoins(db.Model):
    """User's streak coin balance."""
    __tablename__ = 'streak_coins'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    balance = Column(Integer, default=0, nullable=False)
    total_earned = Column(Integer, default=0, nullable=False)
    total_spent = Column(Integer, default=0, nullable=False)

    user = relationship('User', backref=backref('streak_coins', uselist=False, cascade='all, delete-orphan'))

    def earn(self, amount: int) -> None:
        self.balance += amount
        self.total_earned += amount

    def spend(self, amount: int) -> bool:
        if self.balance < amount:
            return False
        self.balance -= amount
        self.total_spent += amount
        return True


class StreakEvent(db.Model):
    """Log of streak-related events (earnings, repairs, breaks)."""
    __tablename__ = 'streak_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    event_type = Column(String(20), nullable=False)
    coins_delta = Column(Integer, default=0, nullable=False)
    event_date = Column(Date, nullable=False)
    details = Column(JSONBCompat, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    steps_done = Column(Integer, nullable=True)
    steps_total = Column(Integer, nullable=True)

    user = relationship('User', backref=backref('streak_events', cascade='all, delete-orphan'))

    __table_args__ = (
        Index('idx_streak_events_user_date', 'user_id', 'event_date'),
        Index('idx_streak_events_user_type', 'user_id', 'event_type'),
    )
