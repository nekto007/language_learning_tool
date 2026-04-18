"""API endpoints for daily plan and summary."""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user
from zoneinfo import ZoneInfo

from app import csrf
from app.api.decorators import api_auth_required
from app.api.errors import api_error
from app.utils.db import db

from config.settings import DEFAULT_TIMEZONE

api_daily_plan = Blueprint('api_daily_plan', __name__)
logger = logging.getLogger(__name__)

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

    tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))

    user_id = current_user.id

    plan = get_daily_plan_unified(user_id, tz=tz)
    summary = get_daily_summary(user_id, tz=tz)
    yesterday = get_yesterday_summary(user_id, tz=tz)

    plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(plan, summary)
    streak_result = process_streak_on_activity(
        user_id, steps_done, steps_total, tz=tz,
        daily_plan=plan, plan_completion=plan_completion,
    )

    # Recompute day_secured from actual activity (plan payload always has completed=False
    # because the assembler constructs phases before activity is recorded).
    phases = plan.get('phases', [])
    if phases and plan.get('_plan_meta', {}).get('effective_mode') == 'mission':
        required_phases = [p for p in phases if p.get('required', True)]
        day_secured = bool(required_phases) and all(
            plan_completion.get(p.get('id', ''), False) for p in required_phases
        )
    else:
        day_secured = plan.get('day_secured', False)
    plan['day_secured'] = day_secured

    # Sync route progress for completed phases so steps are recorded even if
    # the user never reloads /api/daily-plan after finishing their mission.
    if plan.get('mission'):
        try:
            from datetime import datetime as _dt_rp
            import pytz as _pytz_rp
            from app.daily_plan.route_progress import add_route_steps_idempotent, PHASE_STEP_WEIGHTS
            _user_tz_name = current_user.timezone or DEFAULT_TZ
            try:
                _tz_obj = _pytz_rp.timezone(_user_tz_name)
            except Exception:
                _tz_obj = _pytz_rp.timezone(DEFAULT_TZ)
            _route_today = _dt_rp.now(_tz_obj).date()
            for _p in phases:
                if plan_completion.get(_p.get('id', ''), False):
                    _pk = _p.get('phase', '')
                    if PHASE_STEP_WEIGHTS.get(_pk, 0) > 0:
                        add_route_steps_idempotent(user_id, _pk, _route_today, db.session)
            db.session.commit()
        except Exception:
            logger.warning("route_step sync failed in daily_status", exc_info=True)
            db.session.rollback()

    if day_secured:
        from datetime import datetime
        import pytz
        from app.daily_plan.service import write_secured_at
        try:
            tz_obj = pytz.timezone(tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone(DEFAULT_TZ)
        today = datetime.now(tz_obj).date()
        mission = plan.get('mission') or {}
        mission_type = mission.get('type') if isinstance(mission, dict) else None
        try:
            emit_minimum_completed(user_id, mission_type, today)
            write_secured_at(user_id, today, mission_type)
            db.session.commit()
        except Exception:
            logger.warning("secured_at write failed in daily_status", exc_info=True)
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
    from app.daily_plan.route_progress import (
        get_route_state, get_phase_step_weight,
        add_route_steps_idempotent, PHASE_STEP_WEIGHTS,
    )
    from app.telegram.queries import get_daily_summary
    from app.achievements.streak_service import compute_plan_steps

    tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))
    user_id = current_user.id
    plan = get_daily_plan_unified(user_id, tz=tz)
    summary = get_daily_summary(user_id, tz=tz)

    plan_completion, _, _, _ = compute_plan_steps(plan, summary)

    phases = plan.get('phases') or []
    steps_today = sum(
        get_phase_step_weight(p.get('phase', ''))
        for p in phases
        if plan_completion.get(p.get('id', ''), False)
    )

    # Sync route progress before reading state so total_steps stays consistent
    # with steps_today when the user hasn't visited the dashboard yet today.
    if plan.get('mission'):
        try:
            from datetime import datetime
            import pytz as _pytz_rp
            _user_tz_name = current_user.timezone or DEFAULT_TZ
            try:
                _tz_obj = _pytz_rp.timezone(_user_tz_name)
            except Exception:
                _tz_obj = _pytz_rp.timezone(DEFAULT_TZ)
            _route_today = datetime.now(_tz_obj).date()
            for _p in phases:
                if plan_completion.get(_p.get('id', ''), False):
                    _pk = _p.get('phase', '')
                    if PHASE_STEP_WEIGHTS.get(_pk, 0) > 0:
                        add_route_steps_idempotent(user_id, _pk, _route_today, db.session)
            db.session.commit()
        except Exception:
            db.session.rollback()

    route_state = get_route_state(user_id, steps_today, db.session)

    # Recompute day_secured from actual activity (assembler always returns False).
    if phases and plan.get('_plan_meta', {}).get('effective_mode') == 'mission':
        required_phases = [p for p in phases if p.get('required', True)]
        plan['day_secured'] = bool(required_phases) and all(
            plan_completion.get(p.get('id', ''), False) for p in required_phases
        )

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
    from app.auth.models import User
    from app.daily_plan.rivals import is_adult_user
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary
    from app.achievements.streak_service import compute_plan_steps
    from app.achievements.daily_race import (
        get_race_standings,
        update_race_points_from_plan,
    )

    tz = _validate_timezone(request.args.get('tz', current_user.timezone or DEFAULT_TZ))
    user_id = current_user.id

    user = User.query.get(user_id)
    if user is None or not is_adult_user(user.birth_year):
        return api_error('age_restricted', 'Race feature not available', 403)

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
    """Return up to 3 continuation tasks after day is secured.

    This endpoint is distinct from /api/daily-plan/next-step (which returns the
    next incomplete phase from the current daily plan). This endpoint focuses on
    post-minimum continuation recommendations using priority-based heuristics.

    Returns JSON:
        steps: list of {kind, reason, data, estimated_minutes} (up to 3, may be empty)
        step: first item or null (backward compatibility)
    """
    from app.daily_plan.next_step import get_next_best_step

    user_id = current_user.id
    steps = get_next_best_step(user_id, db)

    def _serialize(s):
        return {
            'kind': s.kind,
            'reason': s.reason,
            'data': s.data,
            'estimated_minutes': s.estimated_minutes,
        }

    return jsonify({
        'success': True,
        'steps': [_serialize(s) for s in steps],
        'step': _serialize(steps[0]) if steps else None,
    })

