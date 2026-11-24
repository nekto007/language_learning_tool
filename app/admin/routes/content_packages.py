"""Preview a curriculum content archive, then apply the same data in one transaction."""
# ruff: noqa: RUF001 -- messages in this view are displayed in Russian.
import logging
from time import time

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.services.content_package import read_content_package
from app.admin.services.content_package_import import apply_package, preview_package
from app.admin.utils.decorators import content_editor_required
from app.admin.utils.import_helpers import delete_import_data, load_import_data, save_import_data
from app.auth.models import User
from app.curriculum import cache as curriculum_cache
from app.utils.db import db

logger = logging.getLogger(__name__)
content_packages_bp = Blueprint('content_packages_admin', __name__)
_SESSION_KEY = 'content_package_preview'
_FILE_PREFIX = 'curriculum-'
_PREVIEW_LIFETIME = 3600


def _preview() -> dict | None:
    preview_id = session.get(_SESSION_KEY)
    if not preview_id:
        return None
    data = load_import_data(preview_id, prefix=_FILE_PREFIX)
    if (data and data.get('owner') == current_user.id
            and time() < data.get('expires', 0)):
        return data
    session.pop(_SESSION_KEY, None)
    return None


def _discard() -> None:
    preview_id = session.pop(_SESSION_KEY, None)
    if preview_id:
        try:
            delete_import_data(preview_id, prefix=_FILE_PREFIX)
        except OSError:
            logger.warning('Could not remove temporary curriculum preview', exc_info=True)


@content_packages_bp.route('/content-packages', methods=['GET', 'POST'])
@content_editor_required
def index() -> str | Response:
    if request.method != 'POST':
        return render_template('admin/content_packages.html', preview=_preview(),
                               preview_id=session.get(_SESSION_KEY))
    _discard()
    upload = request.files.get('file')
    try:
        if not upload or not (upload.filename or '').lower().endswith('.zip'):
            raise ValueError('Выберите ZIP с учебными материалами.')
        entries = read_content_package(upload.stream)
        summary = preview_package(entries)
        session[_SESSION_KEY] = save_import_data({
            'owner': current_user.id, 'expires': time() + _PREVIEW_LIFETIME,
            'filename': upload.filename[:160], 'summary': summary, 'entries': entries,
        }, prefix=_FILE_PREFIX)
    except ValueError as error:
        # Flash messages travel in the session cookie. A schema can report an error for every row.
        flash(str(error)[:350], 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('Content archive preview failed')
        flash('Не удалось подготовить предпросмотр. Загрузите архив ещё раз.', 'danger')
    return redirect(url_for('.index'), code=303)


@content_packages_bp.post('/content-packages/apply')
@content_editor_required
def apply() -> Response:
    # Keep this permission until publication commits, including when a preview
    # was prepared days or minutes before an administrator revoked the role.
    editor = User.query.filter_by(id=current_user.id).populate_existing().with_for_update(read=True).one_or_none()
    if editor is None or not editor.can_edit_content:
        abort(403)
    preview_id = request.form.get('preview_id')
    if not preview_id or preview_id != session.get(_SESSION_KEY) or not (data := _preview()):
        flash('Предпросмотр устарел. Проверьте архив ещё раз.', 'warning')
        return redirect(url_for('.index'), code=303)
    try:
        # Workers can read the same preview concurrently. Only the one that
        # removes the staged file owns this confirmation, even for an unchanged lesson.
        if not delete_import_data(preview_id, prefix=_FILE_PREFIX):
            flash('Предпросмотр уже закрыт. Для новой проверки загрузите архив ещё раз.', 'warning')
            return redirect(url_for('.index'), code=303)
        apply_package(data['entries'], data['summary'])
        log_admin_action(current_user.id, 'content_package.apply', target_type='curriculum')
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error)[:350], 'danger')
    except Exception:
        db.session.rollback()
        logger.exception('Content package import failed')
        flash('Не удалось подтвердить импорт. Проверьте материалы и загрузите архив заново.', 'danger')
    else:
        curriculum_cache.cache.clear()
        flash(f"Пакет «{data['filename']}» применён. Материалов в пакете — {len(data['summary'])}.", 'success')
    finally:
        session.pop(_SESSION_KEY, None)
    return redirect(url_for('.index'), code=303)
