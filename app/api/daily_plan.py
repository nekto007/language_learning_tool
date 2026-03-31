"""API endpoints for daily plan and summary."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from zoneinfo import ZoneInfo

from app.api.decorators import api_jwt_required
from app.utils.db import db

api_daily_plan = Blueprint('api_daily_plan', __name__)

DEFAULT_TZ = 'Europe/Moscow'


def _validate_timezone(tz_name: str) -> str:
    """Validate timezone string against system database. Returns default if invalid."""
    try:
        ZoneInfo(tz_name)
        return tz_name
    except (KeyError, ValueError):
        return DEFAULT_TZ


@api_daily_plan.route('/daily-status')
@api_jwt_required
def daily_status():
    """Unified daily status: plan + summary + streak + yesterday — one request."""
    from app.telegram.queries import get_daily_plan, get_daily_summary, get_yesterday_summary
    from app.achievements.streak_service import get_streak_status

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = get_jwt_identity()

    plan = get_daily_plan(user_id, tz=tz)
    summary = get_daily_summary(user_id, tz=tz)
    streak_st = get_streak_status(user_id, tz=tz)
    yesterday = get_yesterday_summary(user_id, tz=tz)

    # Compute plan_completion
    bc_lesson = plan.get('book_course_lesson')
    bc_done = plan.get('book_course_done_today', False)
    bc_is_reading = bc_lesson and bc_lesson.get('lesson_type') == 'reading'
    plan_completion = {
        'lesson': summary['lessons_count'] > 0,
        'grammar': summary['grammar_exercises'] > 0,
        'words': summary.get('srs_words_reviewed', 0) > 0,
        'books': bc_done if bc_is_reading else len(summary.get('books_read', [])) > 0,
        'book_course_practice': bc_done if (bc_lesson and not bc_is_reading) else False,
    }

    # Count steps
    steps_available = {}
    if plan.get('next_lesson'):
        steps_available['lesson'] = True
    if plan.get('grammar_topic'):
        steps_available['grammar'] = True
    if plan.get('words_due') or plan.get('has_any_words'):
        steps_available['words'] = True
    if plan.get('book_to_read') or (bc_lesson and bc_is_reading):
        steps_available['books'] = True
    if bc_lesson and not bc_is_reading:
        steps_available['book_course_practice'] = True

    steps_done = sum(1 for k in steps_available if plan_completion.get(k))
    steps_total = len(steps_available)

    # Save daily completion for progressive streak tracking
    from app.achievements.streak_service import save_daily_completion, get_required_steps
    if steps_total > 0:
        save_daily_completion(user_id, steps_done, steps_total)
        db.session.commit()

    required_steps = get_required_steps(
        streak_st.get('streak', 0), max(steps_total, 1)
    )

    return jsonify({
        'success': True,
        'plan': plan,
        'summary': summary,
        'streak': streak_st,
        'yesterday': yesterday,
        'plan_completion': plan_completion,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'required_steps': required_steps,
    })


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

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
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

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = get_jwt_identity()
    summary = get_daily_summary(user_id, tz=tz)

    return jsonify({'success': True, **summary})


@api_daily_plan.route('/streak')
@api_jwt_required
def streak():
    """Get user's current learning streak with recovery status.

    Query params:
        tz (str): User timezone. Default: 'Europe/Moscow'.

    Returns JSON:
        streak, coins_balance, has_activity_today, can_repair, missed_date, repair_cost
    """
    from app.achievements.streak_service import get_streak_status

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = get_jwt_identity()
    status = get_streak_status(user_id, tz=tz)

    return jsonify({'success': True, **status})


@api_daily_plan.route('/streak/repair', methods=['POST'])
@api_jwt_required
def streak_repair():
    """Pay streak coins to repair a broken streak."""
    from app.achievements.streak_service import find_missed_date, apply_paid_repair
    from app.telegram.queries import get_current_streak

    user_id = get_jwt_identity()
    tz = _validate_timezone(request.json.get('tz', DEFAULT_TZ) if request.is_json else DEFAULT_TZ)

    missed = find_missed_date(user_id, tz=tz)
    if not missed:
        return jsonify({'success': False, 'error': 'no_missed_date'}), 400

    result = apply_paid_repair(user_id, missed)
    if result['success']:
        db.session.commit()
        result['new_streak'] = get_current_streak(user_id, tz=tz)
    else:
        db.session.rollback()

    return jsonify(result)
