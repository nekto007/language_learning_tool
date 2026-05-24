# app/admin/routes/audit_routes.py

"""Admin audit log — paginated, filterable view over AdminAuditLog records."""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from sqlalchemy import desc

from app.admin.audit import AdminAuditLog
from app.admin.utils.decorators import admin_required
from app.admin.utils.export_helpers import (
    MAX_EXPORT_ROWS,
    _sanitize_csv_cell,
    _stream_csv_rows,
)
from app.auth.models import User
from app.utils.db import db
from flask import Response
from flask import stream_with_context

audit_bp = Blueprint('audit_admin', __name__)

logger = logging.getLogger(__name__)

_PER_PAGE = 50
_MAX_PAGE = 1000


@audit_bp.route('/audit-log')
@admin_required
def audit_index():
    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1
    elif page > _MAX_PAGE:
        page = _MAX_PAGE

    admin_id_raw = request.args.get('admin_id', '').strip()
    admin_id = int(admin_id_raw) if admin_id_raw.isdigit() else None

    action_filter = request.args.get('action', '').strip()[:200]
    date_from = _parse_date(request.args.get('date_from', ''))
    date_to = _parse_date(request.args.get('date_to', ''))

    offset = (page - 1) * _PER_PAGE

    entries, has_more = _get_audit_entries(
        db.session,
        limit=_PER_PAGE,
        offset=offset,
        admin_id=admin_id,
        action_filter=action_filter or None,
        date_from=date_from,
        date_to=date_to,
    )

    admin_users = (
        db.session.query(User)
        .filter(User.is_admin == True)  # noqa: E712
        .order_by(User.email)
        .all()
    )

    return render_template(
        'admin/audit/index.html',
        entries=entries,
        page=page,
        has_more=has_more,
        per_page=_PER_PAGE,
        admin_users=admin_users,
        filter_admin_id=admin_id_raw,
        filter_action=action_filter,
        filter_date_from=request.args.get('date_from', ''),
        filter_date_to=request.args.get('date_to', ''),
    )


def _get_audit_entries(
    db_session,
    limit: int,
    offset: int,
    admin_id: int | None = None,
    action_filter: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[dict], bool]:
    query = (
        db_session.query(AdminAuditLog, User)
        .outerjoin(User, AdminAuditLog.admin_id == User.id)
        .order_by(desc(AdminAuditLog.created_at))
    )

    if admin_id is not None:
        query = query.filter(AdminAuditLog.admin_id == admin_id)
    if action_filter:
        query = query.filter(AdminAuditLog.action.ilike(f'%{action_filter}%'))
    if date_from:
        query = query.filter(AdminAuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AdminAuditLog.created_at < date_to + timedelta(days=1))

    rows = query.limit(limit + 1).offset(offset).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    entries = []
    for log, user in rows:
        entries.append({
            'id': log.id,
            'timestamp': log.created_at,
            'admin_id': log.admin_id,
            'admin_email': user.email if user else '(deleted)',
            'action': log.action,
            'target_type': log.target_type,
            'target_id': log.target_id,
        })

    return entries, has_more


@audit_bp.route('/audit-log/export.csv')
@admin_required
def audit_export_csv():
    """Export filtered audit log to CSV (max MAX_EXPORT_ROWS rows)."""
    admin_id_raw = request.args.get('admin_id', '').strip()
    admin_id = int(admin_id_raw) if admin_id_raw.isdigit() else None
    action_filter = request.args.get('action', '').strip()[:200]
    date_from = _parse_date(request.args.get('date_from', ''))
    date_to = _parse_date(request.args.get('date_to', ''))

    query = (
        db.session.query(AdminAuditLog, User)
        .outerjoin(User, AdminAuditLog.admin_id == User.id)
        .order_by(desc(AdminAuditLog.created_at))
    )
    if admin_id is not None:
        query = query.filter(AdminAuditLog.admin_id == admin_id)
    if action_filter:
        query = query.filter(AdminAuditLog.action.ilike(f'%{action_filter}%'))
    if date_from:
        query = query.filter(AdminAuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AdminAuditLog.created_at < date_to + timedelta(days=1))

    rows = query.limit(MAX_EXPORT_ROWS).all()

    headers = ['ID', 'Timestamp', 'Admin Email', 'Action', 'Target Type', 'Target ID']

    def row_iter():
        for log, user in rows:
            yield [
                _sanitize_csv_cell(log.id),
                _sanitize_csv_cell(
                    log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else ''
                ),
                _sanitize_csv_cell(user.email if user else '(deleted)'),
                _sanitize_csv_cell(log.action),
                _sanitize_csv_cell(log.target_type or ''),
                _sanitize_csv_cell(log.target_id),
            ]

    from datetime import timezone as _tz
    ts = datetime.now(_tz.utc).strftime('%Y%m%d_%H%M%S')
    filename = f'admin_audit_log_{ts}.csv'
    response = Response(
        stream_with_context(_stream_csv_rows(headers, row_iter())),
        mimetype='text/csv; charset=utf-8',
    )
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
