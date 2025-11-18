# app/curriculum/services/progress_service.py

import logging
from datetime import UTC, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, func

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db

logger = logging.getLogger(__name__)


class ProgressService:
    """Service for managing user progress through curriculum"""

    @staticmethod
    def get_user_level_progress(user_id: int) -> Dict:
        """
        Get user progress for all CEFR levels
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with progress data by level
        """
        try:
            levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
            user_progress = {}

            for level in levels:
                # Get all modules for the level
                modules = Module.query.filter_by(level_id=level.id).all()
                module_ids = [m.id for m in modules]

                if module_ids:
                    # Count total and completed lessons using optimized query
                    stats = db.session.query(
                        func.count(Lessons.id).label('total'),
                        func.count(
                            func.nullif(LessonProgress.status == 'completed', False)
                        ).label('completed'),
                        func.count(
                            func.nullif(LessonProgress.status == 'in_progress', False)
                        ).label('in_progress')
                    ).select_from(
                        Lessons
                    ).outerjoin(
                        LessonProgress,
                        and_(
                            Lessons.id == LessonProgress.lesson_id,
                            LessonProgress.user_id == user_id
                        )
                    ).filter(
                        Lessons.module_id.in_(module_ids)
                    ).first()

                    total_lessons = stats.total or 0
                    completed_lessons = stats.completed or 0
                    in_progress_lessons = stats.in_progress or 0

                    user_progress[level.id] = {
                        'total_lessons': total_lessons,
                        'completed_lessons': completed_lessons,
                        'in_progress_lessons': in_progress_lessons,
                        'percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0),
                        'level': level
                    }
                else:
                    user_progress[level.id] = {
                        'total_lessons': 0,
                        'completed_lessons': 0,
                        'in_progress_lessons': 0,
                        'percentage': 0,
                        'level': level
                    }

            return user_progress

        except Exception as e:
            logger.error(f"Error getting user level progress: {str(e)}")
            return {}

    @staticmethod
    def get_active_lessons(user_id: int, limit: int = 5) -> List[Dict]:
        """
        Get user's active lessons
        
        Args:
            user_id: User ID
            limit: Maximum number of lessons to return
            
        Returns:
            List of active lessons with progress data
        """
        try:
            active_lessons = db.session.query(
                LessonProgress
            ).filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'in_progress'
            ).order_by(
                LessonProgress.last_activity.desc()
            ).limit(limit).all()

            result = []
            for progress in active_lessons:
                lesson = progress.lesson
                module = lesson.module
                level = module.level

                result.append({
                    'lesson': lesson,
                    'module': module,
                    'level': level,
                    'last_activity': progress.last_activity,
                    'score': progress.score,
                    'progress': progress
                })

            return result

        except Exception as e:
            logger.error(f"Error getting active lessons: {str(e)}")
            return []

    @staticmethod
    def get_recommended_level(user_id: int) -> Optional[CEFRLevel]:
        """
        Get recommended level for user based on progress
        
        Args:
            user_id: User ID
            
        Returns:
            Recommended CEFR level or None
        """
        try:
            levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
            user_progress = ProgressService.get_user_level_progress(user_id)

            for level in levels:
                progress = user_progress.get(level.id, {})
                if progress.get('percentage', 0) < 80:
                    return level

            return levels[-1] if levels else None

        except Exception as e:
            logger.error(f"Error getting recommended level: {str(e)}")
            return None

    @staticmethod
    def create_or_update_progress(
            user_id: int,
            lesson_id: int,
            status: str = 'in_progress',
            score: Optional[float] = None,
            data: Optional[Dict] = None
    ) -> LessonProgress:
        """
        Create or update lesson progress
        
        Args:
            user_id: User ID
            lesson_id: Lesson ID
            status: Progress status
            score: Optional score
            data: Optional additional data
            
        Returns:
            LessonProgress instance
        """
        try:
            progress = LessonProgress.query.filter_by(
                user_id=user_id,
                lesson_id=lesson_id
            ).first()

            if not progress:
                progress = LessonProgress(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    status=status,
                    started_at=datetime.now(UTC),
                    last_activity=datetime.now(UTC)
                )
                db.session.add(progress)
            else:
                progress.status = status
                progress.last_activity = datetime.now(UTC)

            if score is not None:
                progress.score = round(score, 2)

            if data is not None:
                progress.data = data

            if status == 'completed' and not progress.completed_at:
                progress.completed_at = datetime.now(UTC)

            db.session.commit()
            return progress

        except Exception as e:
            logger.error(f"Error creating/updating progress: {str(e)}")
            db.session.rollback()
            raise

    @staticmethod
    def get_module_progress(user_id: int, module_id: int) -> Dict:
        """
        Get user progress for a specific module
        
        Args:
            user_id: User ID
            module_id: Module ID
            
        Returns:
            Dictionary with module progress data
        """
        try:
            # Get module lessons with progress
            lessons_progress = db.session.query(
                Lessons,
                LessonProgress
            ).outerjoin(
                LessonProgress,
                and_(
                    Lessons.id == LessonProgress.lesson_id,
                    LessonProgress.user_id == user_id
                )
            ).filter(
                Lessons.module_id == module_id
            ).order_by(
                Lessons.order,
                Lessons.number
            ).all()

            total_lessons = len(lessons_progress)
            completed_lessons = sum(
                1 for _, progress in lessons_progress
                if progress and progress.status == 'completed'
            )
            in_progress_lessons = sum(
                1 for _, progress in lessons_progress
                if progress and progress.status == 'in_progress'
            )

            # Calculate average score
            scores = [
                progress.score for _, progress in lessons_progress
                if progress and progress.score is not None
            ]
            average_score = sum(scores) / len(scores) if scores else 0

            return {
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'in_progress_lessons': in_progress_lessons,
                'percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0),
                'average_score': round(average_score, 1),
                'lessons': lessons_progress
            }

        except Exception as e:
            logger.error(f"Error getting module progress: {str(e)}")
            return {
                'total_lessons': 0,
                'completed_lessons': 0,
                'in_progress_lessons': 0,
                'percentage': 0,
                'average_score': 0,
                'lessons': []
            }

    @staticmethod
    def can_access_next_module(user_id: int, current_module_id: int) -> bool:
        """
        Check if user can access the next module
        
        Args:
            user_id: User ID
            current_module_id: Current module ID
            
        Returns:
            True if user can access next module
        """
        try:
            current_module = Module.query.get(current_module_id)
            if not current_module:
                return False

            # Get module progress
            progress = ProgressService.get_module_progress(user_id, current_module_id)

            # User must complete at least 80% of lessons to unlock next module
            return progress['percentage'] >= 80

        except Exception as e:
            logger.error(f"Error checking next module access: {str(e)}")
            return False

    @staticmethod
    def get_learning_streak(user_id: int) -> int:
        """
        Calculate user's current learning streak in days
        
        Args:
            user_id: User ID
            
        Returns:
            Number of consecutive days with activity
        """
        try:
            # Get all unique dates with activity
            activity_dates = db.session.query(
                func.date(LessonProgress.last_activity)
            ).filter(
                LessonProgress.user_id == user_id
            ).distinct().order_by(
                func.date(LessonProgress.last_activity).desc()
            ).all()

            if not activity_dates:
                return 0

            # Convert to date objects
            dates = [d[0] for d in activity_dates if d[0]]
            if not dates:
                return 0

            # Check for consecutive days
            streak = 0
            today = datetime.now(UTC).date()

            # Start from today or yesterday
            if dates[0] == today or dates[0] == today - timedelta(days=1):
                streak = 1
                current_date = dates[0]

                for date in dates[1:]:
                    if date == current_date - timedelta(days=1):
                        streak += 1
                        current_date = date
                    else:
                        break

            return streak

        except Exception as e:
            logger.error(f"Error calculating learning streak: {str(e)}")
            return 0

    @staticmethod
    def get_next_lesson(current_lesson_id: int) -> Optional[Lessons]:
        """
        Get the next lesson in sequence
        
        Args:
            current_lesson_id: Current lesson ID
            
        Returns:
            Next lesson or None
        """
        try:
            current_lesson = Lessons.query.get(current_lesson_id)
            if not current_lesson:
                return None

            # Try to get next lesson in the same module
            next_lesson = None
            if current_lesson.order is not None:
                next_lesson = Lessons.query.filter(
                    Lessons.module_id == current_lesson.module_id,
                    Lessons.order > current_lesson.order
                ).order_by(Lessons.order).first()

            if next_lesson:
                return next_lesson

            # If no next lesson in module, try next module
            current_module = current_lesson.module
            next_module = None
            if current_module.number is not None:
                next_module = Module.query.filter(
                    Module.level_id == current_module.level_id,
                    Module.number > current_module.number
                ).order_by(Module.number).first()

            if next_module:
                # Get first lesson of next module
                return Lessons.query.filter_by(
                    module_id=next_module.id
                ).order_by(Lessons.order).first()

            # If no next module, try next level
            current_level = current_module.level
            next_level = None
            if current_level.order is not None:
                next_level = CEFRLevel.query.filter(
                    CEFRLevel.order > current_level.order
                ).order_by(CEFRLevel.order).first()

            if next_level:
                # Get first module of next level
                first_module = Module.query.filter_by(
                    level_id=next_level.id
                ).order_by(Module.number).first()

                if first_module:
                    # Get first lesson of first module
                    return Lessons.query.filter_by(
                        module_id=first_module.id
                    ).order_by(Lessons.order).first()

            return None

        except Exception as e:
            logger.error(f"Error getting next lesson: {str(e)}")
            return None
