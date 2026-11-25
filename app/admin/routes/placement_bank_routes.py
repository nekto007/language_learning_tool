"""Private administrative review and activation for placement banks."""

import json
from collections import Counter
from time import time

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.admin.utils.import_helpers import delete_import_data, load_import_data, save_import_data
from app.auth.models import User
from app.onboarding.placement_bank import (
    LEVELS, MAX_BANK_BYTES, SKILL_LABELS, activate_bank, active_bank, bank_digest, read_bank, validate_bank,
)
from app.onboarding.placement_models import PlacementBank
from app.utils.db import db

placement_bank_bp = Blueprint('placement_bank_admin', __name__)
_PREFIX = 'private-placement-'
_STAGED = 'placement_bank_preview'
_PER_PAGE = 24
_DIFF_PER_PAGE = 12


def _list_filters() -> dict:
    q = request.args.get('q', '').strip()[:100]
    level = request.args.get('level', '')
    skill = request.args.get('skill', '')
    return {
        'q': q, 'level': level if level in LEVELS else '',
        'skill': skill if skill in SKILL_LABELS else '',
        'page': max(1, request.args.get('page', 1, type=int) or 1),
    }


@placement_bank_bp.after_request
def _private(response: Response) -> Response:
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex'
    return response


def _discard() -> None:
    if preview_id := session.pop(_STAGED, None):
        delete_import_data(preview_id, prefix=_PREFIX)


def _staged(preview_id: str) -> dict | None:
    if not preview_id or preview_id != session.get(_STAGED):
        return None
    data = load_import_data(preview_id, prefix=_PREFIX)
    return data if data and data['owner'] == current_user.id and data['expires'] > time() else None


def _begin_preview(document: dict, bank: PlacementBank | None, return_filters: dict | None = None) -> Response:
    validate_bank(document)
    if len(json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()) > MAX_BANK_BYTES:
        raise ValueError('Банк превышает 4 МБ.')
    _discard()
    session[_STAGED] = save_import_data({
        'owner': current_user.id, 'expires': time() + 1800,
        'baseline': bank.id if bank else None, 'document': document, 'return_filters': return_filters or {},
    }, prefix=_PREFIX, private=True)
    return redirect(url_for('.preview'), code=303)