_CLIENT_EVENTS = {
    'next_step_shown',
    'next_step_accepted',
    'next_step_dismissed',
    'session_ended_at_minimum',
    'rival_strip_shown',
    'rival_strip_dismissed',
    'steps_taken_while_rival_visible',
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
    from datetime import date as date_cls, datetime as datetime_cls, timezone, timedelta
    from app.daily_plan.models import DailyPlanEvent

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

    import pytz as _pytz_ev
    _tz_name_ev = getattr(current_user, 'timezone', None) or DEFAULT_TZ
    try:
        _tz_obj_ev = _pytz_ev.timezone(_tz_name_ev)
    except Exception:
        _tz_obj_ev = _pytz_ev.timezone(DEFAULT_TZ)
    user_today = datetime_cls.now(_tz_obj_ev).date()

    plan_date_str = body.get('plan_date')
    if plan_date_str:
        try:
            plan_date = date_cls.fromisoformat(plan_date_str)
            if plan_date > user_today or plan_date < user_today - timedelta(days=2):
                plan_date = user_today
        except ValueError:
            plan_date = user_today
    else:
        plan_date = user_today

    step_kind = body.get('step_kind')
    if step_kind:
        step_kind = str(step_kind)[:40]
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
    Uses savepoint so concurrent requests don't corrupt the outer transaction.
    """
    from sqlalchemy.exc import IntegrityError
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
    savepoint = db.session.begin_nested()
    db.session.add(event)
    try:
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        logger.debug(
            'minimum_completed already recorded for user=%s date=%s (concurrent insert)',
            user_id,
            plan_date,
        )


@api_daily_plan.route('/daily-plan/dismiss-rival-strip', methods=['POST'])
@csrf.exempt
@api_auth_required
def dismiss_rival_strip():
    """Permanently dismiss the ghost rival strip for the current user."""
    from app.auth.models import User

    user = db.session.get(User, current_user.id)
    if user is None:
        return api_error('not_found', 'User not found', 404)

    user.rival_strip_dismissed = True
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_error('db_error', 'Failed to dismiss rival strip', 500)

    return jsonify({'status': 'ok'})


@api_daily_plan.route('/streak/repair', methods=['POST'])
@csrf.exempt
@api_auth_required
def streak_repair():
    """Pay streak coins to repair a broken streak."""
    from app.achievements.streak_service import find_missed_date, apply_paid_repair
    from app.telegram.queries import get_current_streak

    user_id = current_user.id
    tz = _validate_timezone((request.get_json(silent=True) or {}).get('tz', DEFAULT_TZ))

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
