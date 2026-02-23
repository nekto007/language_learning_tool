# app/srs/stats_service.py
"""
Unified SRS Statistics Service.

Single source of truth for SRS statistics across all modules:
- Words/Cards (via UserCardDirection)
- Grammar (via UserGrammarExercise)

Uses count_srs_states() utility for all state counting.
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
from app.srs.utils import count_srs_states, count_srs_states_with_accuracy
from app.srs.mixins import SRSFieldsMixin

logger = logging.getLogger(__name__)


class _NewPlaceholder(SRSFieldsMixin):
    """Represents an exercise/card with no user progress (= new)."""
    state = 'new'
    interval = 0
    next_review = None
    correct_count = 0
    incorrect_count = 0


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

        cards = base_query.all()
        return count_srs_states(cards)

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
                'due_today': 0,
                'accuracy': 0,
            }

        progress_records = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.exercise_id.in_(exercise_ids)
        ).all()

        progress_map = {p.exercise_id: p for p in progress_records}

        # Build list: real progress or placeholder for unstarted exercises
        items = []
        for exercise_id in exercise_ids:
            progress = progress_map.get(exercise_id)
            items.append(progress if progress else _NewPlaceholder())

        return count_srs_states_with_accuracy(items)

    @staticmethod
    def get_grammar_stats_batch(
        user_id: int,
        topic_ids: List[int]
    ) -> Dict[int, Dict]:
        """
        Batch SRS stats for multiple grammar topics. 2 queries instead of 2*N.

        Returns:
            Dict mapping topic_id to stats dict.
        """
        if not topic_ids:
            return {}

        empty_stats = {
            'new_count': 0, 'learning_count': 0, 'review_count': 0,
            'mastered_count': 0, 'total': 0, 'due_today': 0, 'accuracy': 0,
        }

        exercises = GrammarExercise.query.filter(
            GrammarExercise.topic_id.in_(topic_ids)
        ).all()

        if not exercises:
            return {tid: dict(empty_stats) for tid in topic_ids}

        exercises_by_topic = {}
        all_exercise_ids = []
        for ex in exercises:
            exercises_by_topic.setdefault(ex.topic_id, []).append(ex.id)
            all_exercise_ids.append(ex.id)

        progress_records = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.exercise_id.in_(all_exercise_ids)
        ).all()
        progress_map = {p.exercise_id: p for p in progress_records}

        result = {}
        for tid in topic_ids:
            ex_ids = exercises_by_topic.get(tid, [])
            if not ex_ids:
                result[tid] = dict(empty_stats)
                continue

            items = []
            for eid in ex_ids:
                progress = progress_map.get(eid)
                items.append(progress if progress else _NewPlaceholder())

            result[tid] = count_srs_states_with_accuracy(items)

        return result

    @staticmethod
    def get_grammar_user_stats(user_id: int) -> Dict:
        """
        Get overall grammar stats for a user.

        Returns:
            Dict with aggregated stats, topics progress, and by-level breakdown.
        """
        from app.srs.constants import CardState, MASTERED_THRESHOLD_DAYS

        statuses = UserGrammarTopicStatus.query.filter_by(user_id=user_id).all()
        all_progress = UserGrammarExercise.query.filter_by(user_id=user_id).all()

        total_topics = GrammarTopic.query.count()
        total_xp = sum(s.xp_earned or 0 for s in statuses)
        theory_completed_count = sum(1 for s in statuses if s.theory_completed)

        topics_with_progress = set(p.exercise.topic_id for p in all_progress if p.exercise)
        topics_started = len(topics_with_progress)

        # Count topics mastered (all exercises in topic are mastered)
        mastered_exercises_by_topic = {}
        for p in all_progress:
            if p.exercise and p.is_mastered:
                topic_id = p.exercise.topic_id
                mastered_exercises_by_topic.setdefault(topic_id, set()).add(p.exercise_id)

        all_topics = GrammarTopic.query.all()
        topics_mastered = 0
        for topic in all_topics:
            topic_exercise_ids = {e.id for e in topic.exercises}
            if topic_exercise_ids and topic.id in mastered_exercises_by_topic:
                if mastered_exercises_by_topic[topic.id] >= topic_exercise_ids:
                    topics_mastered += 1

        # Use count_srs_states for aggregated counting
        stats = count_srs_states_with_accuracy(all_progress)

        # Stats by level
        by_level = {}
        for level in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']:
            level_topics = GrammarTopic.query.filter_by(level=level).all()
            level_topic_ids = [t.id for t in level_topics]

            if not level_topic_ids:
                by_level[level] = {'total': 0, 'mastered': 0, 'progress_pct': 0}
                continue

            level_exercises = GrammarExercise.query.filter(
                GrammarExercise.topic_id.in_(level_topic_ids)
            ).all()
            level_exercise_ids = set(e.id for e in level_exercises)

            level_mastered = sum(
                1 for p in all_progress
                if p.exercise_id in level_exercise_ids and p.is_mastered
            )

            by_level[level] = {
                'total': len(level_exercise_ids),
                'mastered': level_mastered,
                'progress_pct': round(level_mastered / len(level_exercise_ids) * 100, 1) if level_exercise_ids else 0
            }

        return {
            'total_topics': total_topics,
            'topics_started': topics_started,
            'topics_mastered': topics_mastered,
            'theory_completed': theory_completed_count,
            'total_xp': total_xp,
            'total_exercises': len(all_progress),
            'new_count': stats['new_count'],
            'learning_count': stats['learning_count'],
            'review_count': stats['review_count'],
            'mastered_count': stats['mastered_count'],
            'total_attempts': sum((p.correct_count or 0) + (p.incorrect_count or 0) for p in all_progress),
            'accuracy': stats.get('accuracy', 0),
            'overall_accuracy': stats.get('accuracy', 0),
            'by_level': by_level
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
