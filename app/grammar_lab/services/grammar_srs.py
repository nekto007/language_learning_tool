# app/grammar_lab/services/grammar_srs.py
"""
SRS (Spaced Repetition System) for grammar topics.

Adapted SM-2 algorithm for grammar practice.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import logging

from app.utils.db import db
from app.grammar_lab.models import GrammarTopic, UserGrammarProgress

logger = logging.getLogger(__name__)


class GrammarSRS:
    """SRS for grammar topics (adapted SM-2 algorithm)"""

    MASTERY_LEVELS = {
        0: 'new',        # New topic
        1: 'learning',   # Initial learning
        2: 'reviewing',  # Under review
        3: 'familiar',   # Familiar
        4: 'confident',  # Confident
        5: 'mastered'    # Mastered
    }

    # Streak required to advance to next level
    STREAK_FOR_LEVEL = {
        0: 2,  # 2 correct to go from new to learning
        1: 3,  # 3 correct to go from learning to reviewing
        2: 4,  # 4 correct to go from reviewing to familiar
        3: 5,  # 5 correct to go from familiar to confident
        4: 6,  # 6 correct to go from confident to mastered
    }

    # Base intervals in days for each mastery level
    BASE_INTERVALS = {
        0: 1,
        1: 1,
        2: 3,
        3: 7,
        4: 14,
        5: 30
    }

    def process_answer(self, progress: UserGrammarProgress, is_correct: bool) -> Dict:
        """
        Update progress after an answer.

        Args:
            progress: UserGrammarProgress instance
            is_correct: Whether the answer was correct

        Returns:
            Dict with new_level, next_review, streak
        """
        progress.total_attempts += 1

        if is_correct:
            progress.correct_attempts += 1
            progress.correct_streak += 1

            # Level up if streak is sufficient
            streak_needed = self.STREAK_FOR_LEVEL.get(progress.mastery_level, 6)
            if progress.correct_streak >= streak_needed and progress.mastery_level < 5:
                progress.mastery_level += 1
                progress.correct_streak = 0
                logger.info(f"User leveled up to {progress.mastery_level} on topic {progress.topic_id}")

            # Increase ease factor
            progress.ease_factor = min(2.5, progress.ease_factor + 0.1)
            progress.interval = self._calculate_interval(progress)

        else:
            progress.correct_streak = 0

            # Level down on mistake
            if progress.mastery_level > 0:
                progress.mastery_level -= 1

            # Decrease ease factor
            progress.ease_factor = max(1.3, progress.ease_factor - 0.2)
            progress.interval = 1  # Review tomorrow

        progress.last_reviewed = datetime.now(timezone.utc)
        progress.next_review = datetime.now(timezone.utc) + timedelta(days=progress.interval)

        db.session.commit()

        return {
            'new_level': progress.mastery_level,
            'mastery_label': self.MASTERY_LEVELS.get(progress.mastery_level, 'unknown'),
            'next_review': progress.next_review,
            'streak': progress.correct_streak,
            'interval': progress.interval
        }

    def _calculate_interval(self, progress: UserGrammarProgress) -> int:
        """Calculate review interval based on mastery level and ease factor"""
        base = self.BASE_INTERVALS.get(progress.mastery_level, 1)
        interval = int(base * progress.ease_factor)
        return max(1, interval)

    def get_due_topics(self, user_id: int, limit: int = 10) -> List[GrammarTopic]:
        """
        Get topics due for review.

        Args:
            user_id: User ID
            limit: Max number of topics to return

        Returns:
            List of GrammarTopic instances
        """
        now = datetime.now(timezone.utc)

        return (
            db.session.query(GrammarTopic)
            .join(UserGrammarProgress)
            .filter(
                UserGrammarProgress.user_id == user_id,
                UserGrammarProgress.next_review <= now,
                UserGrammarProgress.mastery_level < 5  # Not fully mastered
            )
            .order_by(
                UserGrammarProgress.mastery_level.asc(),  # Weakest first
                UserGrammarProgress.next_review.asc()
            )
            .limit(limit)
            .all()
        )

    def get_new_topics(self, user_id: int, level: str = None, limit: int = 5) -> List[GrammarTopic]:
        """
        Get topics the user hasn't started yet.

        Args:
            user_id: User ID
            level: Optional CEFR level filter
            limit: Max number of topics

        Returns:
            List of GrammarTopic instances
        """
        # Subquery to get topic IDs user has already started
        started_topics = (
            db.session.query(UserGrammarProgress.topic_id)
            .filter(UserGrammarProgress.user_id == user_id)
            .subquery()
        )

        query = (
            GrammarTopic.query
            .filter(~GrammarTopic.id.in_(started_topics))
        )

        if level:
            query = query.filter(GrammarTopic.level == level)

        return query.order_by(GrammarTopic.level, GrammarTopic.order).limit(limit).all()

    def get_or_create_progress(self, user_id: int, topic_id: int) -> UserGrammarProgress:
        """
        Get or create progress record for a user and topic.

        Args:
            user_id: User ID
            topic_id: Topic ID

        Returns:
            UserGrammarProgress instance
        """
        progress = UserGrammarProgress.query.filter_by(
            user_id=user_id,
            topic_id=topic_id
        ).first()

        if not progress:
            progress = UserGrammarProgress(
                user_id=user_id,
                topic_id=topic_id
            )
            db.session.add(progress)
            db.session.commit()

        return progress

    def complete_theory(self, user_id: int, topic_id: int) -> UserGrammarProgress:
        """
        Mark theory as completed for a topic.

        Args:
            user_id: User ID
            topic_id: Topic ID

        Returns:
            UserGrammarProgress instance
        """
        progress = self.get_or_create_progress(user_id, topic_id)

        if not progress.theory_completed:
            progress.theory_completed = True
            progress.theory_completed_at = datetime.now(timezone.utc)
            db.session.commit()

        return progress

    def get_user_stats(self, user_id: int) -> Dict:
        """
        Get overall grammar stats for a user.

        Args:
            user_id: User ID

        Returns:
            Dict with stats
        """
        all_progress = UserGrammarProgress.query.filter_by(user_id=user_id).all()

        if not all_progress:
            return {
                'total_topics': 0,
                'topics_started': 0,
                'topics_mastered': 0,
                'total_xp': 0,
                'total_attempts': 0,
                'overall_accuracy': 0,
                'by_level': {}
            }

        total_topics = GrammarTopic.query.count()
        topics_started = len(all_progress)
        topics_mastered = sum(1 for p in all_progress if p.mastery_level >= 5)
        total_xp = sum(p.xp_earned for p in all_progress)
        total_attempts = sum(p.total_attempts for p in all_progress)
        total_correct = sum(p.correct_attempts for p in all_progress)

        # Stats by level
        by_level = {}
        for level in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']:
            level_total = GrammarTopic.query.filter_by(level=level).count()
            level_progress = [p for p in all_progress if p.topic and p.topic.level == level]
            level_mastered = sum(1 for p in level_progress if p.mastery_level >= 5)

            by_level[level] = {
                'total': level_total,
                'started': len(level_progress),
                'mastered': level_mastered,
                'progress_pct': round((level_mastered / level_total * 100) if level_total else 0, 1)
            }

        return {
            'total_topics': total_topics,
            'topics_started': topics_started,
            'topics_mastered': topics_mastered,
            'total_xp': total_xp,
            'total_attempts': total_attempts,
            'overall_accuracy': round((total_correct / total_attempts * 100) if total_attempts else 0, 1),
            'by_level': by_level
        }
