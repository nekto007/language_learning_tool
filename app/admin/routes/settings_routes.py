# app/admin/routes/settings_routes.py

"""Admin settings page — site-wide configuration backed by SiteSettings key-value store."""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.site_settings import (
    SETTING_DEFAULTS,
    SETTING_META,
    SettingValidationError,
    get_site_setting,
    set_site_setting,
    validate_setting_value,
)
from app.admin.utils.decorators import admin_required
from app.utils.db import db

settings_bp = Blueprint('settings_admin', __name__)

logger = logging.getLogger(__name__)

# All editable keys exposed in the settings form.
# GSC tokens are managed via the OAuth flow, not the settings form;
# seo_audit_cache_version is bumped via the SEO admin "refresh" button.
_HIDDEN_KEYS = {'gsc_refresh_token', 'gsc_site_url', 'seo_audit_cache_version'}
_ALL_KEYS = [k for k in SETTING_DEFAULTS if k not in _HIDDEN_KEYS]


def _is_bool_key(key: str) -> bool:
    return SETTING_META.get(key, {}).get('type') == 'bool'


def _load_settings() -> dict:
    return {key: get_site_setting(key, default=SETTING_DEFAULTS.get(key, '')) for key in _ALL_KEYS}


@settings_bp.route('/settings', methods=['GET'])
@admin_required
def settings_index():
    settings = _load_settings()
    return render_template(
        'admin/settings/index.html',
        settings=settings,
        setting_meta=SETTING_META,
    )


@settings_bp.route('/settings', methods=['POST'])
@admin_required
def settings_save():
    # Validate every submitted value before writing anything so a single bad
    # field cannot leave the DB in a half-updated state.
    new_values: dict[str, str] = {}
    try:
        for key in _ALL_KEYS:
            if _is_bool_key(key):
                # Unchecked checkboxes simply don't appear in form data — treat
                # absence as 'false' rather than as a missing required field.
                raw = 'true' if request.form.get(key) else 'false'
            else:
                raw = request.form.get(key, '')
            new_values[key] = validate_setting_value(key, raw)
    except SettingValidationError as exc:
        logger.warning('Site settings validation failed: %s', exc)
        flash(f'Ошибка валидации: {exc}', 'danger')
        return redirect(url_for('settings_admin.settings_index'))

    try:
        # Snapshot existing values so we only audit-log keys that actually
        # changed. Reading happens via get_site_setting (which falls back to
        # SETTING_DEFAULTS) so an unseeded key still matches a no-op submit.
        previous = {
            key: get_site_setting(key, default=SETTING_DEFAULTS.get(key, ''))
            for key in _ALL_KEYS
        }
        changed_keys: list[str] = []
        for key, value in new_values.items():
            if value != (previous.get(key) or ''):
                changed_keys.append(key)
            set_site_setting(key, value)

        # One audit row per changed key keeps the log greppable per setting;
        # an additional aggregate row is omitted to avoid noise when nothing
        # actually changed.
        for key in changed_keys:
            log_admin_action(
                current_user.id,
                f'site_settings.update.{key}',
                target_type='site_settings',
            )

        db.session.commit()
        if changed_keys:
            flash(f'Настройки сохранены ({len(changed_keys)} изм.).', 'success')
            logger.info(
                'Site settings updated by admin_id=%s keys=%s',
                current_user.id,
                changed_keys,
            )
        else:
            flash('Изменений нет.', 'info')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to save site settings')
        flash('Ошибка при сохранении настроек.', 'danger')

    return redirect(url_for('settings_admin.settings_index'))
