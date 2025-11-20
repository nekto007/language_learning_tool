"""
SRS Service - Spaced Repetition System logic

Responsibilities:
- Card scheduling (SM-2 algorithm)
- Review queue management
- Card updates after reviews
- Daily limits tracking
"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, and_

from app.utils.db import db
from app.study.models import (
    UserWord, UserCardDirection, StudySettings, StudySession
)
from app.words.models import CollectionWords


class SRSService:
    """Service for Spaced Repetition System logic"""

    @staticmethod
    def get_due_cards(user_id: int, deck_word_ids: List[int], limit: int = None) -> List[UserCardDirection]:
        """
        Get cards that are due for review

        Args:
            user_id: User ID
            deck_word_ids: List of word IDs to include
            limit: Maximum number of cards to return

        Returns:
            List of UserCardDirection objects due for review
        """
        query = db.session.query(UserCardDirection).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(deck_word_ids),
            UserCardDirection.next_review <= datetime.now(timezone.utc)
        ).order_by(
            UserCardDirection.next_review
        )

        if limit:
            query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_new_words_count(user_id: int, deck_word_ids: List[int]) -> int:
        """Count words in deck that user hasn't started learning"""
        existing_word_ids = {
            row[0] for row in db.session.query(UserWord.word_id).filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(deck_word_ids)
            ).all()
        }
        return len([wid for wid in deck_word_ids if wid not in existing_word_ids])

    @staticmethod
    def check_daily_limits(user_id: int) -> Tuple[int, int, int, int]:
        """
        Check daily study limits

        Returns:
            Tuple of (new_cards_studied_today, reviews_done_today, new_limit, review_limit)
        """
        settings = StudySettings.get_settings(user_id)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Count new cards studied today (cards with first_seen today)
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.first_seen >= today_start
        ).scalar() or 0

        # Count reviews done today
        reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
            ),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_seen < today_start  # Exclude new cards
        ).scalar() or 0

        return (
            new_cards_today,
            reviews_today,
            settings.new_cards_per_day,
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
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        if deck_word_ids:
            # Deck-specific counts
            due_count = db.session.query(func.count(UserCardDirection.id)).filter(
                UserCardDirection.user_word_id.in_(
                    db.session.query(UserWord.id).filter(
                        UserWord.user_id == user_id,
                        UserWord.word_id.in_(deck_word_ids)
                    )
                ),
                UserCardDirection.next_review <= datetime.now(timezone.utc)
            ).scalar() or 0

            # Get existing user words for this deck
            existing_word_ids = {
                row[0] for row in db.session.query(UserWord.word_id).filter(
                    UserWord.user_id == user_id,
                    UserWord.word_id.in_(deck_word_ids)
                ).all()
            }
            new_count = len([wid for wid in deck_word_ids if wid not in existing_word_ids])
        else:
            # Auto mode - all cards
            due_count = UserCardDirection.query.join(
                UserWord, UserCardDirection.user_word_id == UserWord.id
            ).filter(
                UserWord.user_id == user_id,
                UserWord.status.in_(['learning', 'review']),
                UserCardDirection.next_review <= datetime.now(timezone.utc)
            ).count()

            # Count all available new words
            new_count = CollectionWords.query.outerjoin(
                UserWord,
                (CollectionWords.id == UserWord.word_id) & (UserWord.user_id == user_id)
            ).filter(
                UserWord.id == None,
                CollectionWords.russian_word.isnot(None),
                CollectionWords.russian_word != ''
            ).count()

        # New cards studied today
        new_cards_today = db.session.query(func.count(UserCardDirection.id)).filter(
            UserCardDirection.user_word_id.in_(
                db.session.query(UserWord.id).filter_by(user_id=user_id)
            ),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.repetitions == 1
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
            direction='forward'
        ).first()

        if not forward:
            forward = UserCardDirection(
                user_word_id=user_word_id,
                direction='forward',
                next_review=datetime.now(timezone.utc)
            )
            db.session.add(forward)

        # Backward direction (Russian -> English)
        backward = UserCardDirection.query.filter_by(
            user_word_id=user_word_id,
            direction='backward'
        ).first()

        if not backward:
            backward = UserCardDirection(
                user_word_id=user_word_id,
                direction='backward',
                next_review=datetime.now(timezone.utc)
            )
            db.session.add(backward)

        db.session.flush()
        return forward, backward

    @staticmethod
    def update_card_after_review(card: UserCardDirection, quality: int) -> None:
        """
        Update card using SM-2 algorithm

        Args:
            card: UserCardDirection object to update
            quality: Quality rating (0-5)
                0-2: Incorrect (reset card)
                3-5: Correct (advance card)
        """
        now = datetime.now(timezone.utc)

        # First review of the card
        if card.first_seen is None:
            card.first_seen = now

        card.last_reviewed = now
        card.review_count += 1

        if quality < 3:
            # Failed - reset card
            card.interval = 1
            card.repetitions = 0
            card.easiness_factor = max(1.3, card.easiness_factor - 0.2)
            card.next_review = now + timedelta(days=1)
        else:
            # Success - advance card using SM-2
            if card.repetitions == 0:
                card.interval = 1
            elif card.repetitions == 1:
                card.interval = 6
            else:
                card.interval = int(card.interval * card.easiness_factor)

            card.repetitions += 1

            # Update easiness factor
            new_ef = card.easiness_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            card.easiness_factor = max(1.3, new_ef)

            # Schedule next review
            card.next_review = now + timedelta(days=card.interval)

        db.session.flush()

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
            direction='forward'
        ).first()

        backward = UserCardDirection.query.filter_by(
            user_word_id=user_word.id,
            direction='backward'
        ).first()

        if not forward or not backward:
            return

        # Calculate average performance
        avg_repetitions = (forward.repetitions + backward.repetitions) / 2
        avg_interval = (forward.interval + backward.interval) / 2

        # Update status based on performance
        if user_word.status in ['new', 'learning']:
            if avg_repetitions >= 3:
                user_word.status = 'review'
        elif user_word.status == 'review':
            if avg_interval > 21:  # 3 weeks
                user_word.status = 'mastered'

        db.session.flush()

    @classmethod
    def get_study_items(cls, user_id: int, deck_word_ids: List[int], limit: int) -> List[Dict]:
        """
        Get items to study (mix of due reviews and new words)

        Args:
            user_id: User ID
            deck_word_ids: List of word IDs in the deck
            limit: Maximum items to return

        Returns:
            List of dictionaries with word and card data
        """
        items = []

        # Check daily limits
        can_new = cls.can_study_new_cards(user_id)
        can_review = cls.can_do_reviews(user_id)

        # Get due cards if reviews allowed
        if can_review:
            due_cards = cls.get_due_cards(user_id, deck_word_ids, limit=limit)
            for card in due_cards:
                user_word = card.user_word
                word = CollectionWords.query.get(user_word.word_id)
                if word:
                    items.append({
                        'type': 'review',
                        'card': card,
                        'user_word': user_word,
                        'word': word
                    })

        # Add new words if allowed and we haven't hit limit
        if can_new and len(items) < limit:
            # Get words not yet in UserWord
            existing_word_ids = {
                row[0] for row in db.session.query(UserWord.word_id).filter(
                    UserWord.user_id == user_id,
                    UserWord.word_id.in_(deck_word_ids)
                ).all()
            }

            new_word_ids = [wid for wid in deck_word_ids if wid not in existing_word_ids]
            needed = min(limit - len(items), len(new_word_ids))

            for word_id in new_word_ids[:needed]:
                word = CollectionWords.query.get(word_id)
                if word:
                    # Create UserWord
                    user_word = UserWord(
                        user_id=user_id,
                        word_id=word_id,
                        status='learning'
                    )
                    db.session.add(user_word)
                    db.session.flush()

                    # Create cards
                    forward, backward = cls.get_or_create_card_directions(user_word.id)

                    items.append({
                        'type': 'new',
                        'card': forward,
                        'user_word': user_word,
                        'word': word
                    })

        db.session.commit()
        return items
