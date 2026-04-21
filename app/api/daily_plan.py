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
    effective_mode = plan.get('_plan_meta', {}).get('effective_mode')
    if phases and effective_mode == 'mission':
        required_phases = [p for p in phases if p.get('required', True)]
        day_secured = bool(required_phases) and all(
            plan_completion.get(p.get('id', ''), False) for p in required_phases
        )
    elif effective_mode == 'linear':
        baseline_slots = plan.get('baseline_slots') or []
        day_secured = bool(baseline_slots) and all(
            plan_completion.get(slot.get('kind', ''), False)
            for slot in baseline_slots
        )
        if isinstance(plan.get('continuation'), dict):
            plan['continuation']['available'] = bool(
                day_secured and (plan['continuation'].get('next_lessons') or [])
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
    effective_mode = plan.get('_plan_meta', {}).get('effective_mode')
    if phases and effective_mode == 'mission':
        required_phases = [p for p in phases if p.get('required', True)]
        plan['day_secured'] = bool(required_phases) and all(
            plan_completion.get(p.get('id', ''), False) for p in required_phases
        )
    elif effective_mode == 'linear':
        baseline_slots = plan.get('baseline_slots') or []
        plan['day_secured'] = bool(baseline_slots) and all(
            plan_completion.get(slot.get('kind', ''), False)
            for slot in baseline_slots
        )
        if isinstance(plan.get('continuation'), dict):
            plan['continuation']['available'] = bool(
                plan['day_secured'] and (plan['continuation'].get('next_lessons') or [])
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


# Mapping between internal ``LinearSlot.kind`` values (used inside the
# plan payload and ``plan_completion`` dict) and ``LinearSlotKind`` values
# (the stable query-param form surfaced in URLs and frontend sessionStorage).
# Only the reading slot diverges — everything else is 1:1.
_SLOT_KIND_TO_LINEAR = {
    'curriculum': 'curriculum',
    'srs': 'srs',
    'reading': 'book',
    'error_review': 'error_review',
}
_LINEAR_TO_SLOT_KIND = {v: k for k, v in _SLOT_KIND_TO_LINEAR.items()}


@api_daily_plan.route('/daily-plan/next-slot')
@api_auth_required
def daily_plan_next_slot():
    """Return the next incomplete baseline slot for the linear daily plan.

    Gated on ``User.use_linear_plan`` — returns 404 for users on
    mission/legacy so stale plan-context URLs (e.g. a Telegram link with
    ``?from=linear_plan``) cannot influence unrelated flows.

    Query params:
        current (str, optional): LinearSlotKind value (curriculum/srs/book/
            error_review) identifying the slot the caller just left. The
            endpoint skips that kind when picking the next slot, even if
            it is still incomplete — the caller has already engaged with it.
        tz (str, optional): user timezone. Used to resolve the local day
            for the secured_at write.

    Response JSON:
        next: {"kind", "url", "title"} | null — first incomplete baseline
            slot whose kind != ``current``. ``null`` when the day is
            secured (all baseline slots completed).
        day_secured: bool — True when every baseline slot is completed
            (combining slot state + summary signals, same recomputation
            used by /api/daily-status).
        secured_just_now: bool — True iff this call is the one that
            wrote ``DailyPlanLog.secured_at``. Idempotent across calls:
            subsequent invocations on the same day return False.
    """
    from datetime import datetime
    import pytz

    from app.auth.models import User
    from app.daily_plan.linear.plan import get_linear_plan
    from app.daily_plan.models import DailyPlanLog
    from app.daily_plan.service import write_secured_at
    from app.telegram.queries import get_daily_summary
    from app.achievements.streak_service import compute_plan_steps

    user = User.query.get(current_user.id)
    if user is None or not user.use_linear_plan:
        return api_error('linear_plan_disabled', 'Linear plan not enabled', 404)

    tz = _validate_timezone(request.args.get('tz', user.timezone or DEFAULT_TZ))
    raw_current = request.args.get('current')
    current_slot_kind = _LINEAR_TO_SLOT_KIND.get(raw_current) if raw_current else None

    plan = get_linear_plan(user.id)
    summary = get_daily_summary(user.id, tz=tz)
    plan_completion, _, _, _ = compute_plan_steps(plan, summary)

    baseline_slots = plan.get('baseline_slots') or []
    day_secured = bool(baseline_slots) and all(
        plan_completion.get(slot.get('kind', ''), False)
        for slot in baseline_slots
    )

    next_slot_payload = None
    if not day_secured:
        for slot in baseline_slots:
            slot_kind = slot.get('kind', '')
            if slot_kind == current_slot_kind:
                continue
            if plan_completion.get(slot_kind, False):
                continue
            slot_url = slot.get('url')
            # Fragment-only URLs (e.g. ``#book-select-modal`` when the user
            # has no chosen book yet) only work on the dashboard, so rewrite
            # them so the CTA from a lesson completion actually goes somewhere.
            if isinstance(slot_url, str) and slot_url.startswith('#'):
                slot_url = '/dashboard' + slot_url
            next_slot_payload = {
                'kind': _SLOT_KIND_TO_LINEAR.get(slot_kind, slot_kind),
                'url': slot_url,
                'title': slot.get('title'),
            }
            break

    secured_just_now = False
    if day_secured:
        try:
            tz_obj = pytz.timezone(tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone(DEFAULT_TZ)
        today = datetime.now(tz_obj).date()

        existing = DailyPlanLog.query.filter_by(
            user_id=user.id, plan_date=today,
        ).first()
        was_already_secured = existing is not None and existing.secured_at is not None

        try:
            emit_minimum_completed(user.id, None, today)
            write_secured_at(user.id, today, None)
            db.session.commit()
            secured_just_now = not was_already_secured
        except Exception:
            logger.warning(
                "secured_at write failed in daily_plan_next_slot",
                exc_info=True,
            )
            db.session.rollback()

    return jsonify({
        'success': True,
        'next': next_slot_payload,
        'day_secured': day_secured,
        'secured_just_now': secured_just_now,
    })


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


@api_daily_plan.route('/daily-plan/error-review/complete', methods=['POST'])
@csrf.exempt
@api_auth_required
def complete_error_review():
    """Complete a linear-plan error-review session.

    Body JSON:
        error_ids (list[int], optional): quiz_error_log ids resolved in
            this session. Unknown ids or ids belonging to other users
            are skipped silently.

    Always attempts the linear ``error_review`` XP award (idempotent per
    day) and surfaces any level-up / day-secured transitions in the
    response.
    """
    from app.daily_plan.linear.errors import resolve_quiz_errors
    from app.daily_plan.linear.xp import (
        maybe_award_error_review_xp,
        maybe_award_linear_perfect_day,
    )

    body = request.get_json(silent=True) or {}
    raw_ids = body.get('error_ids') or []
    if not isinstance(raw_ids, list):
        return api_error('invalid_error_ids', 'error_ids must be a list', 400)

    error_ids: list[int] = []
    for raw in raw_ids:
        try:
            error_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    user_id = current_user.id
    resolved = resolve_quiz_errors(error_ids, user_id, db, commit=False)

    xp_award = maybe_award_error_review_xp(user_id, db_session=db)
    perfect_day = None
    if xp_award is not None:
        perfect_day = maybe_award_linear_perfect_day(user_id, db_session=db)

    try:
        db.session.commit()
    except Exception:
        logger.warning(
            "linear_xp: error-review commit failed user=%s", user_id, exc_info=True,
        )
        db.session.rollback()
        return api_error('db_error', 'Failed to record error review', 500)

    response = {
        'success': True,
        'resolved_count': len(resolved),
    }
    if xp_award is not None:
        response['xp'] = {
            'awarded': xp_award.xp_awarded,
            'total': xp_award.new_total_xp,
            'level': xp_award.new_level,
            'leveled_up': xp_award.leveled_up,
        }
    if perfect_day is not None:
        response['perfect_day_bonus'] = {
            'awarded': perfect_day.xp_awarded,
            'total': perfect_day.new_total_xp,
            'level': perfect_day.new_level,
            'leveled_up': perfect_day.leveled_up,
        }
    return jsonify(response)


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
