# app/curriculum/services/srs_service.py

import logging
from datetime import UTC, datetime
from typing import Dict

from app.curriculum.models import Lessons
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWordLink, CollectionWords

logger = logging.getLogger(__name__)


class SRSService:
    """Service for Spaced Repetition System (SRS) functionality"""

    @staticmethod
    def get_cards_for_lesson(lesson: Lessons, user_id: int) -> Dict:
        """
        Get cards for SRS lesson
        
        Args:
            lesson: SRS lesson
            user_id: User ID
            
        Returns:
            Dictionary with card statistics and due cards
        """
        try:
            if lesson.type != 'card':
                raise ValueError("Not a card lesson")

            # Get collection words
            collection_id = lesson.collection_id
            if not collection_id:
                return {
                    'total_due': 0,
                    'new_cards': 0,
                    'review_cards': 0,
                    'cards': []
                }

            # Get all words in collection
            word_links = CollectionWordLink.query.filter_by(
                collection_id=collection_id
            ).all()
            word_ids = [link.word_id for link in word_links]

            # Get or create UserWord entries
            user_words = []
            for word_id in word_ids:
                user_word = UserWord.get_or_create(user_id, word_id)
                user_words.append(user_word)

            # Get due cards
            now = datetime.now(UTC)
            due_directions = []
            new_cards = 0
            review_cards = 0

            for user_word in user_words:
                # Check each direction
                for direction in ['eng-rus', 'rus-eng']:
                    card_dir = UserCardDirection.query.filter_by(
                        user_word_id=user_word.id,
                        direction=direction
                    ).first()

                    if not card_dir:
                        # New card
                        card_dir = UserCardDirection(
                            user_word_id=user_word.id,
                            direction=direction
                        )
                        db.session.add(card_dir)
                        new_cards += 1
                        due_directions.append(card_dir)
                    elif card_dir.next_review <= now:
                        # Review card
                        review_cards += 1
                        due_directions.append(card_dir)

            db.session.commit()

            # Get SRS settings from lesson
            srs_settings = lesson.get_srs_settings()
            max_new_cards = srs_settings.get('new_cards_limit', 10)

            # Limit new cards
            new_card_dirs = [d for d in due_directions if d.repetitions == 0]
            review_card_dirs = [d for d in due_directions if d.repetitions > 0]

            # Take limited new cards + all review cards
            selected_cards = review_card_dirs + new_card_dirs[:max_new_cards]

            return {
                'total_due': len(selected_cards),
                'new_cards': min(new_cards, max_new_cards),
                'review_cards': review_cards,
                'cards': selected_cards,
                'srs_settings': srs_settings
            }

        except Exception as e:
            logger.error(f"Error getting cards for lesson: {str(e)}")
            return {
                'total_due': 0,
                'new_cards': 0,
                'review_cards': 0,
                'cards': []
            }

    @staticmethod
    def get_card_session_for_lesson(lesson: Lessons, user_id: int) -> Dict:
        """
        Get card session data for frontend
        
        Args:
            lesson: SRS lesson
            user_id: User ID
            
        Returns:
            Dictionary with session data
        """
        try:
            cards_data = SRSService.get_cards_for_lesson(lesson, user_id)

            if cards_data['total_due'] == 0:
                return {
                    'cards': [],
                    'total_cards': 0,
                    'completed': True
                }

            # Prepare cards for frontend
            session_cards = []

            for card_dir in cards_data['cards']:
                user_word = UserWord.query.get(card_dir.user_word_id)
                word = CollectionWords.query.get(user_word.word_id)

                if word:
                    card_data = {
                        'id': card_dir.id,
                        'word_id': word.id,
                        'direction': card_dir.direction,
                        'front': word.english_word if card_dir.direction == 'eng-rus' else word.russian_word,
                        'back': word.russian_word if card_dir.direction == 'eng-rus' else word.english_word,
                        'is_new': card_dir.repetitions == 0,
                        'repetitions': card_dir.repetitions,
                        'ease_factor': card_dir.ease_factor,
                        'interval': card_dir.interval,
                        'hint': '',  # Can be added from lesson content
                        'example': '',  # Can be added from lesson content
                        'audio_url': word.audio_url if hasattr(word,
                                                               'audio_url') and card_dir.direction == 'eng-rus' else None
                    }
                    session_cards.append(card_data)

            return {
                'cards': session_cards,
                'total_cards': len(session_cards),
                'new_cards': cards_data['new_cards'],
                'review_cards': cards_data['review_cards'],
                'completed': False,
                'settings': cards_data.get('srs_settings', {})
            }

        except Exception as e:
            logger.error(f"Error getting card session: {str(e)}")
            return {
                'cards': [],
                'total_cards': 0,
                'completed': True,
                'error': str(e)
            }

    @staticmethod
    def process_card_review(
            lesson_id: int,
            user_id: int,
            word_id: int,
            direction: str,
            quality: int
    ) -> Dict:
        """
        Process card review
        
        Args:
            lesson_id: Lesson ID
            user_id: User ID
            word_id: Word ID
            direction: Card direction ('eng-rus' or 'rus-eng')
            quality: Review quality (0-5)
            
        Returns:
            Result dictionary
        """
        try:
            # Get user word
            user_word = UserWord.query.filter_by(
                user_id=user_id,
                word_id=word_id
            ).first()

            if not user_word:
                return {
                    'success': False,
                    'error': 'Word not found for user'
                }

            # Get card direction
            card_dir = UserCardDirection.query.filter_by(
                user_word_id=user_word.id,
                direction=direction
            ).first()

            if not card_dir:
                return {
                    'success': False,
                    'error': 'Card direction not found'
                }

            # Update card based on review
            old_interval = card_dir.interval
            new_interval = card_dir.update_after_review(quality)

            # Increment session attempts
            card_dir.session_attempts += 1

            db.session.commit()

            # Check if lesson is complete
            cards_data = SRSService.get_cards_for_lesson(
                Lessons.query.get(lesson_id),
                user_id
            )

            lesson_complete = cards_data['total_due'] == 0

            # Update lesson progress if complete
            if lesson_complete:
                from app.curriculum.services.progress_service import ProgressService
                ProgressService.create_or_update_progress(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    status='completed',
                    score=100.0,
                    data={
                        'completed_at': datetime.now(UTC).isoformat(),
                        'total_reviews': card_dir.session_attempts
                    }
                )

            return {
                'success': True,
                'old_interval': old_interval,
                'new_interval': new_interval,
                'next_review': card_dir.next_review.isoformat(),
                'lesson_complete': lesson_complete,
                'remaining_cards': cards_data['total_due']
            }

        except Exception as e:
            logger.error(f"Error processing card review: {str(e)}")
            db.session.rollback()
            return {
                'success': False,
                'error': 'Failed to process review'
            }

    @staticmethod
    def get_user_srs_statistics(user_id: int) -> Dict:
        """
        Get user's SRS statistics
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with SRS statistics
        """
        try:
            # Get all user words
            user_words = UserWord.query.filter_by(user_id=user_id).all()

            # Calculate statistics
            # Note: 'mastered' is no longer a status - it's a threshold within 'review'
            total_words = len(user_words)
            new_words = sum(1 for uw in user_words if uw.status == 'new')
            learning_words = sum(1 for uw in user_words if uw.status == 'learning')
            # Review words that are not mastered
            review_words = sum(1 for uw in user_words if uw.status == 'review' and not uw.is_mastered)
            # Mastered = review status + min_interval >= 180 days
            mastered_words = sum(1 for uw in user_words if uw.is_mastered)

            # Get due cards count
            now = datetime.now(UTC)
            due_cards = UserCardDirection.query.join(
                UserWord
            ).filter(
                UserWord.user_id == user_id,
                UserCardDirection.next_review <= now
            ).count()

            # Calculate retention rate
            total_reviews = db.session.query(
                db.func.sum(UserCardDirection.correct_count + UserCardDirection.incorrect_count)
            ).join(
                UserWord
            ).filter(
                UserWord.user_id == user_id
            ).scalar() or 0

            correct_reviews = db.session.query(
                db.func.sum(UserCardDirection.correct_count)
            ).join(
                UserWord
            ).filter(
                UserWord.user_id == user_id
            ).scalar() or 0

            retention_rate = round((correct_reviews / total_reviews * 100) if total_reviews > 0 else 0)

            return {
                'total_words': total_words,
                'new_words': new_words,
                'learning_words': learning_words,
                'review_words': review_words,
                'mastered_words': mastered_words,
                'due_cards': due_cards,
                'retention_rate': retention_rate,
                'total_reviews': total_reviews
            }

        except Exception as e:
            logger.error(f"Error getting SRS statistics: {str(e)}")
            return {
                'total_words': 0,
                'new_words': 0,
                'learning_words': 0,
                'review_words': 0,
                'mastered_words': 0,
                'due_cards': 0,
                'retention_rate': 0,
                'total_reviews': 0
            }
