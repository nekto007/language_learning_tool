# app/admin/routes/activity_routes.py

"""Protected learner diagnostics, activity history and cohort reports."""

import logging
from datetime import UTC, datetime, timedelta

from flask import Blueprint, abort, render_template, request

from app.admin.services.activity_feed_service import ALL_EVENT_TYPES, EVENT_TYPE_LABELS, get_recent_events
from app.admin.utils.decorators import admin_required
from app.utils.db import db

activity_bp = Blueprint('activity_admin', __name__)

logger = logging.getLogger(__name__)

_PER_PAGE = 50
# Each source fetches `offset + limit` rows then merges in Python; capping at
# 100 pages bounds per-request memory across the fixed set of event sources.
_MAX_PAGE = 100


def _registration_days(default=30):
    days = request.args.get('days', default, type=int)
    return days if days in (7, 14, 30, 60, 90) else default


def _curriculum_report(days, include_members=False, cohort_weeks=None):
    from app.admin.services.retention_report_service import build_report, read_snapshot, utc, weekly_cohorts
    as_of = datetime.now(UTC)
    registration_start = as_of - timedelta(days=days)
    cohort_start = registration_start
    if cohort_weeks:
        cohort_start = (as_of - timedelta(days=as_of.weekday(), weeks=cohort_weeks - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    users, progress, events, missing = read_snapshot(
        db.session.connection(), cutoff=min(registration_start, cohort_start), as_of=as_of)
    selected_users = [user for user in users if utc(user['created_at']) >= registration_start]
    report = build_report(selected_users, progress, events, as_of=as_of, days=days,
                          timezone_name='UTC', missing_sources=missing, include_members=include_members)
    if cohort_weeks:
        report['weekly_cohorts'] = weekly_cohorts(
            [user for user in users if utc(user['created_at']) >= cohort_start], events, as_of=as_of)
    return report


@activity_bp.route('/activity/students')
@admin_required
def activity_students():
    from app.admin.services.student_activity_service import STATUS_LABELS, get_students
    days_raw = request.args.get('days', '')
    if days_raw and days_raw not in ('7', '14', '30', '60', '90'):
        abort(400)
    days = _registration_days() if days_raw else None
    status = request.args.get('status', '')
    if status and status not in STATUS_LABELS:
        abort(400)
    level = request.args.get('level', '').upper()
    if level and level not in ('A1', 'A2', 'B1', 'B2', 'C1'):
        abort(400)
    stage = request.args.get('stage', '')
    stage_label = ''
    lesson_state = request.args.get('lesson_state', '')
    if lesson_state not in ('', 'opened', 'submitted', 'completed', 'idle_unfinished'):
        abort(400)
    user_ids = None
    if stage:
        days = days or 30
        report = _curriculum_report(days, include_members=True)
        memberships = report['memberships']
        if stage not in memberships:
            abort(400)
        user_ids = memberships[stage]
        labels = {step['key']: step['label'] for kind in ('progress_funnel', 'ordered_funnel')
                  for step in report[kind]['steps']}
        for day in ('D1', 'D7', 'D30'):
            labels[f'eligible_{day}'] = f'Полное окно наблюдения {day}'
            labels[f'retained_{day}'] = f'Есть учебная отправка строго на {day}'
        if '_without_' in stage:
            previous, following = stage.split('_without_', 1)
            stage_label = f"{labels.get(previous, previous)} → {labels.get(following, following)}: не перешли"
        else:
            stage_label = labels.get(stage, stage)
    active_days = request.args.get('active_days', type=int)
    if request.args.get('active_days') and active_days not in (1, 3, 7, 14, 30):
        abort(400)
    result = get_students(
        db.session, search=request.args.get('q', '').strip()[:120], days=days,
        level=level, status=status, lesson_id=request.args.get('lesson_id', type=int),
        lesson_state=lesson_state,
        user_ids=user_ids, source=request.args.get('source', '').strip()[:100],
        last_activity_days=active_days,
        page=request.args.get('page', 1, type=int) or 1, per_page=25)
    return render_template('admin/activity/students.html', result=result,
                           status_labels=STATUS_LABELS, stage=stage, stage_label=stage_label)


@activity_bp.route('/activity/students/<int:user_id>')
@admin_required
def activity_student_detail(user_id):
    from app.admin.services.student_activity_service import get_student_detail
    detail = get_student_detail(db.session, user_id)
    if detail is None:
        abort(404)
    source_errors = []
    events = get_recent_events(db.session, user_id=user_id, limit=100, source_errors=source_errors)
    return render_template('admin/activity/student_detail.html', detail=detail,
                           events=events, source_errors=source_errors, event_type_labels=EVENT_TYPE_LABELS)


@activity_bp.route('/activity/lessons')
@admin_required
def activity_lessons():
    from app.admin.services.student_activity_service import get_lesson_diagnostics
    days = _registration_days()
    lessons = get_lesson_diagnostics(db.session, days=days, limit=100)
    return render_template('admin/activity/lesson_diagnostics.html', lessons=lessons, days=days)


@activity_bp.route('/activity')
@admin_required
def activity_index():
    page = request.args.get('page', 1, type=int) or 1
    if page < 1:
        page = 1
    elif page > _MAX_PAGE:
        page = _MAX_PAGE

    user_id_raw = request.args.get('user_id', '').strip()
    user_id = int(user_id_raw) if user_id_raw.isdigit() else None

    selected_types = request.args.getlist('event_types') or None
    if selected_types is not None:
        selected_types = [t for t in selected_types if t in ALL_EVENT_TYPES]
        if not selected_types:
            selected_types = None

    date_from = _parse_date(request.args.get('date_from', ''))
    date_to = _parse_date(request.args.get('date_to', ''))

    offset = (page - 1) * _PER_PAGE

    source_errors = []
    events = get_recent_events(
        db_session=db.session,
        limit=_PER_PAGE + 1,  # fetch +1 to detect has_more
        offset=offset,
        user_id=user_id,
        event_types=selected_types,
        date_from=date_from,
        date_to=date_to,
        source_errors=source_errors,
    )

    has_more = len(events) > _PER_PAGE
    events = events[:_PER_PAGE]

    return render_template(
        'admin/activity/index.html',
        events=events,
        page=page,
        has_more=has_more,
        per_page=_PER_PAGE,
        all_event_types=ALL_EVENT_TYPES,
        event_type_labels=EVENT_TYPE_LABELS,
        filter_user_id=user_id_raw,
        filter_types=selected_types or [],
        filter_date_from=request.args.get('date_from', ''),
        filter_date_to=request.args.get('date_to', ''),
        source_errors=source_errors,
    )


@activity_bp.route('/activity/funnel')
@admin_required
def activity_funnel():
    days = request.args.get('days', 30, type=int)
    if days not in (7, 14, 30, 60, 90):
        days = 30
    weeks = request.args.get('weeks', 8, type=int)
    if weeks not in (4, 8, 12, 16):
        weeks = 8

    # Exact-day curriculum retention is independent of secured-day status.
    curriculum_report = None
    try:
        curriculum_report = _curriculum_report(days, cohort_weeks=weeks)
    except Exception:
        db.session.rollback()
        logger.exception('Could not build curriculum retention report')

    return render_template(
        'admin/activity/funnel.html',
        curriculum_report=curriculum_report,
        days=days,
        weeks=weeks,
    )


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
