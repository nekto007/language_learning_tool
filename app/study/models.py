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
    def get_settings(cls, user_id, lock_for_update=False):
        """Get or create settings for user

        Args:
            user_id: User ID
            lock_for_update: If True, use SELECT FOR UPDATE to prevent race conditions
        """
        query = cls.query.filter_by(user_id=user_id)
        if lock_for_update:
            query = query.with_for_update()
        settings = query.first()
        if not settings:
            settings = cls(user_id=user_id)
            db.session.add(settings)
            if not lock_for_update:
                db.session.commit()
            else:
                db.session.flush()
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
        """Get leaderboard for a game type with eager loading to avoid N+1 queries"""
        from sqlalchemy.orm import joinedload

        query = cls.query.options(joinedload(cls.user)).filter_by(game_type=game_type)

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

    def update_status(self, new_status):
        """Update the status of the user word"""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)
        db.session.commit()

    def set_next_review(self, days=1):
        """Set next review date"""
        self.updated_at = datetime.now(timezone.utc)
        # This is a simplified implementation
        # In practice, you might want to implement spaced repetition logic

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
        Update SRS parameters after review using unified 1-2-3 rating scale.

        Unified Rating Scale (1-2-3):
            1 - Не знаю (Don't know): Reset progress, show again soon
            2 - Сомневаюсь (Doubt): Moderate progress, shorter interval
            3 - Знаю (Know): Good progress, longer interval with bonus

        Legacy compatibility (0-5 scale):
            0-1 → mapped to 1 (Don't know)
            2-3 → mapped to 2 (Doubt)
            4-5 → mapped to 3 (Know)
        """
        # Map to unified 1-2-3 scale
        # Unified scale (current): 1=Не знаю, 2=Сомневаюсь, 3=Знаю
        # Legacy 0-5 scale: 0→1, 4-5→3
        if quality in (1, 2, 3):
            rating = quality  # Unified scale - use directly
        elif quality == 0:
            rating = 1  # Legacy: 0 → Не знаю
        else:
            rating = 3  # Legacy: 4-5 → Знаю

        # Update correct/incorrect count
        if rating >= 2:
            self.correct_count += 1
        else:
            self.incorrect_count += 1

        # Update SM-2 algorithm parameters
        old_ease_factor = self.ease_factor
        old_interval = self.interval

        if rating == 1:
            # "Не знаю" - Reset progress
            self.repetitions = 0
            self.interval = 0
            self.ease_factor = max(1.3, old_ease_factor - 0.20)

        elif rating == 2:
            # "Сомневаюсь" - Moderate progress
            self.repetitions += 1
            # EF stays the same
            self.ease_factor = old_ease_factor

            if self.repetitions == 1:
                self.interval = 1
            elif self.repetitions == 2:
                self.interval = 3  # Shorter than "Know"
            else:
                # 80% of normal interval
                self.interval = max(1, round(old_interval * old_ease_factor * 0.8))

        elif rating == 3:
            # "Знаю" - Good progress with bonus
            self.repetitions += 1
            self.ease_factor = min(2.5, old_ease_factor + 0.15)

            if self.repetitions == 1:
                self.interval = 1
            elif self.repetitions == 2:
                self.interval = 6
            else:
                # 120% bonus to interval
                self.interval = max(1, round(old_interval * old_ease_factor * 1.2))

        # Update review dates
        self.last_reviewed = datetime.now(timezone.utc)

        # Add ±10% variance to prevent review cliffs (all cards reviewing at once)
        import random
        variance = random.uniform(0.9, 1.1)
        adjusted_interval = max(0, round(self.interval * variance)) if self.interval > 0 else 0

        self.next_review = datetime.now(timezone.utc) + timedelta(days=adjusted_interval)

        # Increment session_attempts
        self.session_attempts = (self.session_attempts or 0) + 1

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


class QuizDeck(db.Model):
    """
    Quiz deck - a collection of words for quiz
    """
    __tablename__ = 'quiz_decks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Owner
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Sharing
    is_public = db.Column(db.Boolean, default=False)
    share_code = db.Column(db.String(20), unique=True, nullable=True, index=True)

    # Synchronization (for copied decks)
    parent_deck_id = db.Column(db.Integer, db.ForeignKey('quiz_decks.id'), nullable=True, index=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    # Stats
    times_played = db.Column(db.Integer, default=0)
    average_score = db.Column(db.Float, default=0.0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('quiz_decks', lazy='dynamic', cascade='all, delete-orphan'))
    words = db.relationship('QuizDeckWord', back_populates='deck', cascade='all, delete-orphan', lazy='dynamic')
    results = db.relationship('QuizResult', back_populates='deck', cascade='all, delete-orphan', lazy='dynamic')
    parent_deck = db.relationship('QuizDeck', remote_side=[id], backref='forks')

    def generate_share_code(self):
        """Generate unique share code for this deck"""
        import secrets
        import string
        while True:
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            if not QuizDeck.query.filter_by(share_code=code).first():
                self.share_code = code
                return code

    @property
    def word_count(self):
        """Get total number of words in deck"""
        return self.words.count()

    def sync_from_parent(self):
        """Synchronize this deck with its parent: add new words only"""
        if not self.parent_deck:
            return 0

        # Get current word_ids in this deck
        current_word_ids = {w.word_id for w in self.words.all() if w.word_id}

        # Get words from parent deck
        parent_words = self.parent_deck.words.order_by(QuizDeckWord.order_index).all()

        added_count = 0
        for parent_word in parent_words:
            # Skip custom words without word_id
            if not parent_word.word_id:
                continue

            # Add only new words (not already in this deck)
            if parent_word.word_id not in current_word_ids:
                new_word = QuizDeckWord(
                    deck_id=self.id,
                    word_id=parent_word.word_id,
                    custom_english=parent_word.custom_english,
                    custom_russian=parent_word.custom_russian,
                    custom_sentences=parent_word.custom_sentences,
                    order_index=parent_word.order_index
                )
                db.session.add(new_word)
                added_count += 1

        # Update last sync timestamp
        self.last_synced_at = datetime.now(timezone.utc)

        return added_count

    def sync_to_forks(self):
        """Synchronize all forks of this deck (called when author saves changes)"""
        if not self.is_public:
            return 0, 0

        # Get all forks (copied decks)
        forks = QuizDeck.query.filter_by(parent_deck_id=self.id).all()

        if not forks:
            return 0, 0

        total_added = 0
        for fork in forks:
            added = fork.sync_from_parent()
            total_added += added

        db.session.commit()

        return len(forks), total_added

    def __repr__(self):
        return f'<QuizDeck {self.title}>'


class QuizDeckWord(db.Model):
    """
    Word in a quiz deck
    Can reference existing word from collection_words or be a custom word
    """
    __tablename__ = 'quiz_deck_words'

    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('quiz_decks.id', ondelete='CASCADE'), nullable=False)

    # Reference to existing word (optional)
    word_id = db.Column(db.Integer, db.ForeignKey('collection_words.id', ondelete='SET NULL'), nullable=True)

    # Custom word fields (used if word_id is NULL)
    custom_english = db.Column(db.String(200), nullable=True)
    custom_russian = db.Column(db.String(200), nullable=True)
    custom_sentences = db.Column(db.Text, nullable=True)
    custom_audio_url = db.Column(db.String(500), nullable=True)

    # Order in deck
    order_index = db.Column(db.Integer, default=0)

    # Timestamps
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    deck = db.relationship('QuizDeck', back_populates='words')
    word = db.relationship('CollectionWords', foreign_keys=[word_id])

    __table_args__ = (
        Index('idx_deck_word_deck_id', 'deck_id'),
        Index('idx_deck_word_word_id', 'word_id'),
    )

    @property
    def english_word(self):
        """Get English word - custom override takes priority"""
        if self.custom_english:
            return self.custom_english
        if self.word:
            return self.word.english_word
        return None

    @property
    def russian_word(self):
        """Get Russian word - custom override takes priority"""
        if self.custom_russian:
            return self.custom_russian
        if self.word:
            return self.word.russian_word
        return None

    @property
    def sentences(self):
        """Get sentences - custom override takes priority"""
        if self.custom_sentences:
            return self.custom_sentences
        if self.word and self.word.sentences:
            return self.word.sentences
        return None

    @property
    def audio_url(self):
        """
        Get audio URL from collection_words or custom.
        Supports both formats in DB:
        - Clean filename: pronunciation_en_word.mp3
        - Legacy Anki format: [sound:pronunciation_en_word.mp3]
        """
        if self.word and self.word.get_download == 1 and self.word.listening:
            filename = self.word.listening
            # Extract filename from Anki format if needed
            if filename.startswith('[sound:') and filename.endswith(']'):
                filename = filename[7:-1]
            return f'/static/audio/{filename}'
        return self.custom_audio_url

    def __repr__(self):
        return f'<QuizDeckWord {self.english_word}>'


class QuizResult(db.Model):
    """
    Result of completing a quiz deck
    """
    __tablename__ = 'quiz_results'

    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('quiz_decks.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Results
    total_questions = db.Column(db.Integer, nullable=False)
    correct_answers = db.Column(db.Integer, nullable=False)
    score_percentage = db.Column(db.Float, nullable=False)
    time_taken = db.Column(db.Integer, nullable=False)  # seconds

    # Timestamps
    completed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    deck = db.relationship('QuizDeck', back_populates='results')
    user = db.relationship('User', backref=db.backref('quiz_results', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        Index('idx_quiz_result_deck_user', 'deck_id', 'user_id'),
        Index('idx_quiz_result_completed', 'completed_at'),
    )

    def __repr__(self):
        return f'<QuizResult user={self.user_id} deck={self.deck_id} score={self.score_percentage}%>'


class UserXP(db.Model):
    """
    Tracks user's XP (Experience Points) for gamification
    """
    __tablename__ = 'user_xp'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)
    total_xp = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship
    user = db.relationship('User', backref=db.backref('xp', uselist=False, cascade='all, delete-orphan'))

    @hybrid_property
    def level(self):
        """Calculate level based on total XP (every 100 XP = next level)"""
        # Level 1: 0-99 XP, Level 2: 100-199 XP, Level 3: 200-299 XP, etc.
        return (self.total_xp // 100) + 1

    @classmethod
    def get_or_create(cls, user_id):
        """Get or create UserXP record for a user"""
        user_xp = cls.query.filter_by(user_id=user_id).first()
        if not user_xp:
            user_xp = cls(user_id=user_id, total_xp=0)
            db.session.add(user_xp)
            db.session.flush()
        return user_xp

    def add_xp(self, amount):
        """Add XP and update timestamp"""
        self.total_xp += amount
        self.updated_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f'<UserXP user={self.user_id} xp={self.total_xp} level={self.level}>'


class Achievement(db.Model):
    """
    Defines available achievements/badges that users can earn
    """
    __tablename__ = 'achievements'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # e.g., 'first_quiz', 'perfect_score'
    name = db.Column(db.String(100), nullable=False)  # e.g., 'Первый квиз'
    description = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(10), default='🏆')  # Emoji icon
    xp_reward = db.Column(db.Integer, default=0)  # Bonus XP for earning this
    category = db.Column(db.String(50), default='general')  # 'quiz', 'study', 'streak', etc.

    # Relationships
    user_achievements = db.relationship('UserAchievement', back_populates='achievement', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Achievement {self.code}: {self.name}>'


class UserAchievement(db.Model):
    """
    Tracks which achievements a user has earned
    """
    __tablename__ = 'user_achievements'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievements.id', ondelete='CASCADE'), nullable=False)
    earned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('achievements', lazy='dynamic', cascade='all, delete-orphan'))
    achievement = db.relationship('Achievement', back_populates='user_achievements')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'achievement_id', name='uix_user_achievement'),
        Index('idx_user_achievement_user', 'user_id'),
        Index('idx_user_achievement_earned', 'earned_at'),
    )

    def __repr__(self):
        return f'<UserAchievement user={self.user_id} achievement={self.achievement_id}>'
