from datetime import datetime, timedelta, timezone

from sqlalchemy import Index, func
from sqlalchemy.ext.hybrid import hybrid_property

from app.utils.db import db


class StudySession(db.Model):
    """
    Model to track study sessions and their results
    """
    __tablename__ = 'study_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    session_type = db.Column(db.String(20), nullable=False)  # 'cards', 'quiz', etc.
    start_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    end_time = db.Column(db.DateTime, nullable=True)

    words_studied = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)
    incorrect_answers = db.Column(db.Integer, default=0)

    # Relationship
    user = db.relationship('User', backref=db.backref('study_sessions', lazy='dynamic', cascade='all, delete-orphan'))

    def complete_session(self):
        """Mark the session as complete"""
        self.end_time = datetime.now(timezone.utc)

    @property
    def duration(self):
        """Calculate session duration in minutes"""
        end = self.end_time or datetime.now(timezone.utc)
        
        # Ensure both datetimes are timezone-aware
        if self.start_time and self.start_time.tzinfo is None:
            # If start_time is naive, assume it's UTC
            start = self.start_time.replace(tzinfo=timezone.utc)
        else:
            start = self.start_time
            
        if end and end.tzinfo is None:
            # If end is naive, assume it's UTC
            end = end.replace(tzinfo=timezone.utc)
        
        if not start:
            return 0
            
        delta = end - start
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
    date_achieved = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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


class UserWord(db.Model):
    """
    Links a user to a word with overall learning status.
    """
    __tablename__ = 'user_words'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)

    # Status: new, learning, review, mastered
    status = db.Column(db.String(20), default='new')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('user_words', lazy='dynamic', cascade='all, delete-orphan'))
    word = db.relationship('CollectionWords',
                           backref=db.backref('user_words', lazy='dynamic', cascade='all, delete-orphan'))
    directions = db.relationship('UserCardDirection', backref='user_word', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'word_id', name='uix_user_word'),
        Index('idx_user_word_user_id', 'user_id'),
        Index('idx_user_word_word_id', 'word_id'),
        Index('idx_user_word_status', 'status'),
    )

    def __init__(self, user_id, word_id):
        self.user_id = user_id
        self.word_id = word_id
        self.status = 'new'

    @classmethod
    def get_or_create(cls, user_id, word_id):
        """Get existing user_word or create a new one"""
        user_word = cls.query.filter_by(user_id=user_id, word_id=word_id).first()
        if not user_word:
            user_word = cls(user_id=user_id, word_id=word_id)
            db.session.add(user_word)
            db.session.commit()
        return user_word

    @hybrid_property
    def performance_percentage(self):
        """Calculate percentage of correct answers across all directions"""
        directions = UserCardDirection.query.filter_by(user_word_id=self.id).all()
        total_correct = sum(d.correct_count for d in directions)
        total_incorrect = sum(d.incorrect_count for d in directions)
        total = total_correct + total_incorrect

        if total == 0:
            return 0
        return round((total_correct / total) * 100)

    @performance_percentage.expression
    def performance_percentage(cls):
        """SQL expression for calculating percentage"""
        return (
            db.session.query(
                func.sum(UserCardDirection.correct_count) * 100.0 /
                func.sum(UserCardDirection.correct_count + UserCardDirection.incorrect_count)
            )
            .filter(UserCardDirection.user_word_id == cls.id)
            .scalar_subquery()
        )


class UserCardDirection(db.Model):
    """
    Represents a specific direction (eng→rus or rus→eng) for a user's word.
    Tracks spaced repetition parameters for each direction separately.
    """
    __tablename__ = 'user_card_directions'

    id = db.Column(db.Integer, primary_key=True)
    user_word_id = db.Column(db.Integer, db.ForeignKey('user_words.id', ondelete='CASCADE'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'eng-rus' or 'rus-eng'

    # Spaced repetition parameters
    repetitions = db.Column(db.Integer, default=0)
    ease_factor = db.Column(db.Float, default=2.5)
    interval = db.Column(db.Integer, default=0)
    last_reviewed = db.Column(db.DateTime, nullable=True)
    next_review = db.Column(db.DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    session_attempts = db.Column(db.Integer, default=0)

    # Stats
    correct_count = db.Column(db.Integer, default=0)
    incorrect_count = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('user_word_id', 'direction', name='uix_user_word_direction'),
        Index('idx_card_direction_user_word_id', 'user_word_id'),
        Index('idx_card_direction_next_review', 'next_review'),
    )

    def __init__(self, user_word_id, direction):
        self.user_word_id = user_word_id
        self.direction = direction
        self.repetitions = 0
        self.ease_factor = 2.5
        self.interval = 0
        self.correct_count = 0
        self.incorrect_count = 0
        self.next_review = datetime.now(timezone.utc)

    def update_after_review(self, quality):
        """
        Update SRS parameters after review. Similar to StudyItem.update_after_review
        but tailored for card directions.

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
                    # "Hard" button - apply penalty
                    hard_penalty = 0.8  # 20% penalty for difficult cards
                    self.interval = max(1, round(self.interval * self.ease_factor * hard_penalty))
                elif quality == 4:
                    # "Good" button - standard calculation
                    self.interval = max(1, round(self.interval * self.ease_factor))
                elif quality == 5:
                    # "Easy" button - apply bonus
                    easy_bonus = 1.3  # 30% bonus for easy cards
                    self.interval = max(1, round(self.interval * self.ease_factor * easy_bonus))

        # Update review dates
        self.last_reviewed = datetime.now(timezone.utc)
        self.next_review = datetime.now(timezone.utc) + timedelta(days=self.interval)

        # Update the parent UserWord status if needed
        self.update_user_word_status()

        return self.interval

    def update_user_word_status(self):
        """Update the parent UserWord status based on direction progress"""
        user_word = UserWord.query.get(self.user_word_id)

        # If this is the first review, update status to 'learning'
        if user_word.status == 'new':
            user_word.status = 'learning'
            db.session.commit()
            return

        # Check if both directions have been reviewed
        other_direction = 'rus-eng' if self.direction == 'eng-rus' else 'eng-rus'
        other_card = UserCardDirection.query.filter_by(
            user_word_id=self.user_word_id,
            direction=other_direction
        ).first()

        # If both directions have been reviewed at least once, set to 'review'
        if other_card and other_card.repetitions > 0 and self.repetitions > 0:
            if user_word.status == 'learning':
                user_word.status = 'review'
                db.session.commit()

            # If both directions have long intervals, set to 'mastered'
            if other_card.interval >= 30 and self.interval >= 30 and user_word.status == 'review':
                user_word.status = 'mastered'
                db.session.commit()

    @property
    def due_for_review(self):
        """Check if this direction is due for review"""
        if not self.next_review:
            return True
            
        # Ensure next_review is timezone-aware
        if self.next_review.tzinfo is None:
            next_review_aware = self.next_review.replace(tzinfo=timezone.utc)
        else:
            next_review_aware = self.next_review
            
        return datetime.now(timezone.utc) >= next_review_aware

    @property
    def days_until_review(self):
        """Calculate days until next review"""
        if not self.next_review or self.due_for_review:
            return 0
            
        # Ensure next_review is timezone-aware
        if self.next_review.tzinfo is None:
            next_review_aware = self.next_review.replace(tzinfo=timezone.utc)
        else:
            next_review_aware = self.next_review
            
        delta = next_review_aware - datetime.now(timezone.utc)
        return max(0, delta.days)
