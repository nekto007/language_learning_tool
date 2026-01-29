# app/grammar_lab/services/grammar_lab_service.py
"""
Main service for Grammar Lab module.

Handles topic retrieval, exercise sessions, and progress tracking.
Uses UnifiedSRSService for Anki-like spaced repetition.

All SRS logic is at exercise level (UserGrammarExercise).
Topic status (theory, XP) is in UserGrammarTopicStatus.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import uuid
import logging

from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.grammar_lab.models import (
    GrammarTopic, GrammarExercise,
    GrammarAttempt, UserGrammarExercise, UserGrammarTopicStatus
)
from app.grammar_lab.services.grammar_srs import GrammarSRS
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.srs.constants import CardState, RATING_DONT_KNOW, RATING_KNOW

logger = logging.getLogger(__name__)


def _get_unified_srs_service():
    """Lazy import to avoid circular dependency."""
    from app.srs.service import unified_srs_service
    return unified_srs_service


# XP rewards
GRAMMAR_XP = {
    'theory_completed': 20,
    'exercise_correct': 10,
    'exercise_mastered': 50,
}


class GrammarLabService:
    """Main service for Grammar Lab"""

    def __init__(self):
        self.srs = GrammarSRS()
        self.grader = GrammarExerciseGrader()

    def get_topics_by_level(self, level: str = None, user_id: int = None) -> List[Dict]:
        """
        Get all topics, optionally filtered by level, with user progress.
        """
        query = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order)

        if level:
            query = query.filter(GrammarTopic.level == level)

        topics = query.all()

        result = []
        for topic in topics:
            data = topic.to_dict()

            if user_id:
                # Get topic status
                status = UserGrammarTopicStatus.query.filter_by(
                    user_id=user_id, topic_id=topic.id
                ).first()

                # Get SRS stats from exercises
                srs_stats = self.srs.get_topic_stats(user_id, topic.id)

                data['status'] = status.to_dict() if status else None
                data['srs_stats'] = srs_stats
            else:
                data['status'] = None
                data['srs_stats'] = None

            result.append(data)

        return result

    def get_levels_summary(self, user_id: int = None) -> List[Dict]:
        """Get summary of all levels with topic counts and progress."""
        levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
        result = []

        for level in levels:
            topic_count = GrammarTopic.query.filter_by(level=level).count()

            level_data = {
                'level': level,
                'topic_count': topic_count,
                'exercises_total': 0,
                'exercises_mastered': 0,
                'progress_pct': 0
            }

            if user_id and topic_count > 0:
                # Get exercise counts for this level
                level_topics = GrammarTopic.query.filter_by(level=level).all()
                level_topic_ids = [t.id for t in level_topics]

                exercises = GrammarExercise.query.filter(
                    GrammarExercise.topic_id.in_(level_topic_ids)
                ).all()
                exercise_ids = [e.id for e in exercises]

                if exercise_ids:
                    # Count mastered exercises
                    mastered = UserGrammarExercise.query.filter(
                        UserGrammarExercise.user_id == user_id,
                        UserGrammarExercise.exercise_id.in_(exercise_ids),
                        UserGrammarExercise.state == CardState.REVIEW.value,
                        UserGrammarExercise.interval >= 180
                    ).count()

                    level_data['exercises_total'] = len(exercise_ids)
                    level_data['exercises_mastered'] = mastered
                    level_data['progress_pct'] = round((mastered / len(exercise_ids)) * 100, 1)

            result.append(level_data)

        return result

    def get_topic_detail(self, topic_id: int, user_id: int = None) -> Optional[Dict]:
        """Get full topic details including content and exercises."""
        topic = GrammarTopic.query.get(topic_id)
        if not topic:
            return None

        data = topic.to_dict(include_content=True)

        # Get exercises
        exercises = GrammarExercise.query.filter_by(topic_id=topic_id).order_by(
            GrammarExercise.order,
            GrammarExercise.difficulty
        ).all()
        data['exercises'] = [e.to_dict(hide_answer=True) for e in exercises]

        if user_id:
            # Get topic status
            status = UserGrammarTopicStatus.query.filter_by(
                user_id=user_id, topic_id=topic_id
            ).first()
            data['status'] = status.to_dict() if status else None

            # Get SRS stats
            data['srs_stats'] = self.srs.get_topic_stats(user_id, topic_id)
        else:
            data['status'] = None
            data['srs_stats'] = None

        return data

    def start_topic_practice(self, topic_id: int, user_id: int, max_exercises: int = 12) -> Dict:
        """
        Start practice session with Anki-like state-based exercise selection.

        Priority: RELEARNING > LEARNING > REVIEW > NEW
        """
        import random

        topic = GrammarTopic.query.get(topic_id)
        if not topic:
            return {'error': 'Topic not found'}

        # Ensure topic status exists
        status = self.srs.get_or_create_topic_status(user_id, topic_id)

        # Generate session ID
        session_id = f"grammar_{topic_id}_{user_id}_{uuid.uuid4().hex[:8]}"

        # Get all exercises
        all_exercises = GrammarExercise.query.filter_by(topic_id=topic_id).all()

        if not all_exercises:
            return {
                'error': 'No exercises for this topic',
                'session_id': session_id,
                'topic': topic.to_dict()
            }

        # Ensure exercise-level progress records exist
        exercise_ids = [e.id for e in all_exercises]
        _get_unified_srs_service().get_or_create_grammar_exercise_progress(user_id, exercise_ids)

        # Reset session attempts
        _get_unified_srs_service().reset_grammar_session_attempts(user_id, topic_id=topic_id)

        now = datetime.now(timezone.utc)

        # Categorize by state
        relearning, learning, review, new = [], [], [], []

        for ex in all_exercises:
            progress = UserGrammarExercise.query.filter_by(
                user_id=user_id, exercise_id=ex.id
            ).first()

            if not progress or progress.state == CardState.NEW.value:
                new.append(ex)
            elif progress.state == CardState.RELEARNING.value:
                if progress.next_review <= now:
                    relearning.append(ex)
            elif progress.state == CardState.LEARNING.value:
                if progress.next_review <= now:
                    learning.append(ex)
            elif progress.state == CardState.REVIEW.value:
                if progress.next_review <= now:
                    review.append(ex)

        # Build priority queue
        selected = []
        remaining = max_exercises

        for pool in [relearning, learning, review, new]:
            if remaining <= 0:
                break
            random.shuffle(pool)
            selected.extend(pool[:remaining])
            remaining = max_exercises - len(selected)

        # Fill if needed
        if len(selected) < min(max_exercises, len(all_exercises)):
            remaining_pool = [e for e in all_exercises if e not in selected]
            random.shuffle(remaining_pool)
            selected.extend(remaining_pool[:max_exercises - len(selected)])

        # Prepare exercise data
        exercises_data = []
        for ex in selected:
            ex_data = ex.to_dict(hide_answer=True)
            progress = UserGrammarExercise.query.filter_by(
                user_id=user_id, exercise_id=ex.id
            ).first()

            ex_data['srs_state'] = progress.state if progress else 'new'
            ex_data['srs_interval'] = progress.interval if progress else 0
            ex_data['srs_lapses'] = progress.lapses if progress else 0
            exercises_data.append(ex_data)

        return {
            'session_id': session_id,
            'topic': topic.to_dict(),
            'total_exercises': len(selected),
            'all_exercises_count': len(all_exercises),
            'exercises': exercises_data,
            'status': status.to_dict(),
            'srs_stats': self.srs.get_topic_stats(user_id, topic_id)
        }

    def submit_answer(self, exercise_id: int, user_id: int, answer: Any,
                      session_id: str = None, source: str = 'topic_practice',
                      time_spent: int = None) -> Dict:
        """Submit and grade an exercise answer."""
        exercise = GrammarExercise.query.get(exercise_id)
        if not exercise:
            return {'error': 'Exercise not found'}

        # Grade the answer
        result = self.grader.grade(exercise, answer)

        # Record attempt
        attempt = GrammarAttempt(
            user_id=user_id,
            exercise_id=exercise_id,
            is_correct=result['is_correct'],
            user_answer=str(answer),
            time_spent=time_spent,
            session_id=session_id,
            source=source
        )
        db.session.add(attempt)

        # Update SRS
        rating = RATING_KNOW if result['is_correct'] else RATING_DONT_KNOW
        srs_result = _get_unified_srs_service().grade_grammar_exercise(
            exercise_id=exercise_id,
            rating=rating,
            user_id=user_id,
            session_key=session_id
        )

        # Award XP
        xp_earned = 0
        if result['is_correct']:
            xp_earned += GRAMMAR_XP['exercise_correct']

            # Mastery bonus
            if srs_result.get('success') and srs_result.get('state') == CardState.REVIEW.value:
                if srs_result.get('interval', 0) >= 180:
                    xp_earned += GRAMMAR_XP['exercise_mastered']

        if xp_earned > 0:
            self.srs.add_xp(user_id, exercise.topic_id, xp_earned)

        db.session.commit()

        return {
            **result,
            'xp_earned': xp_earned,
            'srs_update': srs_result,
            'requeue_position': srs_result.get('requeue_position'),
            'requeue_minutes': srs_result.get('requeue_minutes'),
            'exercise_state': srs_result.get('state'),
            'exercise_interval': srs_result.get('interval')
        }

    def complete_theory(self, topic_id: int, user_id: int) -> Dict:
        """Mark theory as completed and award XP."""
        status = self.srs.get_or_create_topic_status(user_id, topic_id)

        xp_earned = 0
        if not status.theory_completed:
            status.theory_completed = True
            status.theory_completed_at = datetime.now(timezone.utc)
            xp_earned = GRAMMAR_XP['theory_completed']
            status.add_xp(xp_earned)
            db.session.commit()

        return {
            'status': status.to_dict(),
            'xp_earned': xp_earned
        }

    def get_user_stats(self, user_id: int) -> Dict:
        """Get comprehensive stats for a user."""
        return self.srs.get_user_stats(user_id)

    def get_recommendations(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Get recommended topics based on exercise states."""
        recommendations = []
        now = datetime.now(timezone.utc)

        # 1. Topics with due exercises (RELEARNING or REVIEW due)
        due_topics = (
            db.session.query(GrammarTopic)
            .join(GrammarExercise)
            .join(UserGrammarExercise)
            .filter(
                UserGrammarExercise.user_id == user_id,
                UserGrammarExercise.next_review <= now,
                UserGrammarExercise.state.in_([CardState.RELEARNING.value, CardState.REVIEW.value])
            )
            .distinct()
            .limit(3)
            .all()
        )

        for topic in due_topics:
            recommendations.append({
                **topic.to_dict(),
                'reason': 'due_for_review',
                'reason_text': 'Пора повторить'
            })

        # 2. Topics in progress (LEARNING state)
        if len(recommendations) < limit:
            in_progress = (
                db.session.query(GrammarTopic)
                .join(GrammarExercise)
                .join(UserGrammarExercise)
                .filter(
                    UserGrammarExercise.user_id == user_id,
                    UserGrammarExercise.state == CardState.LEARNING.value
                )
                .distinct()
                .limit(limit - len(recommendations))
                .all()
            )

            for topic in in_progress:
                if topic.id not in [r['id'] for r in recommendations]:
                    recommendations.append({
                        **topic.to_dict(),
                        'reason': 'in_progress',
                        'reason_text': 'Продолжить изучение'
                    })

        # 3. New topics (no progress yet)
        if len(recommendations) < limit:
            started_topic_ids = (
                db.session.query(GrammarExercise.topic_id)
                .join(UserGrammarExercise)
                .filter(UserGrammarExercise.user_id == user_id)
                .distinct()
                .subquery()
            )

            new_topics = (
                GrammarTopic.query
                .filter(~GrammarTopic.id.in_(started_topic_ids))
                .order_by(GrammarTopic.level, GrammarTopic.order)
                .limit(limit - len(recommendations))
                .all()
            )

            for topic in new_topics:
                recommendations.append({
                    **topic.to_dict(),
                    'reason': 'new',
                    'reason_text': 'Новая тема'
                })

        return recommendations[:limit]
