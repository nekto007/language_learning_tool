"""API endpoints for daily plan and summary."""

from flask import Blueprint, jsonify, request
from flask_login import current_user
from zoneinfo import ZoneInfo

from app import csrf
from app.api.decorators import api_auth_required
from app.api.errors import api_error
from app.utils.db import db

from config.settings import DEFAULT_TIMEZONE

api_daily_plan = Blueprint('api_daily_plan', __name__)

DEFAULT_TZ = DEFAULT_TIMEZONE


def _validate_timezone(tz_name: str) -> str:
    """Validate timezone string against system database. Returns default if invalid."""
    try:
        ZoneInfo(tz_name)
        return tz_name
    except (KeyError, ValueError):
        return DEFAULT_TZ


@api_daily_plan.route('/daily-status')
@api_auth_required
def daily_status():
    """Unified daily status: plan + summary + streak + yesterday — one request."""
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary, get_yesterday_summary
    from app.achievements.streak_service import compute_plan_steps, process_streak_on_activity

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))

    user_id = current_user.id

    plan = get_daily_plan_unified(user_id, tz=tz)
    summary = get_daily_summary(user_id, tz=tz)
    yesterday = get_yesterday_summary(user_id, tz=tz)

    plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(plan, summary)
    streak_result = process_streak_on_activity(
        user_id, steps_done, steps_total, tz=tz,
        daily_plan=plan, plan_completion=plan_completion,
    )

    day_secured = plan.get('day_secured', False)

    if day_secured:
        from datetime import datetime
        import pytz
        try:
            tz_obj = pytz.timezone(tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone(DEFAULT_TZ)
        today = datetime.now(tz_obj).date()
        mission = plan.get('mission') or {}
        mission_type = mission.get('type') if isinstance(mission, dict) else None
        try:
            emit_minimum_completed(user_id, mission_type, today)
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({
        'success': True,
        'plan': plan,
        'summary': summary,
        'streak': streak_result['streak_status'],
        'yesterday': yesterday,
        'plan_completion': plan_completion,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'required_steps': streak_result['required_steps'],
        'streak_repaired': streak_result['streak_repaired'],
        'day_secured': day_secured,
    })


def _compute_steps_today(phases: list) -> int:
    """Sum weighted steps for all completed phases in the plan payload."""
    from app.daily_plan.route_progress import get_phase_step_weight
    return sum(
        get_phase_step_weight(p.get('phase', ''))
        for p in phases
        if p.get('completed', False)
    )


@api_daily_plan.route('/daily-plan')
@api_auth_required
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
        route_state: Current route progress state
    """
    from app.daily_plan.service import get_daily_plan_unified
    from app.daily_plan.route_progress import get_route_state

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = current_user.id
    plan = get_daily_plan_unified(user_id, tz=tz)

    phases = plan.get('phases') or []
    steps_today = _compute_steps_today(phases)
    route_state = get_route_state(user_id, steps_today, db.session)

    return jsonify({'success': True, 'route_state': route_state, **plan})


@api_daily_plan.route('/daily-summary')
@api_auth_required
def daily_summary():
    """Get summary of today's learning activity.

    Query params:
        tz (str): User timezone. Default: 'Europe/Moscow'.

    Returns JSON:
        lessons_count: Number of lessons completed today
        lesson_types: Types of completed lessons
        words_reviewed: Number of words reviewed today
        srs_words_reviewed: Total SRS words reviewed
        srs_new_reviewed: New SRS words reviewed
        srs_review_reviewed: Review SRS words reviewed
        grammar_exercises: Number of grammar exercises done today
        grammar_correct: Number of correct grammar exercises
        books_read: List of book titles read today
        book_course_lessons_today: Number of book course lessons completed today
        lesson_score: Latest lesson score
        lesson_title: Latest lesson title
        grammar_topic_title: Latest grammar topic title
        book_chapter_title: Latest book chapter title
    """
    from app.telegram.queries import get_daily_summary

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))

    user_id = current_user.id
    summary = get_daily_summary(user_id, tz=tz)

    return jsonify({'success': True, **summary})


@api_daily_plan.route('/streak')
@api_auth_required
def streak():
    """Get user's current learning streak with recovery status.

    Query params:
        tz (str): User timezone. Default: 'Europe/Moscow'.

    Returns JSON:
        streak, coins_balance, has_activity_today, can_repair, missed_date, repair_cost
    """
    from app.achievements.streak_service import get_streak_status

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = current_user.id
    status = get_streak_status(user_id, tz=tz)

    return jsonify({'success': True, **status})


@api_daily_plan.route('/daily-race')
@api_auth_required
def daily_race_status():
    """Return current daily race standings for the authenticated user.

    Query params:
        tz (str): User timezone, e.g. 'Europe/Moscow'. Default: project default.

    Enrolls the caller into a race cohort on first visit of the local day,
    recomputes points from their current plan snapshot, and returns the
    sorted leaderboard with ghost fillers included.
    """
    from datetime import datetime
    import pytz
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary
    from app.achievements.streak_service import compute_plan_steps
    from app.achievements.daily_race import (
        get_race_standings,
        update_race_points_from_plan,
    )

    tz = _validate_timezone(request.args.get('tz', DEFAULT_TZ))
    user_id = current_user.id

    try:
        tz_obj = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TZ)
    local_today = datetime.now(tz_obj).date()

    plan = get_daily_plan_unified(user_id, tz=tz)
    summary = get_daily_summary(user_id, tz=tz)
    plan_completion, _, _, _ = compute_plan_steps(plan, summary)

    phases = plan.get('phases') or []
    if phases:
        try:
            update_race_points_from_plan(
                user_id, local_today, phases, plan_completion,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    standings = get_race_standings(user_id, local_today, tz=tz)
    db.session.commit()

    return jsonify({'success': True, 'race': standings})


@api_daily_plan.route('/daily-plan/continuation')
@api_auth_required
def daily_plan_continuation():
    """Return the single highest-priority continuation task after day is secured.

    This endpoint is distinct from /api/daily-plan/next-step (which returns the
    next incomplete phase from the current daily plan). This endpoint focuses on
    post-minimum continuation recommendations using priority-based heuristics.

    Returns JSON:
        step: {kind, reason, data, estimated_minutes} or null when exhausted
    """
    from app.daily_plan.next_step import get_next_best_step

    user_id = current_user.id
    step = get_next_best_step(user_id, db)

    if step is None:
        return jsonify({'success': True, 'step': None})

    return jsonify({
        'success': True,
        'step': {
            'kind': step.kind,
            'reason': step.reason,
            'data': step.data,
            'estimated_minutes': step.estimated_minutes,
        },
    })


@api_daily_plan.route('/daily-plan/phase-complete', methods=['POST'])
@csrf.exempt
@api_auth_required
def daily_plan_phase_complete():
    """Record a completed mission phase and update route progress.

    Body JSON:
        phase_kind (str): one of learn, recall, use, read, check, close, bonus

    Returns JSON:
        route_state: updated route state dict
        checkpoint_reached: bool — True if this completion crossed a checkpoint
    """
    from app.daily_plan.route_progress import add_route_steps, get_route_state, PHASE_STEP_WEIGHTS

    if not request.is_json:
        return api_error('invalid_content_type', 'Request must be JSON', 400)

    body = request.get_json(silent=True) or {}
    phase_kind = body.get('phase_kind', '')

    if phase_kind not in PHASE_STEP_WEIGHTS:
        return api_error(
            'invalid_phase_kind',
            f'phase_kind must be one of: {", ".join(sorted(PHASE_STEP_WEIGHTS))}',
            400,
        )

    user_id = current_user.id
    try:
        row, checkpoint_reached = add_route_steps(user_id, phase_kind, db.session)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_error('db_error', 'Failed to update route progress', 500)

    steps_today = body.get('steps_today', 0)
    route_state = get_route_state(user_id, steps_today, db.session)
    return jsonify({
        'success': True,
        'route_state': route_state,
        'checkpoint_reached': checkpoint_reached,
    })


_CLIENT_EVENTS = {
    'next_step_shown',
    'next_step_accepted',
    'next_step_dismissed',
    'session_ended_at_minimum',
}


@api_daily_plan.route('/daily-plan/events', methods=['POST'])
@csrf.exempt
@api_auth_required
def record_daily_plan_event():
    """Record a Phase 1 behavioral event for H1 hypothesis measurement.

    Accepted event_types: next_step_shown, next_step_accepted,
    next_step_dismissed, session_ended_at_minimum.

    Body JSON:
        event_type (str): one of the accepted event types
        step_kind (str, optional): kind of the next step shown/accepted/dismissed
        reason_text (str, optional): human-readable reason string for next_step_shown
        plan_date (str, optional): ISO date string; defaults to today in user tz
    """
    from datetime import date as date_cls
    from app.daily_plan.models import DailyPlanEvent, DailyPlanEventType

    if not request.is_json:
        return api_error('invalid_content_type', 'Request must be JSON', 400)

    body = request.get_json(silent=True) or {}
    event_type = body.get('event_type', '')

    if event_type not in _CLIENT_EVENTS:
        return api_error(
            'invalid_event_type',
            f'event_type must be one of: {", ".join(sorted(_CLIENT_EVENTS))}',
            400,
        )

    plan_date_str = body.get('plan_date')
    if plan_date_str:
        try:
            plan_date = date_cls.fromisoformat(plan_date_str)
        except ValueError:
            plan_date = None
    else:
        plan_date = None

    step_kind = body.get('step_kind')
    reason_text = body.get('reason_text')
    if reason_text:
        reason_text = str(reason_text)[:500]

    event = DailyPlanEvent(
        user_id=current_user.id,
        event_type=event_type,
        plan_date=plan_date,
        step_kind=step_kind,
        reason_text=reason_text,
    )
    db.session.add(event)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_error('db_error', 'Failed to record event', 500)

    return jsonify({'success': True, 'event_type': event_type})


def emit_minimum_completed(user_id: int, mission_type: str | None, plan_date) -> None:
    """Server-side helper: emit minimum_completed event when day becomes secured.

    Called internally when the plan payload indicates day_secured=True.
    Idempotent per (user_id, plan_date): inserts only if no prior event exists.
    """
    from app.daily_plan.models import DailyPlanEvent

    existing = DailyPlanEvent.query.filter_by(
        user_id=user_id,
        event_type='minimum_completed',
        plan_date=plan_date,
    ).first()
    if existing:
        return

    event = DailyPlanEvent(
        user_id=user_id,
        event_type='minimum_completed',
        plan_date=plan_date,
        mission_type=mission_type,
    )
    db.session.add(event)


@api_daily_plan.route('/streak/repair', methods=['POST'])
@csrf.exempt
@api_auth_required
def streak_repair():
    """Pay streak coins to repair a broken streak."""
    from app.achievements.streak_service import find_missed_date, apply_paid_repair
    from app.telegram.queries import get_current_streak

    user_id = current_user.id
    tz = _validate_timezone(request.json.get('tz', DEFAULT_TZ) if request.is_json else DEFAULT_TZ)

    missed = find_missed_date(user_id, tz=tz)
    if not missed:
        return api_error('no_missed_date', 'No missed date found', 400)

    result = apply_paid_repair(user_id, missed)
    if result['success']:
        db.session.commit()
        result['new_streak'] = get_current_streak(user_id, tz=tz)
    else:
        db.session.rollback()

    return jsonify(result)
