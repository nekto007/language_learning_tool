# app/grammar_lab/services/grammar_srs.py
"""
SRS (Spaced Repetition System) for grammar exercises.

Delegates to UnifiedSRSService for Anki-like state machine.
All SRS logic is at exercise level (UserGrammarExercise).
Topic-level data (theory, XP) is in UserGrammarTopicStatus.
"""

from datetime import datetime, timezone
from typing import Dict, Any
import logging

from app.utils.db import db
from app.grammar_lab.models import UserGrammarTopicStatus
from app.srs.constants import RATING_DONT_KNOW, RATING_KNOW

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

    # Stats methods moved to app/srs/stats_service.py:SRSStatsService
    # - get_topic_stats → SRSStatsService.get_grammar_stats(topic_id=...)
    # - get_topics_stats_batch → SRSStatsService.get_grammar_stats_batch()
    # - get_user_stats → SRSStatsService.get_grammar_user_stats()
