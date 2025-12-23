# app/grammar_lab/services/grammar_lab_service.py
"""
Main service for Grammar Lab module.

Handles topic retrieval, exercise sessions, and progress tracking.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import uuid
import logging

from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarProgress, GrammarAttempt
from app.grammar_lab.services.grammar_srs import GrammarSRS
from app.grammar_lab.services.grader import GrammarExerciseGrader

logger = logging.getLogger(__name__)


# XP rewards
GRAMMAR_XP = {
    'theory_completed': 20,
    'exercise_correct': 10,
    'exercise_streak_3': 15,
    'exercise_streak_5': 25,
    'topic_mastered': 100,
    'level_completed': 500,
    'daily_practice': 30,
}


class GrammarLabService:
    """Main service for Grammar Lab"""

    def __init__(self):
        self.srs = GrammarSRS()
        self.grader = GrammarExerciseGrader()

    def get_topics_by_level(self, level: str = None, user_id: int = None) -> List[Dict]:
        """
        Get all topics, optionally filtered by level, with user progress.

        Args:
            level: Optional CEFR level filter (A1, A2, B1, B2, C1, C2)
            user_id: Optional user ID to include progress

        Returns:
            List of topic dicts with progress info
        """
        query = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order)

        if level:
            query = query.filter(GrammarTopic.level == level)

        topics = query.all()

        # Get user progress if user_id provided
        progress_map = {}
        if user_id:
            progress_records = UserGrammarProgress.query.filter_by(user_id=user_id).all()
            progress_map = {p.topic_id: p for p in progress_records}

        result = []
        for topic in topics:
            data = topic.to_dict()
            progress = progress_map.get(topic.id)
            if progress:
                data['progress'] = progress.to_dict()
            else:
                data['progress'] = None
            result.append(data)

        return result

    def get_levels_summary(self, user_id: int = None) -> List[Dict]:
        """
        Get summary of all levels with topic counts and progress.

        Args:
            user_id: Optional user ID for progress

        Returns:
            List of level summary dicts
        """
        levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
        result = []

        for level in levels:
            topic_count = GrammarTopic.query.filter_by(level=level).count()

            level_data = {
                'level': level,
                'topic_count': topic_count,
                'topics_started': 0,
                'topics_mastered': 0,
                'progress_pct': 0
            }

            if user_id and topic_count > 0:
                # Get progress for this level
                progress_count = (
                    db.session.query(UserGrammarProgress)
                    .join(GrammarTopic)
                    .filter(
                        UserGrammarProgress.user_id == user_id,
                        GrammarTopic.level == level
                    )
                    .count()
                )

                mastered_count = (
                    db.session.query(UserGrammarProgress)
                    .join(GrammarTopic)
                    .filter(
                        UserGrammarProgress.user_id == user_id,
                        GrammarTopic.level == level,
                        UserGrammarProgress.mastery_level >= 5
                    )
                    .count()
                )

                level_data['topics_started'] = progress_count
                level_data['topics_mastered'] = mastered_count
                level_data['progress_pct'] = round((mastered_count / topic_count) * 100, 1)

            result.append(level_data)

        return result

    def get_topic_detail(self, topic_id: int, user_id: int = None) -> Optional[Dict]:
        """
        Get full topic details including content and exercises.

        Args:
            topic_id: Topic ID
            user_id: Optional user ID for progress

        Returns:
            Topic dict with content and exercises
        """
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

        # Get user progress
        if user_id:
            progress = UserGrammarProgress.query.filter_by(
                user_id=user_id,
                topic_id=topic_id
            ).first()
            data['progress'] = progress.to_dict() if progress else None
        else:
            data['progress'] = None

        return data

    def start_topic_practice(self, topic_id: int, user_id: int, max_exercises: int = 12) -> Dict:
        """
        Start practice session for a topic with smart exercise selection.

        Args:
            topic_id: Topic ID
            user_id: User ID
            max_exercises: Maximum exercises per session (default 12)

        Returns:
            Dict with session_id and selected exercises
        """
        import random
        from sqlalchemy import func

        topic = GrammarTopic.query.get(topic_id)
        if not topic:
            return {'error': 'Topic not found'}

        # Get or create progress
        progress = self.srs.get_or_create_progress(user_id, topic_id)

        # Generate session ID
        session_id = f"grammar_{topic_id}_{user_id}_{uuid.uuid4().hex[:8]}"

        # Get all exercises for this topic
        all_exercises = GrammarExercise.query.filter_by(topic_id=topic_id).all()

        if not all_exercises:
            return {
                'error': 'No exercises for this topic',
                'session_id': session_id,
                'topic': topic.to_dict()
            }

        # Get user's attempt stats for each exercise
        exercise_ids = [e.id for e in all_exercises]
        attempt_stats = db.session.query(
            GrammarAttempt.exercise_id,
            func.count(GrammarAttempt.id).label('total'),
            func.sum(func.cast(GrammarAttempt.is_correct, db.Integer)).label('correct')
        ).filter(
            GrammarAttempt.user_id == user_id,
            GrammarAttempt.exercise_id.in_(exercise_ids)
        ).group_by(GrammarAttempt.exercise_id).all()

        # Build stats dict
        stats = {s.exercise_id: {'total': s.total, 'correct': s.correct or 0} for s in attempt_stats}

        # Categorize exercises
        never_attempted = []
        weak_exercises = []  # < 70% correct
        strong_exercises = []  # >= 70% correct

        for ex in all_exercises:
            if ex.id not in stats:
                never_attempted.append(ex)
            else:
                s = stats[ex.id]
                accuracy = s['correct'] / s['total'] if s['total'] > 0 else 0
                if accuracy < 0.7:
                    weak_exercises.append(ex)
                else:
                    strong_exercises.append(ex)

        # Shuffle each category
        random.shuffle(never_attempted)
        random.shuffle(weak_exercises)
        random.shuffle(strong_exercises)

        # Select exercises based on mastery level
        selected = []
        mastery = progress.mastery_level

        if mastery < 2:
            # Early learning: prioritize new exercises
            # 8 new + 4 weak (or fill with new)
            selected.extend(never_attempted[:8])
            selected.extend(weak_exercises[:4])
            remaining = max_exercises - len(selected)
            if remaining > 0:
                selected.extend(never_attempted[8:8+remaining])
        elif mastery < 4:
            # Mid learning: mix of weak and new
            # 4 weak + 6 new + 2 strong for review
            selected.extend(weak_exercises[:4])
            selected.extend(never_attempted[:6])
            selected.extend(strong_exercises[:2])
            remaining = max_exercises - len(selected)
            if remaining > 0:
                # Fill with whatever is available
                pool = [e for e in never_attempted[6:] + weak_exercises[4:] if e not in selected]
                selected.extend(pool[:remaining])
        else:
            # Advanced: review weak + reinforce strong
            # 5 weak + 3 new + 4 strong
            selected.extend(weak_exercises[:5])
            selected.extend(never_attempted[:3])
            selected.extend(strong_exercises[:4])
            remaining = max_exercises - len(selected)
            if remaining > 0:
                pool = [e for e in all_exercises if e not in selected]
                random.shuffle(pool)
                selected.extend(pool[:remaining])

        # Ensure we don't exceed max and have at least some exercises
        selected = selected[:max_exercises]

        # If we still have too few, fill from any available
        if len(selected) < min(max_exercises, len(all_exercises)):
            remaining_pool = [e for e in all_exercises if e not in selected]
            random.shuffle(remaining_pool)
            selected.extend(remaining_pool[:max_exercises - len(selected)])

        # Shuffle final selection for variety
        random.shuffle(selected)

        return {
            'session_id': session_id,
            'topic': topic.to_dict(),
            'total_exercises': len(selected),
            'all_exercises_count': len(all_exercises),
            'exercises': [e.to_dict(hide_answer=True) for e in selected],
            'progress': progress.to_dict()
        }

    def submit_answer(self, exercise_id: int, user_id: int, answer: Any,
                      session_id: str = None, source: str = 'topic_practice',
                      time_spent: int = None) -> Dict:
        """
        Submit and grade an exercise answer.

        Args:
            exercise_id: Exercise ID
            user_id: User ID
            answer: User's answer
            session_id: Optional session ID
            source: Source of attempt (topic_practice, srs_review, daily_lesson)
            time_spent: Time spent on exercise in seconds

        Returns:
            Dict with grading result and updated progress
        """
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

        # Update progress
        progress = self.srs.get_or_create_progress(user_id, exercise.topic_id)
        srs_result = self.srs.process_answer(progress, result['is_correct'])

        # Award XP
        xp_earned = 0
        if result['is_correct']:
            xp_earned += GRAMMAR_XP['exercise_correct']

            # Streak bonuses
            if progress.correct_streak == 3:
                xp_earned += GRAMMAR_XP['exercise_streak_3']
            elif progress.correct_streak == 5:
                xp_earned += GRAMMAR_XP['exercise_streak_5']

            # Mastery bonus
            if srs_result['new_level'] == 5 and progress.mastery_level == 4:
                xp_earned += GRAMMAR_XP['topic_mastered']

            progress.xp_earned += xp_earned

        # Update error stats
        exercise_type = exercise.exercise_type
        error_stats = progress.error_stats or {}
        if exercise_type not in error_stats:
            error_stats[exercise_type] = {'attempts': 0, 'correct': 0}
        error_stats[exercise_type]['attempts'] += 1
        if result['is_correct']:
            error_stats[exercise_type]['correct'] += 1
        progress.error_stats = error_stats

        if time_spent:
            progress.time_spent += time_spent

        db.session.commit()

        return {
            **result,
            'xp_earned': xp_earned,
            'progress': progress.to_dict(),
            'srs_update': srs_result
        }

    def get_practice_session(self, user_id: int, topic_ids: List[int] = None,
                             count: int = 10, include_new: bool = True) -> Dict:
        """
        Create SRS practice session with exercises from multiple topics.

        Args:
            user_id: User ID
            topic_ids: Optional list of specific topic IDs
            count: Number of exercises to include
            include_new: Whether to include exercises from new topics

        Returns:
            Dict with session_id and exercises
        """
        session_id = f"practice_{user_id}_{uuid.uuid4().hex[:8]}"
        exercises = []

        # Get due topics
        due_topics = self.srs.get_due_topics(user_id, limit=5)

        if topic_ids:
            # Filter to requested topics
            due_topics = [t for t in due_topics if t.id in topic_ids]

        # Get exercises from due topics
        for topic in due_topics:
            topic_exercises = GrammarExercise.query.filter_by(topic_id=topic.id).order_by(
                GrammarExercise.order
            ).limit(3).all()
            exercises.extend(topic_exercises)

        # If not enough, get from new topics
        if len(exercises) < count and include_new:
            new_topics = self.srs.get_new_topics(user_id, limit=3)
            for topic in new_topics:
                if len(exercises) >= count:
                    break
                topic_exercises = GrammarExercise.query.filter_by(topic_id=topic.id).order_by(
                    GrammarExercise.order
                ).limit(2).all()
                exercises.extend(topic_exercises)

        # Limit to count
        exercises = exercises[:count]

        return {
            'session_id': session_id,
            'total_exercises': len(exercises),
            'exercises': [e.to_dict(hide_answer=True) for e in exercises],
            'due_topics': [t.to_dict() for t in due_topics]
        }

    def complete_theory(self, topic_id: int, user_id: int) -> Dict:
        """
        Mark theory as completed and award XP.

        Args:
            topic_id: Topic ID
            user_id: User ID

        Returns:
            Dict with progress and XP earned
        """
        progress = self.srs.complete_theory(user_id, topic_id)

        # Award XP only if this is the first completion
        xp_earned = 0
        if progress.theory_completed_at and progress.xp_earned < GRAMMAR_XP['theory_completed']:
            xp_earned = GRAMMAR_XP['theory_completed']
            progress.xp_earned += xp_earned
            db.session.commit()

        return {
            'progress': progress.to_dict(),
            'xp_earned': xp_earned
        }

    def get_user_stats(self, user_id: int) -> Dict:
        """
        Get comprehensive stats for a user.

        Args:
            user_id: User ID

        Returns:
            Dict with stats
        """
        return self.srs.get_user_stats(user_id)

    def get_recommendations(self, user_id: int, limit: int = 5) -> List[Dict]:
        """
        Get recommended topics for the user based on their progress.

        Args:
            user_id: User ID
            limit: Max recommendations

        Returns:
            List of topic dicts with recommendation reason
        """
        recommendations = []

        # 1. Due for review (highest priority)
        due_topics = self.srs.get_due_topics(user_id, limit=3)
        for topic in due_topics:
            recommendations.append({
                **topic.to_dict(),
                'reason': 'due_for_review',
                'reason_text': 'Пора повторить'
            })

        # 2. Topics in progress (not mastered yet)
        if len(recommendations) < limit:
            in_progress = (
                db.session.query(GrammarTopic)
                .join(UserGrammarProgress)
                .filter(
                    UserGrammarProgress.user_id == user_id,
                    UserGrammarProgress.mastery_level.between(1, 4)
                )
                .order_by(UserGrammarProgress.last_reviewed.desc())
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

        # 3. New topics to start
        if len(recommendations) < limit:
            new_topics = self.srs.get_new_topics(user_id, limit=limit - len(recommendations))
            for topic in new_topics:
                recommendations.append({
                    **topic.to_dict(),
                    'reason': 'new',
                    'reason_text': 'Новая тема'
                })

        return recommendations[:limit]
