# app/grammar_lab/services/grammar_srs.py
"""
SRS (Spaced Repetition System) for grammar exercises.

Delegates to UnifiedSRSService for Anki-like state machine.
All SRS logic is at exercise level (UserGrammarExercise).
Topic-level data (theory, XP) is in UserGrammarTopicStatus.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any
import logging

from app.utils.db import db
from app.grammar_lab.models import (
    GrammarTopic, GrammarExercise,
    UserGrammarTopicStatus, UserGrammarExercise
)
from app.srs.constants import RATING_DONT_KNOW, RATING_KNOW, CardState

logger = logging.getLogger(__name__)


class GrammarSRS:
    """
    SRS for grammar exercises.

    Exercise-level SRS: delegated to UnifiedSRSService
    Topic-level status: theory_completed, xp_earned
    """

    def process_exercise_answer(
        self,
        user_id: int,
        exercise_id: int,
        is_correct: bool,
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Process exercise answer using Anki-like state machine.

        Args:
            user_id: User ID
            exercise_id: Exercise ID
            is_correct: Whether the answer was correct
            session_key: Optional session key for logging

        Returns:
            Dict with SRS update results
        """
        # Import here to avoid circular import
        from app.srs.service import unified_srs_service

        # Map binary result to 1-2-3 rating scale
        rating = RATING_KNOW if is_correct else RATING_DONT_KNOW

        # Delegate to UnifiedSRSService
        result = unified_srs_service.grade_grammar_exercise(
            exercise_id=exercise_id,
            rating=rating,
            user_id=user_id,
            session_key=session_key
        )

        return result

    def get_or_create_topic_status(self, user_id: int, topic_id: int) -> UserGrammarTopicStatus:
        """Get or create topic status record."""
        return UserGrammarTopicStatus.get_or_create(user_id, topic_id)

    def complete_theory(self, user_id: int, topic_id: int) -> UserGrammarTopicStatus:
        """Mark theory as completed for a topic."""
        status = self.get_or_create_topic_status(user_id, topic_id)

        if not status.theory_completed:
            status.theory_completed = True
            status.theory_completed_at = datetime.now(timezone.utc)
            db.session.commit()

        return status

    def add_xp(self, user_id: int, topic_id: int, amount: int) -> None:
        """Add XP to a topic."""
        status = self.get_or_create_topic_status(user_id, topic_id)
        status.add_xp(amount)
        db.session.commit()

    def get_topic_stats(self, user_id: int, topic_id: int) -> Dict:
        """
        Get computed stats for a topic based on exercise-level data.

        Returns:
            Dict with new_count, learning_count, review_count, mastered_count, etc.
        """
        exercises = GrammarExercise.query.filter_by(topic_id=topic_id).all()
        exercise_ids = [e.id for e in exercises]

        if not exercise_ids:
            return {
                'new_count': 0,
                'learning_count': 0,
                'review_count': 0,
                'mastered_count': 0,
                'total': 0,
                'accuracy': 0,
            }

        # Get exercise progress
        progress_records = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.exercise_id.in_(exercise_ids)
        ).all()

        progress_map = {p.exercise_id: p for p in progress_records}

        new_count = 0
        learning_count = 0
        review_count = 0
        mastered_count = 0
        total_correct = 0
        total_incorrect = 0

        for exercise_id in exercise_ids:
            progress = progress_map.get(exercise_id)

            if not progress or progress.state == CardState.NEW.value:
                new_count += 1
            elif progress.state in (CardState.LEARNING.value, CardState.RELEARNING.value):
                learning_count += 1
            elif progress.state == CardState.REVIEW.value:
                if progress.interval >= 180:
                    mastered_count += 1
                else:
                    review_count += 1

            if progress:
                total_correct += progress.correct_count or 0
                total_incorrect += progress.incorrect_count or 0

        total_attempts = total_correct + total_incorrect
        accuracy = round((total_correct / total_attempts * 100), 1) if total_attempts > 0 else 0

        return {
            'new_count': new_count,
            'learning_count': learning_count,
            'review_count': review_count,
            'mastered_count': mastered_count,
            'total': len(exercise_ids),
            'accuracy': accuracy,
        }

    def get_user_stats(self, user_id: int) -> Dict:
        """
        Get overall grammar stats for a user.

        Returns:
            Dict with aggregated stats
        """
        # Get all topic statuses
        statuses = UserGrammarTopicStatus.query.filter_by(user_id=user_id).all()

        # Get all exercises progress
        all_progress = UserGrammarExercise.query.filter_by(user_id=user_id).all()

        total_topics = GrammarTopic.query.count()
        total_xp = sum(s.xp_earned or 0 for s in statuses)
        theory_completed_count = sum(1 for s in statuses if s.theory_completed)

        # Count topics started (user has at least one exercise progress for the topic)
        topics_with_progress = set(p.exercise.topic_id for p in all_progress if p.exercise)
        topics_started = len(topics_with_progress)

        # Count topics mastered (all exercises in topic are mastered)
        # Build dict: topic_id -> list of exercise progress
        mastered_exercises_by_topic = {}
        for p in all_progress:
            if p.exercise and p.state == CardState.REVIEW.value and p.interval >= 180:
                topic_id = p.exercise.topic_id
                mastered_exercises_by_topic.setdefault(topic_id, set()).add(p.exercise_id)

        # Get exercise counts per topic
        all_topics = GrammarTopic.query.all()
        topics_mastered = 0
        for topic in all_topics:
            topic_exercise_ids = {e.id for e in topic.exercises}
            if topic_exercise_ids and topic.id in mastered_exercises_by_topic:
                mastered_in_topic = mastered_exercises_by_topic[topic.id]
                if mastered_in_topic >= topic_exercise_ids:  # All exercises mastered
                    topics_mastered += 1

        # Count by state
        new_count = sum(1 for p in all_progress if p.state == CardState.NEW.value)
        learning_count = sum(1 for p in all_progress if p.state in (CardState.LEARNING.value, CardState.RELEARNING.value))
        review_count = sum(1 for p in all_progress if p.state == CardState.REVIEW.value and p.interval < 180)
        mastered_count = sum(1 for p in all_progress if p.state == CardState.REVIEW.value and p.interval >= 180)

        total_correct = sum(p.correct_count or 0 for p in all_progress)
        total_incorrect = sum(p.incorrect_count or 0 for p in all_progress)
        total_attempts = total_correct + total_incorrect
        accuracy = round((total_correct / total_attempts * 100), 1) if total_attempts > 0 else 0

        # Stats by level
        by_level = {}
        for level in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']:
            level_topics = GrammarTopic.query.filter_by(level=level).all()
            level_topic_ids = [t.id for t in level_topics]

            if not level_topic_ids:
                by_level[level] = {'total': 0, 'mastered': 0, 'progress_pct': 0}
                continue

            # Get exercise IDs for this level
            level_exercises = GrammarExercise.query.filter(
                GrammarExercise.topic_id.in_(level_topic_ids)
            ).all()
            level_exercise_ids = [e.id for e in level_exercises]

            # Count mastered exercises
            level_mastered = sum(
                1 for p in all_progress
                if p.exercise_id in level_exercise_ids
                and p.state == CardState.REVIEW.value
                and p.interval >= 180
            )

            by_level[level] = {
                'total': len(level_exercise_ids),
                'mastered': level_mastered,
                'progress_pct': round((level_mastered / len(level_exercise_ids) * 100), 1) if level_exercise_ids else 0
            }

        return {
            'total_topics': total_topics,
            'topics_started': topics_started,
            'topics_mastered': topics_mastered,
            'theory_completed': theory_completed_count,
            'total_xp': total_xp,
            'total_exercises': len(all_progress),
            'new_count': new_count,
            'learning_count': learning_count,
            'review_count': review_count,
            'mastered_count': mastered_count,
            'total_attempts': total_attempts,
            'accuracy': accuracy,
            'overall_accuracy': accuracy,
            'by_level': by_level
        }
