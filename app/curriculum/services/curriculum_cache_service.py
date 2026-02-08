# app/curriculum/services/curriculum_cache_service.py

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Dict, Any, Optional, List

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db

logger = logging.getLogger(__name__)


class CurriculumCacheService:
    """Service for caching and optimizing curriculum data queries"""

    CACHE_DURATION = 300  # 5 minutes

    @staticmethod
    def get_levels_with_progress(user_id: int) -> List[Dict[str, Any]]:
        """
        Get all levels with progress data using optimized queries.

        This method reduces N+1 queries by:
        1. Using eager loading for relationships
        2. Bulk fetching lesson progress
        3. Aggregating stats in Python (faster than many small queries)

        Args:
            user_id: User ID to get progress for

        Returns:
            List of level data dictionaries
        """
        try:
            # Step 1: Eager load all levels, modules, and lessons in ONE query
            levels = db.session.query(CEFRLevel).options(
                joinedload(CEFRLevel.modules).joinedload(Module.lessons)
            ).order_by(CEFRLevel.order).all()

            if not levels:
                return []

            # Step 2: Bulk fetch ALL lesson progress for user in ONE query
            all_lesson_ids = []
            for level in levels:
                for module in level.modules:
                    all_lesson_ids.extend([lesson.id for lesson in module.lessons])

            # Get all progress entries at once
            progress_map = {}
            if all_lesson_ids:
                progress_entries = db.session.query(LessonProgress).filter(
                    LessonProgress.user_id == user_id,
                    LessonProgress.lesson_id.in_(all_lesson_ids)
                ).all()

                progress_map = {p.lesson_id: p for p in progress_entries}

            # Step 3: Process data in Python (no more DB queries)
            levels_data = []
            total_stats = {'total_lessons': 0, 'completed_lessons': 0}

            for level in levels:
                modules_data = []
                level_lessons = 0
                level_completed = 0

                # Sort modules by number to ensure correct order
                for module in sorted(level.modules, key=lambda m: m.number):
                    module_total = len(module.lessons)
                    module_completed = sum(
                        1 for lesson in module.lessons
                        if lesson.id in progress_map and progress_map[lesson.id].status == 'completed'
                    )

                    # Prepare lessons data with status
                    lessons_data = []
                    for lesson in sorted(module.lessons, key=lambda x: x.number):
                        progress = progress_map.get(lesson.id)
                        lesson_status = 'locked'  # default

                        if progress:
                            if progress.status == 'completed':
                                lesson_status = 'completed'
                            elif progress.status == 'in_progress':
                                lesson_status = 'in_progress'
                            else:
                                lesson_status = 'available'
                        else:
                            # First lesson or next after completed
                            if not lessons_data:  # First lesson
                                lesson_status = 'available'
                            elif lessons_data and lessons_data[-1]['status'] == 'completed':
                                lesson_status = 'available'

                        lessons_data.append({
                            'lesson': lesson,
                            'status': lesson_status,
                            'progress': progress
                        })

                    # Determine module availability
                    # First module is always available
                    # Subsequent modules require 80% completion of previous module
                    module_progress_percent = round((module_completed / module_total * 100) if module_total > 0 else 0)
                    is_module_available = True

                    if module.number > 1 and modules_data:
                        # Check if previous module is completed at least 80%
                        prev_module_progress = modules_data[-1]['progress_percent']
                        is_module_available = prev_module_progress >= 80

                    modules_data.append({
                        'module': module,
                        'total_lessons': module_total,
                        'completed_lessons': module_completed,
                        'progress_percent': module_progress_percent,
                        'is_available': is_module_available,
                        'lessons': lessons_data
                    })

                    level_lessons += module_total
                    level_completed += module_completed

                # Find next lesson for this level (sorted by module number, then lesson number)
                next_lesson = None
                sorted_modules = sorted(level.modules, key=lambda m: m.number)
                for module in sorted_modules:
                    sorted_lessons = sorted(module.lessons, key=lambda l: l.number)
                    for lesson in sorted_lessons:
                        progress = progress_map.get(lesson.id)
                        if not progress or progress.status != 'completed':
                            next_lesson = lesson
                            break
                    if next_lesson:
                        break

                level_progress = round((level_completed / level_lessons * 100) if level_lessons > 0 else 0)
                remaining_lessons = level_lessons - level_completed
                estimated_time = remaining_lessons * 15

                level_data = {
                    'level': level,
                    'modules': modules_data,
                    'total_lessons': level_lessons,
                    'completed_lessons': level_completed,
                    'progress_percent': level_progress,
                    'estimated_hours': round(estimated_time / 60, 1),
                    'is_available': True,
                    'next_lesson': next_lesson
                }

                levels_data.append(level_data)
                total_stats['total_lessons'] += level_lessons
                total_stats['completed_lessons'] += level_completed

            return levels_data

        except Exception as e:
            logger.error(f"Error getting levels with progress: {str(e)}")
            return []

    @staticmethod
    def get_recent_activity(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get recent lesson activity for user using optimized query.

        Args:
            user_id: User ID
            limit: Number of recent activities to fetch

        Returns:
            List of recent activity dictionaries
        """
        try:
            # Single query with all joins
            recent_progress = db.session.query(LessonProgress).options(
                joinedload(LessonProgress.lesson)
                .joinedload(Lessons.module)
                .joinedload(Module.level)
            ).filter(
                LessonProgress.user_id == user_id
            ).order_by(
                LessonProgress.last_activity.desc()
            ).limit(limit).all()

            recent_activity = []
            for progress in recent_progress:
                recent_activity.append({
                    'lesson': progress.lesson,
                    'module': progress.lesson.module,
                    'level': progress.lesson.module.level,
                    'status': progress.status,
                    'score': progress.score,
                    'last_activity': progress.last_activity
                })

            return recent_activity

        except Exception as e:
            logger.error(f"Error getting recent activity: {str(e)}")
            return []

    @staticmethod
    def get_gamification_stats(user_id: int) -> Dict[str, Any]:
        """
        Calculate gamification statistics efficiently.

        Args:
            user_id: User ID

        Returns:
            Dictionary with gamification stats
        """
        try:
            current_date = datetime.now(UTC).date()

            # Get all activity dates in one query
            activity_dates = db.session.query(
                func.date(LessonProgress.last_activity).label('activity_date')
            ).filter(
                LessonProgress.user_id == user_id
            ).distinct().order_by(
                func.date(LessonProgress.last_activity).desc()
            ).all()

            # Calculate streak
            streak = 0
            if activity_dates:
                activity_dates_list = [d[0] for d in activity_dates]

                if activity_dates_list and (
                    activity_dates_list[0] == current_date or
                    activity_dates_list[0] == current_date - timedelta(days=1)
                ):
                    streak = 1
                    check_date = activity_dates_list[0] - timedelta(days=1)

                    for date in activity_dates_list[1:]:
                        if date == check_date:
                            streak += 1
                            check_date -= timedelta(days=1)
                        else:
                            break

            # Get completion stats in one query
            points_data = db.session.query(
                func.count(LessonProgress.id).label('completed_count'),
                func.coalesce(func.avg(LessonProgress.score), 0).label('avg_score')
            ).filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed'
            ).first()

            completed_lessons = points_data[0] or 0
            avg_score = points_data[1] or 0

            # Calculate points
            total_points = completed_lessons * 10
            if avg_score >= 90:
                total_points += completed_lessons * 5
            elif avg_score >= 80:
                total_points += completed_lessons * 3

            user_level = 1 + (total_points // 100)

            # Get today's progress
            today_completed = db.session.query(func.count(LessonProgress.id)).filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed',
                func.date(LessonProgress.completed_at) == current_date
            ).scalar() or 0

            daily_goal = 3
            daily_progress = min(today_completed, daily_goal)

            return {
                'streak': streak,
                'total_points': total_points,
                'user_level': user_level,
                'daily_progress': daily_progress,
                'daily_goal': daily_goal,
                'completed_lessons': completed_lessons,
                'avg_score': round(avg_score, 1)
            }

        except Exception as e:
            logger.error(f"Error calculating gamification stats: {str(e)}")
            return {
                'streak': 0,
                'total_points': 0,
                'user_level': 1,
                'daily_progress': 0,
                'daily_goal': 3,
                'completed_lessons': 0,
                'avg_score': 0
            }

    @staticmethod
    def get_level_with_modules(level_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get level with modules and optimized progress data.

        Args:
            level_id: Level ID
            user_id: User ID

        Returns:
            Level data dictionary or None
        """
        try:
            # Eager load level with modules and lessons
            level = db.session.query(CEFRLevel).options(
                joinedload(CEFRLevel.modules).joinedload(Module.lessons)
            ).filter(CEFRLevel.id == level_id).first()

            if not level:
                return None

            # Get all lesson IDs for this level
            all_lesson_ids = []
            for module in level.modules:
                all_lesson_ids.extend([lesson.id for lesson in module.lessons])

            # Bulk fetch progress
            progress_map = {}
            if all_lesson_ids:
                progress_entries = db.session.query(LessonProgress).filter(
                    LessonProgress.user_id == user_id,
                    LessonProgress.lesson_id.in_(all_lesson_ids)
                ).all()

                progress_map = {p.lesson_id: p for p in progress_entries}

            return {
                'level': level,
                'progress_map': progress_map
            }

        except Exception as e:
            logger.error(f"Error getting level with modules: {str(e)}")
            return None
