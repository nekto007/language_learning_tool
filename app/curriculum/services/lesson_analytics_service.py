# app/curriculum/services/lesson_analytics_service.py

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy import func, and_, desc

from app.curriculum.models import LessonAttempt, Lessons, Module, CEFRLevel, LessonProgress
from app.utils.db import db

logger = logging.getLogger(__name__)


class LessonAnalyticsService:
    """Service for analyzing lesson attempts and generating insights"""

    @classmethod
    def get_lesson_stats(cls, lesson_id: int) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a lesson.

        Args:
            lesson_id: Lesson ID

        Returns:
            Dictionary with lesson statistics
        """
        try:
            # Get lesson info
            lesson = Lessons.query.get(lesson_id)
            if not lesson:
                return {}

            # Get attempt statistics
            stats = db.session.query(
                func.count(LessonAttempt.id).label('total_attempts'),
                func.count(func.distinct(LessonAttempt.user_id)).label('unique_users'),
                func.avg(LessonAttempt.score).label('avg_score'),
                func.avg(LessonAttempt.time_spent_seconds).label('avg_time'),
                func.count(func.case((LessonAttempt.passed == True, 1))).label('passed_count')
            ).filter(
                LessonAttempt.lesson_id == lesson_id,
                LessonAttempt.completed_at.isnot(None)
            ).first()

            total_attempts = stats.total_attempts or 0
            pass_rate = (stats.passed_count / total_attempts * 100) if total_attempts > 0 else 0

            # Get retry statistics
            retry_stats = db.session.query(
                LessonAttempt.user_id,
                func.count(LessonAttempt.id).label('attempts')
            ).filter(
                LessonAttempt.lesson_id == lesson_id
            ).group_by(
                LessonAttempt.user_id
            ).having(
                func.count(LessonAttempt.id) > 1
            ).all()

            retry_rate = (len(retry_stats) / stats.unique_users * 100) if stats.unique_users > 0 else 0
            avg_attempts_per_user = (total_attempts / stats.unique_users) if stats.unique_users > 0 else 0

            # Get common mistakes
            common_mistakes = cls._analyze_common_mistakes(lesson_id, limit=5)

            return {
                'lesson': lesson,
                'total_attempts': total_attempts,
                'unique_users': stats.unique_users or 0,
                'avg_score': round(stats.avg_score or 0, 1),
                'avg_time_minutes': round((stats.avg_time or 0) / 60, 1),
                'pass_rate': round(pass_rate, 1),
                'retry_rate': round(retry_rate, 1),
                'avg_attempts_per_user': round(avg_attempts_per_user, 1),
                'common_mistakes': common_mistakes
            }

        except Exception as e:
            logger.error(f"Error getting lesson stats: {str(e)}")
            return {}

    @classmethod
    def _analyze_common_mistakes(cls, lesson_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Analyze common mistakes across all attempts."""
        try:
            # Get all mistakes from recent attempts
            attempts = LessonAttempt.query.filter(
                LessonAttempt.lesson_id == lesson_id,
                LessonAttempt.mistakes.isnot(None)
            ).order_by(desc(LessonAttempt.completed_at)).limit(100).all()

            # Count mistake frequency
            mistake_counts = {}
            for attempt in attempts:
                if attempt.mistakes:
                    for mistake in attempt.mistakes:
                        question_id = mistake.get('question_id') or mistake.get('question')
                        if question_id:
                            key = str(question_id)
                            if key not in mistake_counts:
                                mistake_counts[key] = {
                                    'question_id': question_id,
                                    'count': 0,
                                    'question_text': mistake.get('question_text', 'Unknown')
                                }
                            mistake_counts[key]['count'] += 1

            # Sort by frequency
            sorted_mistakes = sorted(
                mistake_counts.values(),
                key=lambda x: x['count'],
                reverse=True
            )[:limit]

            return sorted_mistakes

        except Exception as e:
            logger.error(f"Error analyzing common mistakes: {str(e)}")
            return []

    @classmethod
    def get_module_stats(cls, module_id: int) -> Dict[str, Any]:
        """Get statistics for entire module."""
        try:
            module = Module.query.get(module_id)
            if not module:
                return {}

            lessons = Lessons.query.filter_by(module_id=module_id).all()
            lesson_ids = [l.id for l in lessons]

            # Aggregate statistics across all lessons
            stats = db.session.query(
                func.count(LessonAttempt.id).label('total_attempts'),
                func.count(func.distinct(LessonAttempt.user_id)).label('unique_users'),
                func.avg(LessonAttempt.score).label('avg_score'),
                func.avg(LessonAttempt.time_spent_seconds).label('avg_time')
            ).filter(
                LessonAttempt.lesson_id.in_(lesson_ids),
                LessonAttempt.completed_at.isnot(None)
            ).first()

            # Get completion rate
            total_users = stats.unique_users or 0
            completed_users = db.session.query(
                func.count(func.distinct(LessonProgress.user_id))
            ).join(Lessons).filter(
                Lessons.module_id == module_id,
                LessonProgress.status == 'completed'
            ).group_by(LessonProgress.user_id).having(
                func.count(func.distinct(LessonProgress.lesson_id)) == len(lessons)
            ).scalar() or 0

            completion_rate = (completed_users / total_users * 100) if total_users > 0 else 0

            # Get drop-off points (lessons with high abandonment)
            drop_off = cls._find_drop_off_points(module_id)

            return {
                'module': module,
                'total_lessons': len(lessons),
                'total_attempts': stats.total_attempts or 0,
                'unique_users': total_users,
                'avg_score': round(stats.avg_score or 0, 1),
                'avg_time_minutes': round((stats.avg_time or 0) / 60, 1),
                'completion_rate': round(completion_rate, 1),
                'drop_off_points': drop_off
            }

        except Exception as e:
            logger.error(f"Error getting module stats: {str(e)}")
            return {}

    @classmethod
    def _find_drop_off_points(cls, module_id: int) -> List[Dict[str, Any]]:
        """Find lessons where users commonly abandon the module."""
        try:
            lessons = Lessons.query.filter_by(module_id=module_id).order_by(Lessons.order).all()
            drop_off = []

            for lesson in lessons:
                # Count users who started but didn't complete
                started = db.session.query(func.count(func.distinct(LessonProgress.user_id))).filter(
                    LessonProgress.lesson_id == lesson.id
                ).scalar() or 0

                completed = db.session.query(func.count(func.distinct(LessonProgress.user_id))).filter(
                    LessonProgress.lesson_id == lesson.id,
                    LessonProgress.status == 'completed'
                ).scalar() or 0

                abandonment_rate = ((started - completed) / started * 100) if started > 0 else 0

                if abandonment_rate > 30:  # Flag if >30% abandonment
                    drop_off.append({
                        'lesson': lesson,
                        'abandonment_rate': round(abandonment_rate, 1),
                        'started': started,
                        'completed': completed
                    })

            return sorted(drop_off, key=lambda x: x['abandonment_rate'], reverse=True)[:3]

        except Exception as e:
            logger.error(f"Error finding drop-off points: {str(e)}")
            return []

    @classmethod
    def get_user_performance(cls, user_id: int) -> Dict[str, Any]:
        """Get comprehensive performance metrics for a user."""
        try:
            # Get all attempts
            all_attempts = LessonAttempt.query.filter(
                LessonAttempt.user_id == user_id,
                LessonAttempt.completed_at.isnot(None)
            ).all()

            if not all_attempts:
                return {
                    'total_attempts': 0,
                    'avg_score': 0,
                    'pass_rate': 0,
                    'avg_time': 0,
                    'strengths': [],
                    'weaknesses': []
                }

            # Calculate overall stats
            total = len(all_attempts)
            passed = sum(1 for a in all_attempts if a.passed)
            avg_score = sum(a.score for a in all_attempts if a.score) / total
            avg_time = sum(a.time_spent_seconds for a in all_attempts if a.time_spent_seconds) / total

            # Analyze by lesson type
            by_type = {}
            for attempt in all_attempts:
                lesson_type = attempt.lesson.type
                if lesson_type not in by_type:
                    by_type[lesson_type] = {'scores': [], 'times': []}

                if attempt.score:
                    by_type[lesson_type]['scores'].append(attempt.score)
                if attempt.time_spent_seconds:
                    by_type[lesson_type]['times'].append(attempt.time_spent_seconds)

            # Calculate averages by type
            type_stats = {}
            for lesson_type, data in by_type.items():
                type_stats[lesson_type] = {
                    'avg_score': round(sum(data['scores']) / len(data['scores']), 1) if data['scores'] else 0,
                    'avg_time': round(sum(data['times']) / len(data['times']) / 60, 1) if data['times'] else 0
                }

            # Identify strengths and weaknesses
            strengths = sorted(
                [(t, s['avg_score']) for t, s in type_stats.items()],
                key=lambda x: x[1],
                reverse=True
            )[:2]

            weaknesses = sorted(
                [(t, s['avg_score']) for t, s in type_stats.items() if s['avg_score'] < 80],
                key=lambda x: x[1]
            )[:2]

            return {
                'total_attempts': total,
                'avg_score': round(avg_score, 1),
                'pass_rate': round((passed / total * 100), 1),
                'avg_time_minutes': round(avg_time / 60, 1),
                'strengths': [{'type': t, 'score': s} for t, s in strengths],
                'weaknesses': [{'type': t, 'score': s} for t, s in weaknesses],
                'by_type': type_stats
            }

        except Exception as e:
            logger.error(f"Error getting user performance: {str(e)}")
            return {}

    @classmethod
    def get_system_health(cls) -> Dict[str, Any]:
        """Get overall system health metrics."""
        try:
            # Get counts for last 7 days
            week_ago = datetime.utcnow() - timedelta(days=7)

            recent_attempts = db.session.query(
                func.count(LessonAttempt.id).label('total'),
                func.count(func.distinct(LessonAttempt.user_id)).label('active_users'),
                func.avg(LessonAttempt.score).label('avg_score'),
                func.count(func.case((LessonAttempt.passed == True, 1))).label('passed')
            ).filter(
                LessonAttempt.started_at >= week_ago
            ).first()

            total = recent_attempts.total or 0
            pass_rate = (recent_attempts.passed / total * 100) if total > 0 else 0

            # Find problematic lessons (low pass rate)
            problematic = db.session.query(
                LessonAttempt.lesson_id,
                func.count(LessonAttempt.id).label('attempts'),
                func.avg(LessonAttempt.score).label('avg_score'),
                func.count(func.case((LessonAttempt.passed == True, 1))).label('passed')
            ).filter(
                LessonAttempt.started_at >= week_ago,
                LessonAttempt.completed_at.isnot(None)
            ).group_by(
                LessonAttempt.lesson_id
            ).having(
                func.count(LessonAttempt.id) >= 5  # At least 5 attempts
            ).all()

            problem_lessons = []
            for row in problematic:
                pass_rate_lesson = (row.passed / row.attempts * 100) if row.attempts > 0 else 0
                if pass_rate_lesson < 50:  # Less than 50% pass rate
                    lesson = Lessons.query.get(row.lesson_id)
                    problem_lessons.append({
                        'lesson': lesson,
                        'attempts': row.attempts,
                        'avg_score': round(row.avg_score, 1),
                        'pass_rate': round(pass_rate_lesson, 1)
                    })

            return {
                'last_7_days': {
                    'total_attempts': total,
                    'active_users': recent_attempts.active_users or 0,
                    'avg_score': round(recent_attempts.avg_score or 0, 1),
                    'pass_rate': round(pass_rate, 1)
                },
                'problem_lessons': sorted(problem_lessons, key=lambda x: x['pass_rate'])[:5],
                'alert_count': len(problem_lessons)
            }

        except Exception as e:
            logger.error(f"Error getting system health: {str(e)}")
            return {}

    @classmethod
    def generate_alerts(cls) -> List[Dict[str, Any]]:
        """Generate automatic alerts for administrators."""
        alerts = []

        try:
            health = cls.get_system_health()

            # Alert: Low overall pass rate
            if health['last_7_days']['pass_rate'] < 60:
                alerts.append({
                    'severity': 'high',
                    'type': 'low_pass_rate',
                    'message': f"Overall pass rate dropped to {health['last_7_days']['pass_rate']}%",
                    'action': 'Review lesson difficulty and user feedback'
                })

            # Alert: Problem lessons
            if health['alert_count'] > 3:
                alerts.append({
                    'severity': 'medium',
                    'type': 'multiple_problem_lessons',
                    'message': f"{health['alert_count']} lessons have <50% pass rate",
                    'action': 'Review and improve problematic lessons',
                    'details': health['problem_lessons'][:3]
                })

            # Alert: Low activity
            if health['last_7_days']['active_users'] < 5:
                alerts.append({
                    'severity': 'low',
                    'type': 'low_activity',
                    'message': f"Only {health['last_7_days']['active_users']} active users in last 7 days",
                    'action': 'Consider marketing or re-engagement campaigns'
                })

        except Exception as e:
            logger.error(f"Error generating alerts: {str(e)}")

        return alerts
