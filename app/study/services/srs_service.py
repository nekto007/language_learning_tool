"""
SRS Service - Anki-like Spaced Repetition System logic

Responsibilities:
- Card scheduling with priority queues (RELEARNING > LEARNING > REVIEW > NEW)
- Review queue management
- Card updates after reviews
- Daily limits tracking
"""
from typing import List, Dict, Tuple, Set
from datetime import datetime, timezone
from sqlalchemy import func, and_, or_, case
from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.study.models import (
    UserWord, UserCardDirection, StudySettings, QuizDeckWord
)
from app.words.models import CollectionWords
from app.srs.constants import CardState


def get_user_word_ids(user_id: int, word_ids: List[int] = None) -> Set[int]:
    """
    Get set of word_ids that user has already started learning.
    Replaces multiple duplicate implementations across the codebase.

    Args:
        user_id: User ID
        word_ids: Optional list of word IDs to filter by

    Returns:
        Set of word_ids that the user has already started learning
    """
    query = db.session.query(UserWord.word_id).filter(
        UserWord.user_id == user_id
    )
    if word_ids:
        query = query.filter(UserWord.word_id.in_(word_ids))
    return {row[0] for row in query.all()}


class SRSService:
    """Service for Anki-like Spaced Repetition System logic.

    SRS-scheduling использует `UserCardDirection.update_after_review()`
    (Anki state machine, quality 1-2-3). Классический SM-2 (quality 0-5)
    в кодбейзе не используется.
    """

    @staticmethod
    def get_due_cards(
        user_id: int,
        deck_word_ids: List[int],
        limit: int = None,
        exclude_card_ids: List[int] = None
    ) -> List[UserCardDirection]:
        """
        Get cards that are due for review with Anki-like priority queue.

        Priority order:
        1. RELEARNING cards (due now)
        2. LEARNING cards (due now)
        3. REVIEW cards (due now)

        Args:
            user_id: User ID
            deck_word_ids: List of word IDs to include
            limit: Maximum number of cards to return
            exclude_card_ids: Card IDs to exclude (for anti-repeat)

        Returns:
            List of UserCardDirection objects due for review, ordered by priority
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Create a priority column for ordering
        # RELEARNING = 1, LEARNING = 2, REVIEW = 3, other = 4
        priority_order = case(
            (UserCardDirection.state == CardState.RELEARNING.value, 1),
            (UserCardDirection.state == CardState.LEARNING.value, 2),
            (UserCardDirection.state == CardState.REVIEW.value, 3),
            else_=4
        )

        query = db.session.query(UserCardDirection).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(deck_word_ids),
            UserCardDirection.next_review <= now,
            # Filter out buried cards
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now
            ),
            # Exclude NEW cards - they are handled separately
            or_(
                UserCardDirection.state == CardState.RELEARNING.value,
                UserCardDirection.state == CardState.LEARNING.value,
                UserCardDirection.state == CardState.REVIEW.value,
                # Legacy cards with repetitions > 0 are treated as REVIEW
                and_(
                    UserCardDirection.state.is_(None),
                    UserCardDirection.repetitions > 0
                )
            )
        )

        # Anti-repeat: exclude specified card IDs
        if exclude_card_ids:
            query = query.filter(~UserCardDirection.id.in_(exclude_card_ids))

        query = query.order_by(
            priority_order,
            UserCardDirection.next_review
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_new_words_count(user_id: int, deck_word_ids: List[int]) -> int:
        """Count words in deck that user hasn't started learning"""
        existing_word_ids = get_user_word_ids(user_id, deck_word_ids)
        return len([wid for wid in deck_word_ids if wid not in existing_word_ids])

    @staticmethod
    def check_daily_limits(user_id: int) -> Tuple[int, int, int, int]:
        """
        Check daily study limits

        New cards = cards where first_reviewed is today (first time ever studied)
        Reviews = cards reviewed today but first_reviewed was before today

        Returns:
            Tuple of (new_cards_studied_today, reviews_done_today, new_limit, review_limit)
        """
        settings = StudySettings.get_settings(user_id)
        today_start = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)

        # Count new cards: first_reviewed is today (card was studied for the first time today)
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.first_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        # Count reviews: last_reviewed is today BUT first_reviewed was before today
        reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_reviewed < today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        return (
            new_cards_today,
            reviews_today,
            settings.new_words_per_day,
            settings.reviews_per_day
        )

    @staticmethod
    def can_study_new_cards(user_id: int) -> bool:
        """Check if user can study new cards today"""
        new_today, _, new_limit, _ = SRSService.check_daily_limits(user_id)
        return new_today < new_limit

    @staticmethod
    def can_do_reviews(user_id: int) -> bool:
        """Check if user can do reviews today"""
        _, reviews_today, _, review_limit = SRSService.check_daily_limits(user_id)
        return reviews_today < review_limit

    @staticmethod
    def _compute_adaptive_state(user_id: int) -> Tuple[int, int, str]:
        """Internal: returns (adaptive_new, adaptive_reviews, reason).

        reason ∈ {'normal', 'accuracy_low', 'backlog_reduction'}.
        Accuracy takes precedence over backlog when both trigger.
        """
        settings = StudySettings.get_settings(user_id)
        base_new = settings.new_words_per_day
        base_reviews = settings.reviews_per_day
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        recent_cards = db.session.query(UserCardDirection).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.last_reviewed.isnot(None)
        ).order_by(UserCardDirection.last_reviewed.desc()).limit(50).all()

        total_correct = sum(c.correct_count or 0 for c in recent_cards)
        total_incorrect = sum(c.incorrect_count or 0 for c in recent_cards)
        total = total_correct + total_incorrect

        accuracy = (total_correct / total * 100) if total > 0 else 100

        backlog = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.next_review < now,
            UserCardDirection.state == 'review'
        ).scalar() or 0

        if accuracy < 85:
            return (min(2, base_new), base_reviews, 'accuracy_low')
        if backlog > 50:
            return (min(2, base_new), base_reviews, 'backlog_reduction')
        return (base_new, base_reviews, 'normal')

    @staticmethod
    def get_adaptive_limits(user_id: int) -> Tuple[int, int]:
        """
        Returns adaptive limits based on accuracy and backlog.

        If accuracy < 85% over last 50 reviews OR backlog > 50 overdue cards:
        → reduce new cards limit to min(2, base_limit)

        Returns:
            Tuple of (adaptive_new_limit, adaptive_review_limit)
        """
        adaptive_new, adaptive_reviews, _ = SRSService._compute_adaptive_state(user_id)
        return (adaptive_new, adaptive_reviews)

    @staticmethod
    def get_adaptive_limit_reason(user_id: int) -> str:
        """Returns reason for current adaptive new-card limit.

        One of 'normal', 'accuracy_low', 'backlog_reduction'. Used by
        /api/daily-status and /api/daily-plan to surface a one-time tooltip
        when the new-card cap is reduced.
        """
        _, _, reason = SRSService._compute_adaptive_state(user_id)
        return reason

    @staticmethod
    def get_card_counts(user_id: int, deck_word_ids: List[int] = None) -> Dict:
        """
        Get card counts for display (due, new, limits)

        Args:
            user_id: User ID
            deck_word_ids: Optional list of word IDs to filter by (for deck-specific counts)

        Returns:
            Dict with 'due_count', 'new_count', 'new_today', 'new_limit', 'can_study_new',
            'nothing_to_study', 'limit_reached'
        """
        settings = StudySettings.get_settings(user_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # End of today - show cards due anytime today (matches fetching logic)
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        if deck_word_ids:
            # Deck-specific counts
            # Filter by status to match the fetching logic (exclude 'mastered')
            # Use end_of_today to count all cards due today (matches fetching logic)
            due_count = db.session.query(func.count(UserCardDirection.id)).filter(
                UserCardDirection.user_word_id.in_(
                    db.session.query(UserWord.id).filter(
                        UserWord.user_id == user_id,
                        UserWord.word_id.in_(deck_word_ids),
                        UserWord.status.in_(['new', 'learning', 'review'])
                    )
                ),
                or_(
                    UserCardDirection.next_review.is_(None),
                    UserCardDirection.next_review <= end_of_today
                )
            ).scalar() or 0

            # Count new words: words without UserWord OR words with UserWord but no directions
            # Get word_ids that have UserCardDirection records
            words_with_directions = db.session.query(UserWord.word_id).join(
                UserCardDirection, UserWord.id == UserCardDirection.user_word_id
            ).filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(deck_word_ids)
            ).all()
            words_with_directions_set = {row[0] for row in words_with_directions}

            # New = deck words that don't have directions yet
            new_count = len([wid for wid in deck_word_ids if wid not in words_with_directions_set])
        else:
            # Auto mode - all cards
            # Include 'new' status to match fetching logic
            # Use end_of_today to count all cards due today (or NULL for new cards)
            due_count = UserCardDirection.query.join(
                UserWord, UserCardDirection.user_word_id == UserWord.id
            ).filter(
                UserWord.user_id == user_id,
                UserWord.status.in_(['new', 'learning', 'review']),
                or_(
                    UserCardDirection.next_review.is_(None),
                    UserCardDirection.next_review <= end_of_today
                )
            ).count()

            # Count all available new words (no UserWord OR UserWord exists but no directions)
            # Get word_ids that have directions
            words_with_directions_subquery = db.session.query(UserWord.word_id).join(
                UserCardDirection, UserWord.id == UserCardDirection.user_word_id
            ).filter(
                UserWord.user_id == user_id
            ).scalar_subquery()

            new_count = CollectionWords.query.outerjoin(
                UserWord,
                (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == user_id)
            ).filter(
                or_(
                    UserWord.id.is_(None),
                    ~CollectionWords.id.in_(words_with_directions_subquery)
                ),
                CollectionWords.russian_word.isnot(None),
                CollectionWords.russian_word != ''
            ).count()

        # New cards: first_reviewed is today (card was studied for the first time today)
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter_by(user_id=user_id)
            ),
            UserCardDirection.first_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        can_study_new = new_cards_today < settings.new_words_per_day
        nothing_to_study = due_count == 0 and (new_count == 0 or not can_study_new)
        limit_reached = new_count > 0 and not can_study_new

        return {
            'due_count': due_count,
            'new_count': new_count,
            'new_today': new_cards_today,
            'new_limit': settings.new_words_per_day,
            'can_study_new': can_study_new,
            'nothing_to_study': nothing_to_study,
            'limit_reached': limit_reached
        }

    @staticmethod
    def get_or_create_card_directions(user_word_id: int) -> Tuple[UserCardDirection, UserCardDirection]:
        """
        Get or create both card directions (en->ru, ru->en) for a word

        Returns:
            Tuple of (forward_card, backward_card)
        """
        # Forward direction (English -> Russian)
        forward = UserCardDirection.query.filter_by(
            user_word_id=user_word_id,
            direction='eng-rus'
        ).first()

        if not forward:
            forward = UserCardDirection(
                user_word_id=user_word_id,
                direction='eng-rus',
                next_review=datetime.now(timezone.utc)
            )
            db.session.add(forward)

        # Backward direction (Russian -> English)
        backward = UserCardDirection.query.filter_by(
            user_word_id=user_word_id,
            direction='rus-eng'
        ).first()

        if not backward:
            backward = UserCardDirection(
                user_word_id=user_word_id,
                direction='rus-eng',
                next_review=datetime.now(timezone.utc)
            )
            db.session.add(backward)

        db.session.flush()
        return forward, backward

    @staticmethod
    def update_word_status_after_review(user_word: UserWord) -> None:
        """
        Update UserWord status based on card performance

        Status transitions:
        - new/learning -> review (after successful repetitions)
        - review -> mastered (after interval > 21 days)
        """
        # Get both card directions
        forward = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction='eng-rus'
        ).first()

        backward = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction='rus-eng'
        ).first()

        if not forward or not backward:
            return

        # Calculate average performance
        avg_repetitions = (forward.repetitions + backward.repetitions) / 2
        avg_interval = (forward.interval + backward.interval) / 2

        # Update status based on performance
        # Note: 'mastered' is no longer a status - it's a threshold within 'review'
        # (is_mastered = min_interval >= 180 days)
        if user_word.status in ['new', 'learning']:
            if avg_repetitions >= 3:
                user_word.status = 'review'
        # 'review' status is the final status - mastered is computed from intervals

        db.session.flush()

    @classmethod
    def get_study_items(
        cls,
        user_id: int,
        deck_word_ids: List[int],
        limit: int,
        exclude_card_ids: List[int] = None
    ) -> List[Dict]:
        """
        Get items to study with Anki-like priority queue.

        Priority order:
        1. RELEARNING cards (due now) - failed reviews need immediate attention
        2. LEARNING cards (due now) - cards in learning steps
        3. REVIEW cards (due now) - regular spaced repetition
        4. NEW cards - fresh cards (with daily limit)

        Args:
            user_id: User ID
            deck_word_ids: List of word IDs in the deck
            limit: Maximum items to return
            exclude_card_ids: Card IDs to exclude (for anti-repeat)

        Returns:
            List of dictionaries with word, card, and state data
        """
        items = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Check daily limits
        can_new = cls.can_study_new_cards(user_id)
        can_review = cls.can_do_reviews(user_id)

        remaining = limit

        # Base filter for buried cards and anti-repeat
        def apply_filters(query):
            # Filter out buried cards
            query = query.filter(
                or_(
                    UserCardDirection.buried_until.is_(None),
                    UserCardDirection.buried_until <= now
                )
            )
            # Anti-repeat: exclude specified card IDs
            if exclude_card_ids:
                query = query.filter(~UserCardDirection.id.in_(exclude_card_ids))
            return query

        # PRIORITY 1: RELEARNING cards (always show first)
        if can_review and remaining > 0:
            relearning_query = db.session.query(UserCardDirection).join(
                UserWord, UserCardDirection.user_word_id == UserWord.id
            ).options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ).filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(deck_word_ids),
                UserCardDirection.state == CardState.RELEARNING.value,
                UserCardDirection.next_review <= now
            )
            relearning_query = apply_filters(relearning_query)
            relearning_cards = relearning_query.order_by(
                UserCardDirection.next_review
            ).limit(remaining).all()

            for card in relearning_cards:
                word = card.user_word.word  # Already loaded via joinedload
                if word:
                    items.append({
                        'type': 'relearning',
                        'state': CardState.RELEARNING.value,
                        'card': card,
                        'user_word': card.user_word,
                        'word': word
                    })
            remaining -= len(relearning_cards)

        # PRIORITY 2: LEARNING cards (in learning steps)
        if can_review and remaining > 0:
            learning_query = db.session.query(UserCardDirection).join(
                UserWord, UserCardDirection.user_word_id == UserWord.id
            ).options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ).filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(deck_word_ids),
                UserCardDirection.state == CardState.LEARNING.value,
                UserCardDirection.next_review <= now
            )
            learning_query = apply_filters(learning_query)
            learning_cards = learning_query.order_by(
                UserCardDirection.next_review
            ).limit(remaining).all()

            for card in learning_cards:
                word = card.user_word.word  # Already loaded via joinedload
                if word:
                    items.append({
                        'type': 'learning',
                        'state': CardState.LEARNING.value,
                        'card': card,
                        'user_word': card.user_word,
                        'word': word
                    })
            remaining -= len(learning_cards)

        # PRIORITY 3: REVIEW cards (due for review)
        if can_review and remaining > 0:
            review_query = db.session.query(UserCardDirection).join(
                UserWord, UserCardDirection.user_word_id == UserWord.id
            ).options(
                joinedload(UserCardDirection.user_word).joinedload(UserWord.word)
            ).filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(deck_word_ids),
                or_(
                    UserCardDirection.state == CardState.REVIEW.value,
                    # Legacy cards with repetitions > 0 are treated as REVIEW
                    and_(
                        UserCardDirection.state.is_(None),
                        UserCardDirection.repetitions > 0
                    )
                ),
                UserCardDirection.next_review <= now
            )
            review_query = apply_filters(review_query)
            review_cards = review_query.order_by(
                UserCardDirection.next_review
            ).limit(remaining).all()

            for card in review_cards:
                word = card.user_word.word  # Already loaded via joinedload
                if word:
                    items.append({
                        'type': 'review',
                        'state': CardState.REVIEW.value,
                        'card': card,
                        'user_word': card.user_word,
                        'word': word
                    })
            remaining -= len(review_cards)

        # PRIORITY 4: NEW cards (with daily limit)
        if can_new and remaining > 0:
            # Get words not yet in UserWord using the helper function
            existing_word_ids = get_user_word_ids(user_id, deck_word_ids)

            new_word_ids = [wid for wid in deck_word_ids if wid not in existing_word_ids]
            needed = min(remaining, len(new_word_ids))

            # Batch fetch all needed words to avoid N+1
            words_to_fetch = new_word_ids[:needed]
            words_by_id = {w.id: w for w in CollectionWords.query.filter(
                CollectionWords.id.in_(words_to_fetch)
            ).all()} if words_to_fetch else {}

            for word_id in words_to_fetch:
                word = words_by_id.get(word_id)
                if word:
                    # Create UserWord
                    user_word = UserWord(
                        user_id=user_id,
                        word_id=word_id,
                        status='learning'
                    )
                    db.session.add(user_word)
                    db.session.flush()

                    from app.study.deck_utils import ensure_word_in_default_deck
                    ensure_word_in_default_deck(user_id, word_id, user_word.id)

                    # Create cards with NEW state
                    forward, backward = cls.get_or_create_card_directions(user_word.id)

                    # Ensure state is set to NEW
                    for card in [forward, backward]:
                        if not card.state:
                            card.state = CardState.NEW.value
                            card.step_index = 0
                            card.lapses = 0

                    items.append({
                        'type': 'new',
                        'state': CardState.NEW.value,
                        'card': forward,
                        'user_word': user_word,
                        'word': word
                    })

        db.session.commit()
        return items

    @staticmethod
    def get_deck_stats_today(user_id: int, deck_id: int) -> Tuple[int, int]:
        """
        Count new cards and reviews done TODAY for a specific deck.

        New cards = cards where first_reviewed is today (first time ever studied)
        Reviews = cards reviewed today but first_reviewed was before today

        Args:
            user_id: User ID
            deck_id: Deck ID

        Returns:
            tuple: (new_cards_today, reviews_today)
        """
        today_start = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)

        # Get word IDs for this deck
        deck_word_ids = [dw.word_id for dw in QuizDeckWord.query.filter_by(deck_id=deck_id).all() if dw.word_id]

        if not deck_word_ids:
            return 0, 0

        # Count new cards: first_reviewed is today (card was studied for the first time today)
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(deck_word_ids),
            UserCardDirection.first_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        # Count reviews: last_reviewed is today BUT first_reviewed was before today
        reviews_today = db.session.query(func.count(UserCardDirection.id)).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(deck_word_ids),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_reviewed < today_start,
            UserCardDirection.first_reviewed.isnot(None)
        ).scalar() or 0

        return new_cards_today, reviews_today
