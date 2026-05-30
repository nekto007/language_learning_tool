from datetime import datetime, timedelta, timezone

from sqlalchemy import Index, func
from sqlalchemy.ext.hybrid import hybrid_property

from app.srs.constants import MASTERED_THRESHOLD_DAYS as _MASTERED_DAYS, MATURE_THRESHOLD_DAYS as _MATURE_DAYS
from app.srs.mixins import SRSFieldsMixin
from app.utils.db import db


class StudySession(db.Model):
    """
    Model to track study sessions and their results
    """
    __tablename__ = 'study_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    session_type = db.Column(db.String(20), nullable=False, default='cards')  # 'cards', 'quiz', etc.
    start_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    end_time = db.Column(db.DateTime, nullable=True)

    words_studied = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)
    incorrect_answers = db.Column(db.Integer, default=0)

    # Relationship
    user = db.relationship('User', backref=db.backref('study_sessions', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<StudySession {self.id}: {self.session_type} user={self.user_id}>"

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

    def __repr__(self):
        return f"<StudySettings user={self.user_id}>"

    @classmethod
    def get_settings(cls, user_id, lock_for_update=False):
        """Get or create settings for user

        Args:
            user_id: User ID
            lock_for_update: If True, use SELECT FOR UPDATE to prevent race conditions

        Read-path (``lock_for_update=False``) is memoized per request so the
        dashboard / plan assembly doesn't re-query the same row 8+ times.
        Write-path always re-fetches and locks.
        """
        if lock_for_update:
            return cls._fetch_settings(user_id, lock_for_update=True)
        return cls._fetch_settings_cached(user_id)

    @classmethod
    def _fetch_settings(cls, user_id, lock_for_update=False):
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

    @classmethod
    def _fetch_settings_cached(cls, user_id):
        from app.utils.request_cache import _get_cache

        cache = _get_cache()
        if cache is None:
            return cls._fetch_settings(user_id, lock_for_update=False)
        key = ('StudySettings.get_settings', user_id)
        if key not in cache:
            cache[key] = cls._fetch_settings(user_id, lock_for_update=False)
        return cache[key]


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

    def __repr__(self):
        return f"<GameScore {self.id}: {self.game_type} score={self.score}>"

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

    Status is derived from UserCardDirection states:
    - 'new': word added but no cards answered yet (all directions have repetitions=0)
    - 'learning': at least one direction is in learning/relearning state
    - 'review': all directions graduated to review state

    Mature/mastered are thresholds within review, not separate statuses:
    - is_mature: min(interval) >= 21 days
    - is_mastered: min(interval) >= 180 days
    """
    __tablename__ = 'user_words'

    # Thresholds for mature/mastered (in days) — canonical source: app/srs/constants.py
    MATURE_THRESHOLD_DAYS = _MATURE_DAYS
    MASTERED_THRESHOLD_DAYS = _MASTERED_DAYS

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('collection_words.id', ondelete='CASCADE'), nullable=False)

    # Status: new, learning, review (mastered removed - it's now a threshold)
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
        Index('idx_user_word_user_status', 'user_id', 'status'),
    )

    def __init__(self, user_id, word_id):
        self.user_id = user_id
        self.word_id = word_id
        self.status = 'new'

    def __repr__(self):
        return f"<UserWord {self.id}: user={self.user_id} word={self.word_id} status={self.status}>"

    @classmethod
    def get_or_create(cls, user_id: int, word_id: int) -> 'UserWord':
        """Get existing user_word or create a new one"""
        user_word = cls.query.filter_by(user_id=user_id, word_id=word_id).first()
        if not user_word:
            user_word = cls(user_id=user_id, word_id=word_id)
            db.session.add(user_word)
            db.session.flush()
        return user_word

    def recalculate_status(self):
        """
        Derive status from UserCardDirection states.

        Priority:
        1. If ANY direction is in 'learning' or 'relearning' → status = 'learning'
        2. Else if ANY direction is in 'new' → status = 'new'
        3. Else (all directions in 'review') → status = 'review'
        """
        directions_list = self.directions.all()

        if not directions_list:
            # No directions yet - keep as 'new'
            return

        has_learning = False
        has_new = False
        all_review = True

        for d in directions_list:
            if d.state in ('learning', 'relearning'):
                has_learning = True
                all_review = False
            elif d.state == 'new':
                has_new = True
                all_review = False
            # 'review' state doesn't change all_review

        if has_learning:
            new_status = 'learning'
        elif has_new:
            new_status = 'new'
        elif all_review:
            new_status = 'review'
        else:
            new_status = 'new'  # fallback

        if self.status != new_status:
            self.status = new_status
            self.updated_at = datetime.now(timezone.utc)

    @property
    def min_interval(self):
        """Get minimum interval across all directions (in days)."""
        directions_list = self.directions.all()
        if not directions_list:
            return 0
        intervals = [d.interval for d in directions_list if d.interval is not None]
        return min(intervals) if intervals else 0

    @property
    def is_mature(self):
        """Word is mature if min interval >= 21 days."""
        return self.status == 'review' and self.min_interval >= self.MATURE_THRESHOLD_DAYS

    @property
    def is_mastered(self):
        """Word is mastered if min interval >= 180 days."""
        return self.status == 'review' and self.min_interval >= self.MASTERED_THRESHOLD_DAYS

    def update_status(self, new_status):
        """Update the status of the user word (legacy method, prefer recalculate_status)"""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)
        db.session.commit()

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


class UserCardDirection(SRSFieldsMixin, db.Model):
    """
    Represents a specific direction (eng→rus or rus→eng) for a user's word.
    Tracks spaced repetition parameters for each direction separately.

    Anki-like state machine:
        NEW → LEARNING → REVIEW ⟷ RELEARNING
    """
    __tablename__ = 'user_card_directions'

    id = db.Column(db.Integer, primary_key=True)
    user_word_id = db.Column(db.Integer, db.ForeignKey('user_words.id', ondelete='CASCADE'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'eng-rus' or 'rus-eng'

    # Anki-like card state: 'new', 'learning', 'review', 'relearning'
    state = db.Column(db.String(15), default='new', nullable=False)

    # Learning step index (0-based, for LEARNING and RELEARNING states)
    step_index = db.Column(db.Integer, default=0, nullable=False)

    # Lapse count (number of times card went from REVIEW to RELEARNING)
    lapses = db.Column(db.Integer, default=0, nullable=False)

    # Bury until - card won't be shown until this timestamp (for session-level bury)
    buried_until = db.Column(db.DateTime, nullable=True)

    # Spaced repetition parameters
    repetitions = db.Column(db.Integer, default=0)
    ease_factor = db.Column(db.Float, default=2.5)
    interval = db.Column(db.Integer, default=0)
    last_reviewed = db.Column(db.DateTime, nullable=True)
    first_reviewed = db.Column(db.DateTime, nullable=True)  # When card was first studied (for new card limit tracking)
    next_review = db.Column(db.DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    session_attempts = db.Column(db.Integer, default=0)

    # Stats
    correct_count = db.Column(db.Integer, default=0)
    incorrect_count = db.Column(db.Integer, default=0)

    # Source of this card: 'lesson_vocab', 'book_reading', 'custom_list', 'manual', or None
    source = db.Column(db.String(50), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_word_id', 'direction', name='uix_user_word_direction'),
        Index('idx_card_direction_user_word_id', 'user_word_id'),
        Index('idx_card_direction_next_review', 'next_review'),
        Index('idx_card_direction_state', 'state'),
        Index('idx_card_direction_buried_until', 'buried_until'),
        Index('idx_card_direction_state_review', 'state', 'next_review'),
    )

    def __repr__(self):
        return f"<UserCardDirection {self.id}: word={self.user_word_id} {self.direction} state={self.state}>"

    def __init__(self, user_word_id, direction, source=None, **kwargs):
        from app.srs.constants import DEFAULT_EASE_FACTOR

        self.user_word_id = user_word_id
        self.direction = direction
        self.source = source
        self.state = 'new'
        self.step_index = 0
        self.lapses = 0
        self.repetitions = 0
        self.ease_factor = DEFAULT_EASE_FACTOR
        self.interval = 0
        self.correct_count = 0
        self.incorrect_count = 0
        self.next_review = datetime.now(timezone.utc).replace(tzinfo=None)
        self.buried_until = None
        for k, v in kwargs.items():
            setattr(self, k, v)

    def bury(self, hours: int = 24):
        """
        Bury this card - it won't be shown until the specified time.

        Args:
            hours: Number of hours to bury the card (default 24 = until tomorrow)
        """
        self.buried_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)

    def bury_for_session(self, session_duration_hours: int = 4):
        """
        Bury card for the rest of the study session.
        Default assumes a session is about 4 hours max.
        """
        self.buried_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=session_duration_hours)

    def unbury(self):
        """Remove bury status from this card."""
        self.buried_until = None

    @property
    def is_buried(self) -> bool:
        """Check if this card is currently buried."""
        if not self.buried_until:
            return False
        if self.buried_until.tzinfo is None:
            buried_aware = self.buried_until.replace(tzinfo=timezone.utc)
        else:
            buried_aware = self.buried_until
        return datetime.now(timezone.utc) < buried_aware

    @property
    def is_leech(self) -> bool:
        """
        Check if this card is a 'leech' (stuck card with many lapses).
        Leech cards should show hints/examples to help the user.
        """
        from app.srs.constants import LEECH_THRESHOLD
        return (self.lapses or 0) >= LEECH_THRESHOLD

    def update_after_review(self, quality):
        """
        Update SRS parameters after review using Anki-like state machine.

        SM-2 math delegated to UnifiedSRSService.calculate_sm2_update so both
        grading surfaces share one engine. This wrapper additionally updates
        UserWord aggregate counters (correct/incorrect counts, session_attempts)
        and first_reviewed/last_reviewed timestamps — fields not managed by
        the canonical grade_card path.

        Caller commits.

        Returns:
            interval_days (int)
        """
        from app.srs.constants import (
            RATING_DONT_KNOW, RATING_DOUBT,
            CardState, DEFAULT_EASE_FACTOR
        )
        from app.srs.service import UnifiedSRSService
        import random

        # Map to unified 1-2-3 scale for legacy compatibility
        if quality in (1, 2, 3):
            rating = quality
        elif quality == 0:
            rating = 1  # Legacy: 0 → Again
        else:
            rating = 3  # Legacy: 4-5 → Good

        # Update correct/incorrect count
        if rating >= RATING_DOUBT:
            self.correct_count = (self.correct_count or 0) + 1
        else:
            self.incorrect_count = (self.incorrect_count or 0) + 1

        # Increment session_attempts
        self.session_attempts = (self.session_attempts or 0) + 1

        # Naive-UTC convention — matches UserCardDirection column type (DateTime, no tz)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.last_reviewed = now

        # Set first_reviewed only on the first review (for new card limit tracking)
        if self.first_reviewed is None:
            self.first_reviewed = now

        # Delegate SM-2 math to the canonical engine
        update_result = UnifiedSRSService.calculate_sm2_update(
            rating=rating,
            state=self.state or CardState.NEW.value,
            step_index=self.step_index or 0,
            repetitions=self.repetitions or 0,
            interval=self.interval or 0,
            ease_factor=self.ease_factor or DEFAULT_EASE_FACTOR,
            lapses=self.lapses or 0,
        )

        # Apply SM-2 results
        self.state = update_result['state']
        self.step_index = update_result['step_index']
        self.repetitions = update_result['repetitions']
        self.interval = update_result['interval']
        self.ease_factor = update_result['ease_factor']
        self.lapses = update_result['lapses']

        # Apply leech bury if signalled by the engine
        bury_days = update_result.get('bury_days')
        if bury_days:
            self.buried_until = now + timedelta(days=bury_days)

        # Calculate next_review based on state
        requeue_minutes = update_result.get('requeue_minutes')
        days_until_review = update_result.get('days_until_review', 0)

        if self.state == CardState.REVIEW.value and days_until_review > 0:
            # Add ±10% variance to prevent review cliffs
            variance = random.uniform(0.9, 1.1)
            adjusted_interval = max(1, round(days_until_review * variance))
            self.next_review = now + timedelta(days=adjusted_interval)
        elif self.state in (CardState.LEARNING.value, CardState.RELEARNING.value):
            if requeue_minutes:
                self.next_review = now + timedelta(minutes=requeue_minutes)
            else:
                self.next_review = now
        else:
            self.next_review = now

        # Update the parent UserWord status if needed
        self.update_user_word_status()

        return self.interval

    def update_user_word_status(self):
        """Update the parent UserWord status based on card states using recalculate_status()"""
        # Flush first so that direction.all() query sees the updated state
        db.session.flush()
        user_word = UserWord.query.get(self.user_word_id)
        if user_word:
            user_word.recalculate_status()
            db.session.flush()  # Flush the status change

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

    # Per-deck limits (NULL = fallback to StudySettings)
    new_words_per_day = db.Column(db.Integer, nullable=True)
    reviews_per_day = db.Column(db.Integer, nullable=True)

    # Stats
    times_played = db.Column(db.Integer, default=0)
    average_score = db.Column(db.Float, default=0.0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('quiz_decks', lazy='dynamic', cascade='all, delete-orphan'))
    words = db.relationship('QuizDeckWord', back_populates='deck', cascade='all, delete-orphan', lazy='dynamic')
    results = db.relationship('QuizResult', back_populates='deck', cascade='all, delete-orphan', lazy='dynamic')
    parent_deck = db.relationship('QuizDeck', remote_side=[id], backref='forks')

    def get_new_words_limit(self, user_settings):
        """Get effective new words limit with fallback to user settings."""
        return self.new_words_per_day if self.new_words_per_day is not None else user_settings.new_words_per_day

    def get_reviews_limit(self, user_settings):
        """Get effective reviews limit with fallback to user settings."""
        return self.reviews_per_day if self.reviews_per_day is not None else user_settings.reviews_per_day

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
        """Get total number of words in deck.

        Returns the cached value set by batch-preloading in routes (via _word_count)
        to avoid N+1 queries when iterating over multiple decks.
        """
        if '_word_count' in self.__dict__:
            return self.__dict__['_word_count']
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
                # Get or create UserWord for the deck owner
                user_word = UserWord.get_or_create(self.user_id, parent_word.word_id)

                new_word = QuizDeckWord(
                    deck_id=self.id,
                    word_id=parent_word.word_id,
                    user_word_id=user_word.id,  # Link to owner's UserWord
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

    # Direct link to user's word learning status (for efficient statistics)
    user_word_id = db.Column(
        db.Integer,
        db.ForeignKey('user_words.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )

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
    user_word = db.relationship('UserWord', backref='deck_words')

    __table_args__ = (
        db.UniqueConstraint('deck_id', 'word_id', name='uix_deck_word'),
        Index('idx_deck_word_deck_id', 'deck_id'),
        Index('idx_deck_word_word_id', 'word_id'),
        Index('idx_deck_word_user_word_id', 'user_word_id'),
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
    seen_at = db.Column(db.DateTime, nullable=True)

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


class CustomWordList(db.Model):
    """User-created personal vocabulary list."""
    __tablename__ = 'custom_word_lists'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('custom_word_lists', lazy='dynamic', cascade='all, delete-orphan'))
    entries = db.relationship('CustomWordListEntry', back_populates='word_list', cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        Index('idx_custom_word_list_user_id', 'user_id'),
    )

    def __repr__(self):
        return f'<CustomWordList {self.id}: user={self.user_id} name={self.name!r}>'


class CustomWordListEntry(db.Model):
    """A word entry in a user's custom vocabulary list."""
    __tablename__ = 'custom_word_list_entries'

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('custom_word_lists.id', ondelete='CASCADE'), nullable=False)
    word = db.Column(db.Text, nullable=False)
    translation = db.Column(db.Text, nullable=False)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    word_list = db.relationship('CustomWordList', back_populates='entries')

    __table_args__ = (
        db.UniqueConstraint('list_id', 'word', name='uix_custom_list_word'),
        Index('idx_custom_word_list_entry_list_id', 'list_id'),
    )

    def __repr__(self):
        return f'<CustomWordListEntry {self.id}: list={self.list_id} word={self.word!r}>'
