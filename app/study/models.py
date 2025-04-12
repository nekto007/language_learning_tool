from datetime import datetime, timedelta

from sqlalchemy import Float, cast
from sqlalchemy.ext.hybrid import hybrid_property

from app.utils.db import db


class StudyItem(db.Model):
    """
    Model to track learning progress for a word using spaced repetition algorithm
    """
    __tablename__ = 'study_items'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)

    # Spaced repetition parameters
    ease_factor = db.Column(db.Float, default=2.5)  # Ease factor (starts at 2.5)
    interval = db.Column(db.Integer, default=0)  # Current interval in days
    repetitions = db.Column(db.Integer, default=0)  # Number of times reviewed

    # Review dates
    last_reviewed = db.Column(db.DateTime, default=datetime.utcnow)
    next_review = db.Column(db.DateTime, default=datetime.utcnow)

    # Study statistics
    correct_count = db.Column(db.Integer, default=0)
    incorrect_count = db.Column(db.Integer, default=0)

    # Relationships
    user = db.relationship('User', backref=db.backref('study_items', lazy='dynamic', cascade='all, delete-orphan'))
    word = db.relationship('CollectionWords',
                           backref=db.backref('study_items', lazy='dynamic', cascade='all, delete-orphan'))

    def __init__(self, user_id, word_id):
        self.user_id = user_id
        self.word_id = word_id
        # Initialize these fields explicitly
        self.repetitions = 0
        self.ease_factor = 2.5
        self.interval = 0
        self.correct_count = 0
        self.incorrect_count = 0
        self.last_reviewed = datetime.utcnow()
        self.next_review = datetime.utcnow()

    def update_after_review(self, quality):
        """
        Update the spaced repetition parameters after a review

        quality: Rating from 0 to 5
            0 - Complete blackout, wrong answer
            1-2 - Incorrect response but recognized the word
            3 - Correct response but with difficulty
            4 - Correct response with some hesitation
            5 - Perfect response
        """
        # Update correct/incorrect count
        if quality >= 3:
            self.correct_count += 1
        else:
            self.incorrect_count += 1

        # Update SM-2 algorithm parameters
        old_ease_factor = self.ease_factor

        # Implement SM-2 algorithm (Anki-like)
        if quality < 3:
            # If response was wrong, start over
            self.repetitions = 0
            self.interval = 0
            # EF decreases but should not go below 1.3
            self.ease_factor = max(1.3, old_ease_factor - 0.20)
        else:
            self.repetitions += 1
            # Update ease factor
            self.ease_factor = max(1.3, old_ease_factor - 0.8 + (0.28 * quality) - (0.02 * quality * quality))

            # Make sure ease factor doesn't go below 1.3
            if self.repetitions == 1:
                # First correct repetition
                self.interval = 1
            elif self.repetitions == 2:
                # Second correct repetition
                self.interval = 6
            else:
                # For subsequent repetitions, calculate based on previous interval and ease factor
                if quality == 3:
                    # "Трудно" button (Hard) - apply penalty
                    hard_penalty = 0.8  # 20% penalty for difficult cards
                    self.interval = max(1, round(self.interval * self.ease_factor * hard_penalty))
                elif quality == 4:
                    # "Хорошо" button (Good) - standard calculation
                    self.interval = max(1, round(self.interval * self.ease_factor))
                elif quality == 5:
                    # "Легко" button (Easy) - apply bonus
                    easy_bonus = 1.3  # 30% bonus for easy cards
                    self.interval = max(1, round(self.interval * self.ease_factor * easy_bonus))

        # Update review dates
        self.last_reviewed = datetime.utcnow()
        self.next_review = datetime.utcnow() + timedelta(days=self.interval)

        return self.interval

    @property
    def due_for_review(self):
        """Check if this item is due for review"""
        return datetime.utcnow() >= self.next_review

    @property
    def days_until_review(self):
        """Calculate days until next review"""
        if self.due_for_review:
            return 0
        delta = self.next_review - datetime.utcnow()
        return max(0, delta.days)

    @property
    def is_mastered(self):
        """Check if the word is considered "mastered" (interval >= 30 days)"""
        return self.interval >= 30

    @hybrid_property
    def performance_percentage(self):
        """Calculate percentage of correct answers"""
        total = self.correct_count + self.incorrect_count
        if total == 0:
            return 0
        return round((self.correct_count / total) * 100)

    @performance_percentage.expression
    def performance_percentage(cls):
        """SQL-выражение для вычисления процента"""
        # Используем cast для корректного деления (избегаем целочисленного деления)
        return (cast(cls.correct_count, Float) / (cls.correct_count + cls.incorrect_count)) * 100


