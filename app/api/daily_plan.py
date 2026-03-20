"""API endpoints for daily plan and summary."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.api.decorators import api_jwt_required

api_daily_plan = Blueprint('api_daily_plan', __name__)


@api_daily_plan.route('/daily-plan')
@api_jwt_required
def daily_plan():
    """Get user's daily study plan.

    Query params:
        tz (str): User timezone, e.g. 'Europe/Moscow'. Default: 'Europe/Moscow'.

    Returns JSON:
        next_lesson: Next curriculum lesson to study
        grammar_topic: Grammar topic to practice
        words_due: Number of SRS words due today
        has_any_words: Whether user has any words in study
        book_to_read: Book started but not read today
        suggested_books: Book suggestions for new users
        book_course_lesson: Next book course lesson
        book_course_done_today: Whether book course lesson done today
        onboarding: Onboarding suggestions for new users (null if not new)
        bonus: Extra tasks available
    """
    from app.telegram.queries import get_daily_plan

    tz = request.args.get('tz', 'Europe/Moscow')
    user_id = get_jwt_identity()
    plan = get_daily_plan(user_id, tz=tz)

    return jsonify({'success': True, **plan})


@api_daily_plan.route('/daily-summary')
@api_jwt_required
def daily_summary():
    """Get summary of today's learning activity.

    Query params:
        tz (str): User timezone. Default: 'Europe/Moscow'.

    Returns JSON:
        lessons_completed: Number of lessons completed today
        lesson_types: Types of completed lessons
        words_reviewed: Number of words reviewed today
        new_words_learned: Number of new words learned today
        grammar_exercises: Number of grammar exercises done today
        chapters_read: Number of book chapters read today
        streak: Current learning streak in days
        book_course_lessons: Number of book course lessons completed today
    """
    from app.telegram.queries import get_daily_summary

    tz = request.args.get('tz', 'Europe/Moscow')
    user_id = get_jwt_identity()
    summary = get_daily_summary(user_id, tz=tz)

    return jsonify({'success': True, **summary})


@api_daily_plan.route('/streak')
@api_jwt_required
def streak():
    """Get user's current learning streak.

    Query params:
        tz (str): User timezone. Default: 'Europe/Moscow'.

    Returns JSON:
        streak: Current streak in days
        has_activity_today: Whether user was active today
    """
    from app.telegram.queries import get_current_streak, has_activity_today

    tz = request.args.get('tz', 'Europe/Moscow')
    user_id = get_jwt_identity()

    return jsonify({
        'success': True,
        'streak': get_current_streak(user_id, tz=tz),
        'has_activity_today': has_activity_today(user_id, tz=tz),
    })
