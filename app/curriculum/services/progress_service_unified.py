# app/curriculum/services/progress_service_unified.py

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from sqlalchemy import func

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.study.models import UserXP
from app.utils.db import db

logger = logging.getLogger(__name__)


class ProgressService:
    """
    Unified service for managing user progress and XP.

    This service integrates:
    - LessonProgress tracking
    - UserXP system
    - Achievement tracking
    - Gamification stats
    """

    # XP Rewards Configuration
    XP_REWARDS = {
        'vocabulary': 10,
        'grammar': 15,
        'quiz': 20,
        'matching': 10,
        'text': 15,
        'card': 25,  # SRS lessons give more XP
        'final_test': 50  # Final tests give significant XP
    }

    # Score multipliers for XP
    SCORE_MULTIPLIERS = {
        'excellent': 2.0,  # 90-100%
        'good': 1.5,       # 80-89%
        'pass': 1.0,       # 70-79%
        'retry': 0.5       # Below 70%
    }

    @classmethod
    def award_lesson_xp(cls, user_id: int, lesson: Lessons, score: float) -> int:
        """
        Award XP for completing a lesson.

        Args:
            user_id: User ID
            lesson: Lesson object
            score: Score achieved (0-100)

        Returns:
            XP awarded
        """
        try:
            # Get base XP for lesson type
            base_xp = cls.XP_REWARDS.get(lesson.type, 10)

            # Apply score multiplier
            if score >= 90:
                multiplier = cls.SCORE_MULTIPLIERS['excellent']
            elif score >= 80:
                multiplier = cls.SCORE_MULTIPLIERS['good']
            elif score >= 70:
                multiplier = cls.SCORE_MULTIPLIERS['pass']
            else:
                multiplier = cls.SCORE_MULTIPLIERS['retry']

            xp_earned = int(base_xp * multiplier)

            # Get or create UserXP
            user_xp = UserXP.get_or_create(user_id)
            user_xp.total_xp += xp_earned
            user_xp.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            logger.info(f"Awarded {xp_earned} XP to user {user_id} for lesson {lesson.id} (score: {score})")
            return xp_earned

        except Exception as e:
            logger.error(f"Error awarding XP: {str(e)}")
            db.session.rollback()
            return 0

    @classmethod
    def update_lesson_progress(
        cls,
        user_id: int,
        lesson_id: int,
        status: str,
        score: Optional[float] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Optional[LessonProgress]:
        """
        Update lesson progress and award XP if completed.

        Args:
            user_id: User ID
            lesson_id: Lesson ID
            status: Progress status ('not_started', 'in_progress', 'completed')
            score: Score achieved
            data: Additional progress data

        Returns:
            Updated LessonProgress object or None on error
        """
        try:
            # Get or create progress
            progress = LessonProgress.query.filter_by(
                user_id=user_id,
                lesson_id=lesson_id
            ).first()

            if not progress:
                progress = LessonProgress(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    started_at=datetime.utcnow()
                )
                db.session.add(progress)

            # Update fields
            old_status = progress.status
            progress.status = status
            progress.last_activity = datetime.utcnow()

            if score is not None:
                progress.set_score(score)

            if data is not None:
                progress.data = data

            # Award XP if newly completed
            if status == 'completed' and old_status != 'completed':
                progress.completed_at = datetime.utcnow()

                # Award XP
                lesson = Lessons.query.get(lesson_id)
                if lesson and progress.score is not None:
                    xp_earned = cls.award_lesson_xp(user_id, lesson, progress.score)

                    # Store XP in progress data
                    if not progress.data:
                        progress.data = {}
                    progress.data['xp_earned'] = xp_earned

            db.session.commit()
            return progress

        except Exception as e:
            logger.error(f"Error updating lesson progress: {str(e)}")
            db.session.rollback()
            return None

    @classmethod
    def get_user_stats(cls, user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive user statistics.

        Args:
            user_id: User ID

        Returns:
            Dictionary with user stats
        """
        try:
            # Get UserXP
            user_xp = UserXP.get_or_create(user_id)

            # Get lesson stats
            lesson_stats = db.session.query(
                func.count(LessonProgress.id).label('total_lessons'),
                func.count(
                    func.case((LessonProgress.status == 'completed', 1))
                ).label('completed_lessons'),
                func.coalesce(func.avg(LessonProgress.score), 0).label('avg_score')
            ).filter(
                LessonProgress.user_id == user_id
            ).first()

            # Calculate completion rate
            total = lesson_stats.total_lessons or 0
            completed = lesson_stats.completed_lessons or 0
            completion_rate = round((completed / total * 100) if total > 0 else 0, 1)

            # Get current streak
            streak = cls._calculate_streak(user_id)

            return {
                'xp': {
                    'total': user_xp.total_xp,
                    'level': user_xp.level,
                    'xp_for_next_level': user_xp.level * 100,
                    'xp_in_current_level': user_xp.total_xp % 100
                },
                'lessons': {
                    'total_started': total,
                    'completed': completed,
                    'completion_rate': completion_rate,
                    'avg_score': round(lesson_stats.avg_score or 0, 1)
                },
                'streak': {
                    'current': streak,
                    'record': cls._get_record_streak(user_id)
                }
            }

        except Exception as e:
            logger.error(f"Error getting user stats: {str(e)}")
            return {
                'xp': {'total': 0, 'level': 1, 'xp_for_next_level': 100, 'xp_in_current_level': 0},
                'lessons': {'total_started': 0, 'completed': 0, 'completion_rate': 0, 'avg_score': 0},
                'streak': {'current': 0, 'record': 0}
            }

    @classmethod
    def get_level_progress(cls, user_id: int, level_id: int) -> Dict[str, Any]:
        """
        Get progress for a specific CEFR level.

        Args:
            user_id: User ID
            level_id: Level ID

        Returns:
            Dictionary with level progress
        """
        try:
            # Get level
            level = CEFRLevel.query.get(level_id)
            if not level:
                return {}

            # Get all lessons for this level
            lesson_ids = db.session.query(Lessons.id).join(Module).filter(
                Module.level_id == level_id
            ).all()
            lesson_ids = [lid[0] for lid in lesson_ids]

            if not lesson_ids:
                return {
                    'level': level,
                    'total_lessons': 0,
                    'completed_lessons': 0,
                    'progress_percent': 0
                }

            # Get progress stats
            progress_stats = db.session.query(
                func.count(LessonProgress.id).label('completed')
            ).filter(
                LessonProgress.user_id == user_id,
                LessonProgress.lesson_id.in_(lesson_ids),
                LessonProgress.status == 'completed'
            ).first()

            completed = progress_stats.completed or 0
            total = len(lesson_ids)
            progress_percent = round((completed / total * 100) if total > 0 else 0)

            return {
                'level': level,
                'total_lessons': total,
                'completed_lessons': completed,
                'progress_percent': progress_percent
            }

        except Exception as e:
            logger.error(f"Error getting level progress: {str(e)}")
            return {}

    @classmethod
    def get_module_progress(cls, user_id: int, module_id: int) -> Dict[str, Any]:
        """
        Get progress for a specific module.

        Args:
            user_id: User ID
            module_id: Module ID

        Returns:
            Dictionary with module progress
        """
        try:
            # Get module
            module = Module.query.get(module_id)
            if not module:
                return {}

            # Get all lessons for this module
            lessons = Lessons.query.filter_by(module_id=module_id).all()
            lesson_ids = [lesson.id for lesson in lessons]

            if not lesson_ids:
                return {
                    'module': module,
                    'total_lessons': 0,
                    'completed_lessons': 0,
                    'progress_percent': 0
                }

            # Get progress stats
            progress_stats = db.session.query(
                func.count(LessonProgress.id).label('completed')
            ).filter(
                LessonProgress.user_id == user_id,
                LessonProgress.lesson_id.in_(lesson_ids),
                LessonProgress.status == 'completed'
            ).first()

            completed = progress_stats.completed or 0
            total = len(lessons)
            progress_percent = round((completed / total * 100) if total > 0 else 0)

            return {
                'module': module,
                'total_lessons': total,
                'completed_lessons': completed,
                'progress_percent': progress_percent
            }

        except Exception as e:
            logger.error(f"Error getting module progress: {str(e)}")
            return {}

    @classmethod
    def _calculate_streak(cls, user_id: int) -> int:
        """Calculate current learning streak in days."""
        try:
            current_date = datetime.utcnow().date()

            # Get distinct activity dates
            activity_dates = db.session.query(
                func.date(LessonProgress.last_activity).label('activity_date')
            ).filter(
                LessonProgress.user_id == user_id
            ).distinct().order_by(
                func.date(LessonProgress.last_activity).desc()
            ).all()

            if not activity_dates:
                return 0

            dates_list = [d[0] for d in activity_dates]

            # Check if active today or yesterday
            if dates_list[0] not in [current_date, current_date - timedelta(days=1)]:
                return 0

            streak = 1
            check_date = dates_list[0] - timedelta(days=1)

            for date in dates_list[1:]:
                if date == check_date:
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break

            return streak

        except Exception as e:
            logger.error(f"Error calculating streak: {str(e)}")
            return 0

    @classmethod
    def _get_record_streak(cls, user_id: int) -> int:
        """Get user's record streak (stored in UserXP or calculated)."""
        # TODO: Add record_streak field to UserXP model
        # For now, just return current streak
        return cls._calculate_streak(user_id)