class StudySession(db.Model):
    """
    Model to track study sessions and their results
    """
    __tablename__ = 'study_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    session_type = db.Column(db.String(20), nullable=False)  # 'cards', 'quiz', etc.
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)

    words_studied = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)
    incorrect_answers = db.Column(db.Integer, default=0)

    # Relationship
    user = db.relationship('User', backref=db.backref('study_sessions', lazy='dynamic', cascade='all, delete-orphan'))

    def complete_session(self):
        """Mark the session as complete"""
        self.end_time = datetime.utcnow()

    @property
    def duration(self):
        """Calculate session duration in minutes"""
        end = self.end_time or datetime.utcnow()
        delta = end - self.start_time
        return round(delta.total_seconds() / 60, 1)

    @property
    def performance_percentage(self):
        """Calculate percentage of correct answers"""
        total = self.correct_answers + self.incorrect_answers
        if total == 0:
            return 0
        return round((self.correct_answers / total) * 100)


class StudySettings(db.Model):
    """
    User preferences for study sessions
    """
    __tablename__ = 'study_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)

    # Session settings
    new_words_per_day = db.Column(db.Integer, default=5)
    reviews_per_day = db.Column(db.Integer, default=20)

    # Study preferences
    include_translations = db.Column(db.Boolean, default=True)
    include_examples = db.Column(db.Boolean, default=True)
    include_audio = db.Column(db.Boolean, default=True)

    # Difficulty settings
    show_hint_time = db.Column(db.Integer, default=10)  # Seconds until hint is shown

    # Relationship
    user = db.relationship('User', backref=db.backref('study_settings', uselist=False, cascade='all, delete-orphan'))

    @classmethod
    def get_settings(cls, user_id):
        """Get or create settings for user"""
        settings = cls.query.filter_by(user_id=user_id).first()
        if not settings:
            settings = cls(user_id=user_id)
            db.session.add(settings)
            db.session.commit()
        return settings


class GameScore(db.Model):
    """
    Model to track high scores and leaderboards for games
    """
    __tablename__ = 'game_scores'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    game_type = db.Column(db.String(20), nullable=False)  # 'matching', 'quiz', etc.
    difficulty = db.Column(db.String(20), nullable=True)  # 'easy', 'medium', 'hard'
    score = db.Column(db.Integer, default=0)
    time_taken = db.Column(db.Integer, default=0)  # В секундах
    pairs_matched = db.Column(db.Integer, default=0)
    total_pairs = db.Column(db.Integer, default=0)
    moves = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)
    total_questions = db.Column(db.Integer, default=0)
    date_achieved = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('game_scores', lazy='dynamic', cascade='all, delete-orphan'))

    @classmethod
    def get_leaderboard(cls, game_type, difficulty=None, limit=10):
        """Get leaderboard for a game type"""
        query = cls.query.filter_by(game_type=game_type)

        if difficulty:
            query = query.filter_by(difficulty=difficulty)

        return query.order_by(cls.score.desc()).limit(limit).all()

    def get_rank(self):
        """Get rank of this score in leaderboard"""
        query = GameScore.query.filter(
            GameScore.game_type == self.game_type,
            GameScore.score > self.score
        )

        if self.difficulty:
            query = query.filter_by(difficulty=self.difficulty)

        return query.count() + 1
