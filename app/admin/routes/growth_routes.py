"""Focused, private admin report for 100 genuinely weekly learners."""

import json
import logging
from math import ceil

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import text

from app.admin.audit import log_admin_action
from app.admin.services.growth_service import (
    EXCLUSION_REASONS, EXCLUSIONS_KEY, STATE_LABELS, get_report, load_overrides,
)
from app.admin.site_settings import set_site_setting
from app.admin.utils.decorators import admin_required
from app.auth.models import User
from app.curriculum.rate_limiter import rate_limit
from app.utils.db import db

growth_bp = Blueprint('growth_admin', __name__)
logger = logging.getLogger(__name__)


@growth_bp.after_request
def private_report(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@growth_bp.route('/growth')
@admin_required
def index():
    view = request.args.get('view', 'overview')
    state = request.args.get('state', '')
    if view not in ('overview', 'exclusions') or state not in ('', 'active7', 'lost', *STATE_LABELS):
        abort(400)
    q = request.args.get('q', '').strip()[:120]
    source = request.args.get('source', '').strip()[:100]
    lesson_id = request.args.get('lesson_id', type=int)
    try:
        report = get_report(db.session)
    except Exception:
        db.session.rollback()
        logger.exception('Growth report unavailable')
        return make_response(render_template('admin/growth/index.html', report=None), 503)
    rows = report['accounts'] if view == 'exclusions' else report['learners']
    if q:
        rows = ([u for u in rows if u['id'] == int(q)] if q.isascii() and q.isdigit() else
                [u for u in rows if q.casefold() in f"{u['username']} {u.get('email') or ''}".casefold()])
    if view == 'overview':
        if source:
            rows = [u for u in rows if u['source']['label'] == source]
        if state == 'active7':
            rows = [u for u in rows if u['active7']]
        elif state == 'lost':
            rows = [u for u in rows if u['previous_week'] and not u['active7']]
        elif state:
            rows = [u for u in rows if u['state'] == state]
        if lesson_id:
            stopped = next((item['user_ids'] for item in report['bottlenecks'] if item['id'] == lesson_id), ())
            rows = [u for u in rows if u['id'] in stopped]
    page_size = 25
    pages = max(1, ceil(len(rows) / page_size))
    page = min(pages, max(1, request.args.get('page', 1, type=int)))
    return render_template(
        'admin/growth/index.html', report=report, view=view, rows=rows[(page - 1) * page_size:page * page_size],
        row_count=len(rows), page=page, pages=pages, q=q, source=source, state=state,
        reasons=EXCLUSION_REASONS, states=STATE_LABELS, lesson_id=lesson_id,
    )


@growth_bp.route('/growth/accounts/<int:user_id>/visibility', methods=['POST'])
@admin_required
@rate_limit(limit=30, window=60, per='user')
def account_visibility(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    action, reason = request.form.get('action'), request.form.get('reason')
    if action not in ('exclude', 'include', 'auto') or (action == 'exclude' and reason not in EXCLUSION_REASONS):
        abort(400)
    if user.is_admin:
        flash('Администраторы всегда исключены из цели.', 'info')
        return redirect(url_for('growth_admin.index', view='exclusions'))
    try:
        # A transaction-scoped lock also serializes the first insert and edits by
        # different admins. Read the setting only after acquiring the lock.
        if db.session.get_bind().dialect.name == 'postgresql':
            db.session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 10020261123})
        overrides = load_overrides(db.session)
        if action == 'auto':
            overrides.pop(str(user_id), None)
        else:
            overrides[str(user_id)] = {'excluded': action == 'exclude', 'reason': reason if action == 'exclude' else ''}
        set_site_setting(EXCLUSIONS_KEY, json.dumps(overrides, ensure_ascii=False))
        log_admin_action(current_user.id, f'growth.account_{action}', target_type='user', target_id=user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not update growth account exclusions')
        flash('Не удалось сохранить исключение. Список не изменён.', 'danger')  # noqa: RUF001
        return redirect(url_for('growth_admin.index', view='exclusions'))
    flash('Учёт в аналитике обновлён. Аккаунт и учебные данные сохранены.', 'success')
    return redirect(url_for('growth_admin.index', view='exclusions', _anchor=f'account-{user_id}'))