def _diff(before: dict | None, after: dict, requested_page: int) -> dict:
    old = {item['id']: item for item in before['items']} if before else {}
    new = {item['id']: item for item in after['items']}
    changed = [key for key in new if key in old and new[key] != old[key]]
    added = [key for key in new if key not in old]
    removed = [key for key in old if key not in new]
    keys = [*changed, *added, *removed]
    pages = max(1, (len(keys) + _DIFF_PER_PAGE - 1) // _DIFF_PER_PAGE)
    page = min(max(1, requested_page), pages)
    counts = Counter((q['level'], q['skill']) for q in after['items'])
    return {
        'changed': len(changed), 'added': len(added), 'removed': len(removed), 'counts': counts,
        'page': page, 'pages': pages,
        'examples': [(key, old.get(key), new.get(key))
                     for key in keys[(page - 1) * _DIFF_PER_PAGE:page * _DIFF_PER_PAGE]],
    }


@placement_bank_bp.get('/placement-bank')
@admin_required
def index() -> str:
    bank = active_bank()
    filters = _list_filters()
    q, level, skill = filters['q'], filters['level'], filters['skill']
    choices = bank.content['items'] if bank else []
    filtered = [row for row in choices if (
        (not level or row['level'] == level) and (not skill or row['skill'] == skill)
        and (not q or q.casefold() in (row['id'] + ' ' + row['prompt']).casefold())
    )]
    pages = max(1, (len(filtered) + _PER_PAGE - 1) // _PER_PAGE)
    page = min(pages, filters['page'])
    filters['page'] = page
    versions = db.session.execute(db.select(
        PlacementBank.id, PlacementBank.label, PlacementBank.active, PlacementBank.created_at,
    ).order_by(PlacementBank.created_at.desc(), PlacementBank.id).limit(12)).all()
    return render_template('admin/placement_bank/index.html', bank=bank, choices=filtered[(page - 1) * _PER_PAGE:page * _PER_PAGE],
                           versions=versions, q=q, level=level, skill=skill, page=page, pages=pages, count=len(choices),
                           levels=LEVELS, skills=SKILL_LABELS, filters=filters)


@placement_bank_bp.post('/placement-bank/upload')
@admin_required
def upload() -> Response:
    source = request.files.get('bank')
    if not source or not (source.filename or '').lower().endswith('.json'):
        flash('Выберите файл банка в формате JSON.', 'warning')
    else:
        try:
            return _begin_preview(read_bank(source.stream.read(MAX_BANK_BYTES + 1)), active_bank())
        except ValueError as exc:
            flash(f'Банк не прошёл проверку. {str(exc)[:250]}', 'warning')
    return redirect(url_for('.index'), code=303)


@placement_bank_bp.route('/placement-bank/questions/<item_id>', methods=['GET', 'POST'])
@admin_required
def edit_item(item_id: str) -> ResponseReturnValue:
    filters = _list_filters()
    bank = active_bank()
    if bank is None:
        abort(404)
    item = next((row for row in bank.content['items'] if row['id'] == item_id), None)
    if item is None:
        abort(404)
    error, status = '', 200
    if request.method == 'POST':
        if request.form.get('bank_id') != bank.id:
            return render_template('admin/placement_bank/edit.html', bank=bank, item=item, skills=SKILL_LABELS,
                                   filters=filters,
                                   error='Версия банка изменилась. Сверьте текущий вопрос и повторите правку.'), 409
        candidate = item.copy()
        candidate['prompt'] = request.form.get('prompt', '').strip()
        candidate['answers'] = [line.strip() for line in request.form.get('answers', '').splitlines() if line.strip()]
        if item['input'] == 'choice':
            candidate['options'] = [line.strip() for line in request.form.get('options', '').splitlines() if line.strip()]
        for field in ('passage', 'audio_url', 'topic', 'topic_slug'):
            if field in item or field in request.form:
                value = request.form.get(field, '').strip()
                if value or field in ('passage', 'audio_url'):
                    candidate[field] = value
                else:
                    candidate.pop(field, None)
        document = {**bank.content, 'items': [
            candidate if row['id'] == item_id else row for row in bank.content['items']
        ]}
        try:
            if candidate == item:
                raise ValueError('Изменений нет.')
            return _begin_preview(document, bank, filters)
        except ValueError as exc:
            item, error, status = candidate, f'Вопрос не прошёл проверку. {str(exc)[:250]}', 422
    return render_template('admin/placement_bank/edit.html', bank=bank, item=item, skills=SKILL_LABELS,
                           error=error, filters=filters), status


@placement_bank_bp.get('/placement-bank/preview')
@admin_required
def preview() -> ResponseReturnValue:
    preview_id = session.get(_STAGED, '')
    data = _staged(preview_id)
    if data is None:
        flash('Предпросмотр истёк. Подготовьте новую версию.', 'warning')
        return redirect(url_for('.index'))
    bank = active_bank()
    before = db.session.get(PlacementBank, data['baseline']) if data['baseline'] else None
    document = data['document']
    return render_template('admin/placement_bank/preview.html', document=document, digest=bank_digest(document),
                           diff=_diff(before.content if before else None, document,
                                      request.args.get('page', 1, type=int) or 1), preview_id=preview_id,
                           filters=data.get('return_filters', {}),
                           old_label=before.label if before else None, levels=LEVELS, skills=SKILL_LABELS,
                           unchanged=bool(before and before.id == bank_digest(document)),
                           stale=(bank.id if bank else None) != data['baseline'])


@placement_bank_bp.post('/placement-bank/activate')
@admin_required
def activate() -> ResponseReturnValue:
    editor = User.query.filter_by(id=current_user.id).with_for_update(read=True).populate_existing().one_or_none()
    if editor is None or not editor.is_active or not editor.is_admin:
        abort(403)
    data = _staged(request.form.get('preview_id', ''))
    if data is None:
        flash('Предпросмотр истёк. Подготовьте новую версию.', 'warning')
        return redirect(url_for('.index'), code=303)
    try:
        digest, changed = activate_bank(data['document'], expected_active=data['baseline'])
        if changed:
            log_admin_action(current_user.id, 'placement.bank.activate', 'placement_bank', required=True)
        db.session.commit()
    except ValueError:
        db.session.rollback()
        _discard()
        return render_template('admin/placement_bank/conflict.html', filters=data.get('return_filters', {})), 409
    except Exception:
        db.session.rollback()
        raise
    _discard()
    if changed:
        current_app.logger.info('Placement bank activated: version=%s admin_id=%s', digest, current_user.id)
    flash('Новая версия банка активна.' if changed else 'Эта версия уже активна.', 'success')
    return redirect(url_for('.index', **data.get('return_filters', {})), code=303)
