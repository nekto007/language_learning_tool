# app/admin/routes/activity_routes.py

"""Admin user activity feed — paginated, filterable chronological event log."""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request

from app.admin.services.activity_feed_service import ALL_EVENT_TYPES, EVENT_TYPE_LABELS, get_recent_events
from app.admin.services.cohort_service import get_cohort_retention, get_funnel_data
from app.admin.utils.decorators import admin_required
from app.utils.db import db

activity_bp = Blueprint('activity_admin', __name__)

logger = logging.getLogger(__name__)

_PER_PAGE = 50
# Each source fetches `offset + limit` rows then merges in Python; capping at
# 100 pages bounds per-request memory at ~25k rows across five sources.
_MAX_PAGE = 100


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

    events = get_recent_events(
        db_session=db.session,
        limit=_PER_PAGE + 1,  # fetch +1 to detect has_more
        offset=offset,
        user_id=user_id,
        event_types=selected_types,
        date_from=date_from,
        date_to=date_to,
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

    funnel = get_funnel_data(db.session, days=days)
    cohorts = get_cohort_retention(db.session, weeks=weeks)

    return render_template(
        'admin/activity/funnel.html',
        funnel=funnel,
        cohorts=cohorts,
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
