# app/curriculum/models.py

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
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
    collection_id = Column(Integer, ForeignKey('collections.id', ondelete='SET NULL'))  # For vocabulary components
    book_id = Column(Integer, ForeignKey('book.id', ondelete='SET NULL'))  # For text components
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    min_cards_required = Column(Integer, default=10)  # Минимум карточек для завершения
    min_accuracy_required = Column(Integer, default=80)  # Минимум процент правильных ответов

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

    # Relationships
    module = relationship('Module', back_populates='lessons')
    collection = relationship('Collection', backref='lessons')
    book = relationship('Book', backref='lesson_components')
    lesson_progress = relationship(
        'LessonProgress',
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


# class LessonComponent(db.Model):
#     """Model representing a component within a lesson (vocabulary, grammar, quiz, etc.)"""
#     __tablename__ = 'lesson_components'
#
#     id = Column(Integer, primary_key=True)
#     lesson_id = Column(Integer, ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False)
#     type = Column(String(50), nullable=False)  # vocabulary, grammar, quiz, matching, text, anki_cards, checkpoint
#     title = Column(String(200), nullable=False)
#     order = Column(Integer, default=0)  # Order within the lesson
#     content = Column(JSON)  # Flexible JSON content based on component type
#     collection_id = Column(Integer, ForeignKey('collections.id', ondelete='SET NULL'))  # For vocabulary components
#     book_id = Column(Integer, ForeignKey('book.id', ondelete='SET NULL'))  # For text components
#     created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
#     updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
#                         onupdate=lambda: datetime.now(timezone.utc))
#
#     # Relationships
#     lesson = relationship('Lesson', back_populates='components')
#     collection = relationship('Collection', backref='lesson_components')
#
#
#     __table_args__ = (
#         Index('idx_lesson_components_lesson_order', 'lesson_id', 'order'),
#     )
#
#     def __repr__(self):
#         return f"<LessonComponent {self.id}: {self.type} - {self.title}>"


# class ModuleProgress(db.Model):
#     """Model tracking user progress through modules"""
#     __tablename__ = 'user_progress'
#
#     id = Column(Integer, primary_key=True)
#     user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
#     module_id = Column(Integer, ForeignKey('module.id', ondelete='CASCADE'), nullable=False)
#     status = Column(String(20), default='not_started')  # not_started, in_progress, completed
#     score = Column(Float, default=0.0)  # Overall score for the module
#     started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
#     completed_at = Column(DateTime)
#     last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))
#
#     # Relationships
#     user = relationship('User', backref='progress')
#     lessons = relationship('Lessons', back_populates='progress')
#     lesson_progress = relationship('LessonProgress', back_populates='user_progress', cascade='all, delete-orphan')
#
#     __table_args__ = (
#         Index('idx_module_progress_user_module', 'user_id', 'module_id', unique=True),
#     )
#
#     def __repr__(self):
#         return f"<UserProgress: User {self.user_id} - Lesson {self.lesson_id} - {self.status}>"


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

# class SRSNotification(db.Model):
#     """Уведомления о необходимости повторения"""
#     __tablename__ = 'srs_notifications'
#
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
#     lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=True)
#
#     notification_type = db.Column(db.String(50), nullable=False)  # 'lesson_review', 'daily_reminder', etc.
#     title = db.Column(db.String(200), nullable=False)
#     message = db.Column(db.Text, nullable=True)
#     due_cards = db.Column(db.Integer, nullable=True)
#
#     is_read = db.Column(db.Boolean, default=False, nullable=False)
#     is_sent = db.Column(db.Boolean, default=False, nullable=False)
#
#     created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
#     sent_at = db.Column(db.DateTime, nullable=True)
#
#     # Relationships
#     user = db.relationship('User', backref=db.backref('srs_notifications', lazy='dynamic'))
#     lesson = db.relationship('Lessons', backref=db.backref('srs_notifications', lazy='dynamic'))
#
#     def mark_as_read(self):
#         """Отметить уведомление как прочитанное"""
#         self.is_read = True
#         self.read_at = datetime.now(timezone.utc)
#         db.session.commit()
#
#     def mark_as_sent(self):
#         """Отметить уведомление как отправленное"""
#         self.is_sent = True
#         self.sent_at = datetime.now(timezone.utc)
#         db.session.commit()
#
#     @classmethod
#     def create_lesson_reminder(cls, user_id, lesson_id, due_cards):
#         """Создать напоминание о повторении урока"""
#         from app.curriculum.models import Lessons
#
#         lesson = Lessons.query.get(lesson_id)
#         if not lesson:
#             return None
#
#         notification = cls(
#             user_id=user_id,
#             lesson_id=lesson_id,
#             notification_type='lesson_review',
#             title=f'Время повторить урок "{lesson.title}"',
#             message=f'У вас {due_cards} карточек для повторения',
#             due_cards=due_cards
#         )
#
#         db.session.add(notification)
#         db.session.commit()
#
#         return notification
#
#     @classmethod
#     def get_unread_count(cls, user_id):
#         """Получить количество непрочитанных уведомлений"""
#         return cls.query.filter_by(
#             user_id=user_id,
#             is_read=False
#         ).count()
#
#
