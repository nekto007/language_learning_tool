# app/srs/stats_service.py
"""
Unified SRS Statistics Service.

Provides consistent statistics across all SRS-enabled modules:
- Words/Cards (via UserCardDirection)
- Grammar (via UserGrammarExercise)
- Curriculum (future)

This ensures a unified format for counters displayed across the app.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import logging

from sqlalchemy import func

from app.utils.db import db
from app.study.models import UserWord, UserCardDirection, QuizDeck, QuizDeckWord
from app.grammar_lab.models import (
    UserGrammarExercise, GrammarExercise, GrammarTopic, UserGrammarTopicStatus
)
from app.srs.constants import CardState

logger = logging.getLogger(__name__)


# Thresholds for mastered status (in days)
MASTERED_INTERVAL_THRESHOLD = 180
MATURE_INTERVAL_THRESHOLD = 21


class SRSStatsService:
    """
    Unified source of SRS statistics for any content type.

    Provides consistent format across modules:
    {
        'new_count': int,       # state = 'new'
        'learning_count': int,  # state in ('learning', 'relearning')
        'review_count': int,    # state = 'review' AND interval < 180
        'mastered_count': int,  # state = 'review' AND interval >= 180
        'total': int,
        'due_today': int,       # Items due for review today
    }
    """

    @staticmethod
    def get_words_stats(
        user_id: int,
        deck_id: int = None,
        word_ids: List[int] = None
    ) -> Dict[str, int]:
        """
        Get SRS stats for words/cards.

        Args:
            user_id: User ID
            deck_id: Optional deck filter
            word_ids: Optional list of specific word IDs

        Returns:
            Dict with stats (new_count, learning_count, review_count, mastered_count, total, due_today)
        """
        now = datetime.now(timezone.utc)

        # Build base query for UserCardDirection
        base_query = (
            db.session.query(UserCardDirection)
            .join(UserWord)
            .filter(UserWord.user_id == user_id)
        )

        # Filter by deck if provided
        if deck_id:
            deck_word_ids = db.session.query(QuizDeckWord.word_id).filter(
                QuizDeckWord.deck_id == deck_id,
                QuizDeckWord.word_id.isnot(None)
            ).subquery()
            base_query = base_query.filter(UserWord.word_id.in_(deck_word_ids))

        # Filter by specific word IDs if provided
        if word_ids:
            base_query = base_query.filter(UserWord.word_id.in_(word_ids))

        # Only count one direction to avoid double counting words
        base_query = base_query.filter(UserCardDirection.direction == 'eng-rus')

        # Get all cards for counting
        cards = base_query.all()

        new_count = 0
        learning_count = 0
        review_count = 0
        mastered_count = 0
        due_today = 0

        for card in cards:
            state = card.state or CardState.NEW.value

            if state == CardState.NEW.value:
                new_count += 1
            elif state in (CardState.LEARNING.value, CardState.RELEARNING.value):
                learning_count += 1
                if card.next_review and card.next_review <= now:
                    due_today += 1
            elif state == CardState.REVIEW.value:
                if card.interval and card.interval >= MASTERED_INTERVAL_THRESHOLD:
                    mastered_count += 1
                else:
                    review_count += 1
                if card.next_review and card.next_review <= now:
                    due_today += 1

        # Add new cards to due_today (they're always due)
        due_today += new_count

        return {
            'new_count': new_count,
            'learning_count': learning_count,
            'review_count': review_count,
            'mastered_count': mastered_count,
            'total': new_count + learning_count + review_count + mastered_count,
            'due_today': due_today
        }

    @staticmethod
    def get_grammar_stats(
        user_id: int,
        topic_id: int = None,
        level: str = None
    ) -> Dict[str, int]:
        """
        Get SRS stats for grammar exercises.

        Args:
            user_id: User ID
            topic_id: Optional topic filter
            level: Optional CEFR level filter (A1, A2, etc.)

        Returns:
            Dict with stats (new_count, learning_count, review_count, mastered_count, total, due_today)
        """
        now = datetime.now(timezone.utc)

        # Get exercise IDs based on filters
        exercise_query = GrammarExercise.query

        if topic_id:
            exercise_query = exercise_query.filter(GrammarExercise.topic_id == topic_id)
        elif level:
            exercise_query = exercise_query.join(GrammarTopic).filter(GrammarTopic.level == level)

        exercise_ids = [e.id for e in exercise_query.all()]

        if not exercise_ids:
            return {
                'new_count': 0,
                'learning_count': 0,
                'review_count': 0,
                'mastered_count': 0,
                'total': 0,
                'due_today': 0
            }

        # Get user progress for these exercises
        progress_records = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.exercise_id.in_(exercise_ids)
        ).all()

        # Create lookup for quick access
        progress_map = {p.exercise_id: p for p in progress_records}

        new_count = 0
        learning_count = 0
        review_count = 0
        mastered_count = 0
        due_today = 0

        for exercise_id in exercise_ids:
            progress = progress_map.get(exercise_id)

            if not progress:
                # No progress = new exercise
                new_count += 1
                due_today += 1  # New items are always due
                continue

            state = progress.state or CardState.NEW.value

            if state == CardState.NEW.value:
                new_count += 1
                due_today += 1
            elif state in (CardState.LEARNING.value, CardState.RELEARNING.value):
                learning_count += 1
                if progress.next_review and progress.next_review <= now:
                    due_today += 1
            elif state == CardState.REVIEW.value:
                if progress.interval and progress.interval >= MASTERED_INTERVAL_THRESHOLD:
                    mastered_count += 1
                else:
                    review_count += 1
                if progress.next_review and progress.next_review <= now:
                    due_today += 1

        return {
            'new_count': new_count,
            'learning_count': learning_count,
            'review_count': review_count,
            'mastered_count': mastered_count,
            'total': len(exercise_ids),
            'due_today': due_today
        }

    @staticmethod
    def get_stats(
        user_id: int,
        item_type: str,
        source_id: int = None
    ) -> Dict[str, int]:
        """
        Unified entry point for getting SRS stats.

        Args:
            user_id: User ID
            item_type: Type of content ('words', 'grammar', 'curriculum')
            source_id: Optional source ID (deck_id, topic_id, lesson_id)

        Returns:
            Dict with consistent stats format
        """
        if item_type == 'words':
            return SRSStatsService.get_words_stats(user_id, deck_id=source_id)
        elif item_type == 'grammar':
            return SRSStatsService.get_grammar_stats(user_id, topic_id=source_id)
        elif item_type == 'curriculum':
            # Future: implement curriculum stats
            return {
                'new_count': 0,
                'learning_count': 0,
                'review_count': 0,
                'mastered_count': 0,
                'total': 0,
                'due_today': 0
            }
        else:
            logger.warning(f"Unknown item_type: {item_type}")
            return {
                'new_count': 0,
                'learning_count': 0,
                'review_count': 0,
                'mastered_count': 0,
                'total': 0,
                'due_today': 0
            }

    @staticmethod
    def get_user_overview(user_id: int) -> Dict[str, Any]:
        """
        Get overview stats for a user across all modules.

        Returns:
            Dict with stats per module and totals
        """
        words_stats = SRSStatsService.get_words_stats(user_id)
        grammar_stats = SRSStatsService.get_grammar_stats(user_id)

        return {
            'words': words_stats,
            'grammar': grammar_stats,
            'totals': {
                'new_count': words_stats['new_count'] + grammar_stats['new_count'],
                'learning_count': words_stats['learning_count'] + grammar_stats['learning_count'],
                'review_count': words_stats['review_count'] + grammar_stats['review_count'],
                'mastered_count': words_stats['mastered_count'] + grammar_stats['mastered_count'],
                'total': words_stats['total'] + grammar_stats['total'],
                'due_today': words_stats['due_today'] + grammar_stats['due_today']
            }
        }

    @staticmethod
    def get_grammar_topics_stats(user_id: int, level: str = None) -> List[Dict]:
        """
        Get SRS stats for each grammar topic.

        Args:
            user_id: User ID
            level: Optional CEFR level filter

        Returns:
            List of topic dicts with stats
        """
        # Get topics
        topic_query = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order)
        if level:
            topic_query = topic_query.filter(GrammarTopic.level == level)

        topics = topic_query.all()
        result = []

        for topic in topics:
            stats = SRSStatsService.get_grammar_stats(user_id, topic_id=topic.id)

            # Get topic status
            topic_status = UserGrammarTopicStatus.query.filter_by(
                user_id=user_id,
                topic_id=topic.id
            ).first()

            result.append({
                'id': topic.id,
                'slug': topic.slug,
                'title': topic.title,
                'title_ru': topic.title_ru,
                'level': topic.level,
                'srs_stats': stats,
                'theory_completed': topic_status.theory_completed if topic_status else False,
                'xp_earned': topic_status.xp_earned if topic_status else 0
            })

        return result


# Singleton instance for convenience
srs_stats_service = SRSStatsService()
