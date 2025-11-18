# app/curriculum/routes/api.py

import logging
from datetime import UTC, datetime, timedelta

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_lesson_access, check_module_access
from app.curriculum.service import get_card_session_for_lesson, get_cards_for_lesson
from app.utils.db import db

logger = logging.getLogger(__name__)

# Create blueprint for API routes
api_bp = Blueprint('curriculum_api', __name__)


@api_bp.route('/api/levels')
@login_required
def api_get_levels():
    """Get all CEFR levels with user progress"""
    try:
        levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

        result = []
        for level in levels:
            # Get modules for level
            modules = Module.query.filter_by(level_id=level.id).all()
            module_ids = [m.id for m in modules]

            # Calculate progress
            total_lessons = 0
            completed_lessons = 0

            if module_ids:
                total_lessons = db.session.query(db.func.count(Lessons.id)).filter(
                    Lessons.module_id.in_(module_ids)
                ).scalar() or 0

                completed_lessons = db.session.query(db.func.count(LessonProgress.id)).join(
                    Lessons, Lessons.id == LessonProgress.lesson_id
                ).filter(
                    Lessons.module_id.in_(module_ids),
                    LessonProgress.user_id == current_user.id,
                    LessonProgress.status == 'completed'
                ).scalar() or 0

            result.append({
                'id': level.id,
                'code': level.code,
                'name': level.name,
                'description': level.description,
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'progress_percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)
            })

        return jsonify({
            'success': True,
            'levels': result
        })

    except Exception as e:
        logger.error(f"Error getting levels: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@api_bp.route('/api/level/<string:level_code>/modules')
@login_required
def api_get_level_modules(level_code):
    """Get modules for a specific level"""
    try:
        level = CEFRLevel.query.filter_by(code=level_code).first()
        if not level:
            return jsonify({'success': False, 'error': 'Level not found'}), 404

        modules = Module.query.filter_by(level_id=level.id).order_by(Module.number).all()

        result = []
        for module in modules:
            # Get lesson count and progress
            total_lessons = Lessons.query.filter_by(module_id=module.id).count()

            completed_lessons = db.session.query(db.func.count(LessonProgress.id)).join(
                Lessons, Lessons.id == LessonProgress.lesson_id
            ).filter(
                Lessons.module_id == module.id,
                LessonProgress.user_id == current_user.id,
                LessonProgress.status == 'completed'
            ).scalar() or 0

            result.append({
                'id': module.id,
                'number': module.number,
                'title': module.title,
                'description': module.description,
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'progress_percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0),
                'is_accessible': check_module_access(module.id)
            })

        return jsonify({
            'success': True,
            'level': {
                'id': level.id,
                'code': level.code,
                'name': level.name
            },
            'modules': result
        })

    except Exception as e:
        logger.error(f"Error getting modules: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@api_bp.route('/api/module/<int:module_id>/lessons')
@login_required
def api_get_module_lessons(module_id):
    """Get lessons for a specific module"""
    try:
        module = Module.query.get(module_id)
        if not module:
            return jsonify({'success': False, 'error': 'Module not found'}), 404

        # Check access
        if not check_module_access(module_id):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        lessons = Lessons.query.filter_by(
            module_id=module_id
        ).order_by(Lessons.order, Lessons.number).all()

        result = []
        for lesson in lessons:
            # Get progress
            progress = LessonProgress.query.filter_by(
                user_id=current_user.id,
                lesson_id=lesson.id
            ).first()

            result.append({
                'id': lesson.id,
                'number': lesson.number,
                'title': lesson.title,
                'type': lesson.type,
                'description': lesson.description,
                'status': progress.status if progress else 'not_started',
                'score': progress.score if progress else None,
                'completed_at': progress.completed_at.isoformat() if progress and progress.completed_at else None,
                'is_accessible': check_lesson_access(lesson.id)
            })

        return jsonify({
            'success': True,
            'module': {
                'id': module.id,
                'number': module.number,
                'title': module.title,
                'level_code': module.level.code
            },
            'lessons': result
        })

    except Exception as e:
        logger.error(f"Error getting lessons: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@api_bp.route('/api/lesson/<int:lesson_id>/info')
@login_required
def api_get_lesson_info(lesson_id):
    """Get detailed lesson information"""
    try:
        lesson = Lessons.query.get(lesson_id)
        if not lesson:
            return jsonify({'success': False, 'error': 'Lesson not found'}), 404

        # Check access
        if not check_lesson_access(lesson_id):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        # Get progress
        progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson_id
        ).first()

        # Get additional info based on lesson type
        additional_info = {}

        if lesson.type == 'card':
            cards_data = get_cards_for_lesson(lesson, current_user.id)
            additional_info['cards'] = {
                'total_due': cards_data['total_due'],
                'new_cards': cards_data['new_cards'],
                'review_cards': cards_data['review_cards']
            }
        elif lesson.type == 'vocabulary' and lesson.collection_id:
            # Get word count
            from app.words.models import Collection, CollectionWordLink
            word_count = CollectionWordLink.query.filter_by(
                collection_id=lesson.collection_id
            ).count()
            additional_info['word_count'] = word_count

        result = {
            'success': True,
            'lesson': {
                'id': lesson.id,
                'number': lesson.number,
                'title': lesson.title,
                'type': lesson.type,
                'description': lesson.description,
                'module': {
                    'id': lesson.module.id,
                    'title': lesson.module.title,
                    'number': lesson.module.number
                },
                'level': {
                    'code': lesson.module.level.code,
                    'name': lesson.module.level.name
                }
            },
            'progress': {
                'status': progress.status if progress else 'not_started',
                'score': progress.score if progress else None,
                'started_at': progress.started_at.isoformat() if progress and progress.started_at else None,
                'completed_at': progress.completed_at.isoformat() if progress and progress.completed_at else None,
                'last_activity': progress.last_activity.isoformat() if progress and progress.last_activity else None
            }
        }

        if additional_info:
            result['additional_info'] = additional_info

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting lesson info: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@api_bp.route('/api/user/progress')
@login_required
def api_get_user_progress():
    """Get overall user progress in curriculum"""
    try:
        # Get total statistics
        total_lessons = Lessons.query.count()

        user_progress = LessonProgress.query.filter_by(
            user_id=current_user.id
        ).all()

        started_lessons = len(user_progress)
        completed_lessons = sum(1 for p in user_progress if p.status == 'completed')
        in_progress_lessons = sum(1 for p in user_progress if p.status == 'in_progress')

        # Calculate average score
        completed_with_score = [p.score for p in user_progress if p.status == 'completed' and p.score is not None]
        average_score = sum(completed_with_score) / len(completed_with_score) if completed_with_score else 0

        # Get recent activity
        recent_activity = sorted(
            [p for p in user_progress if p.last_activity],
            key=lambda x: x.last_activity,
            reverse=True
        )[:5]

        recent_lessons = []
        for progress in recent_activity:
            lesson = progress.lesson
            recent_lessons.append({
                'lesson_id': lesson.id,
                'lesson_title': lesson.title,
                'lesson_type': lesson.type,
                'module_title': lesson.module.title,
                'level_code': lesson.module.level.code,
                'last_activity': progress.last_activity.isoformat(),
                'status': progress.status,
                'score': progress.score
            })

        # Get current streak (days in a row with activity)
        streak = calculate_user_streak(current_user.id)

        return jsonify({
            'success': True,
            'progress': {
                'total_lessons': total_lessons,
                'started_lessons': started_lessons,
                'completed_lessons': completed_lessons,
                'in_progress_lessons': in_progress_lessons,
                'completion_percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0),
                'average_score': round(average_score, 1),
                'current_streak': streak
            },
            'recent_activity': recent_lessons
        })

    except Exception as e:
        logger.error(f"Error getting user progress: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


@api_bp.route('/api/lesson/<int:lesson_id>/card/session')
@login_required
def api_get_card_session(lesson_id):
    """Get card session data for SRS lesson"""
    try:
        lesson = Lessons.query.get(lesson_id)
        if not lesson or lesson.type != 'card':
            return jsonify({'success': False, 'error': 'Invalid lesson'}), 400

        # Check access
        if not check_lesson_access(lesson_id):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        # Get session data
        session_data = get_card_session_for_lesson(lesson, current_user.id)

        return jsonify({
            'success': True,
            'session': session_data
        })

    except Exception as e:
        logger.error(f"Error getting card session: {str(e)}")
        return jsonify({'success': False, 'error': 'Server error'}), 500


def calculate_user_streak(user_id):
    """Calculate user's current learning streak in days"""
    try:
        # Get all unique dates with activity
        activity_dates = db.session.query(
            db.func.date(LessonProgress.last_activity)
        ).filter(
            LessonProgress.user_id == user_id
        ).distinct().order_by(
            db.func.date(LessonProgress.last_activity).desc()
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
        logger.error(f"Error calculating streak: {str(e)}")
        return 0
