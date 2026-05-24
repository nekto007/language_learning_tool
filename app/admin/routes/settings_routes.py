# app/admin/routes/settings_routes.py

"""Admin settings page — site-wide configuration backed by SiteSettings key-value store."""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.site_settings import SETTING_DEFAULTS, get_site_setting, set_site_setting
from app.admin.utils.decorators import admin_required
from app.utils.db import db

settings_bp = Blueprint('settings_admin', __name__)

logger = logging.getLogger(__name__)

_BOOL_KEYS = {
    'default_linear_plan',
    'default_mission_plan',
    'daily_race_enabled',
    'streak_shield_enabled',
}

_INT_KEYS = {
    'referral_bonus_xp',
}

# All editable keys exposed in the settings form
_ALL_KEYS = [k for k in SETTING_DEFAULTS if k not in {'gsc_refresh_token', 'gsc_site_url'}]


def _load_settings() -> dict:
    return {key: get_site_setting(key, default=SETTING_DEFAULTS.get(key, '')) for key in _ALL_KEYS}


@settings_bp.route('/settings', methods=['GET'])
@admin_required
def settings_index():
    settings = _load_settings()
    return render_template('admin/settings/index.html', settings=settings)


@settings_bp.route('/settings', methods=['POST'])
@admin_required
def settings_save():
    try:
        for key in _ALL_KEYS:
            if key in _BOOL_KEYS:
                value = 'true' if request.form.get(key) else 'false'
            elif key in _INT_KEYS:
                raw = request.form.get(key, '').strip()
                try:
                    parsed = int(raw) if raw else int(SETTING_DEFAULTS.get(key, '0') or 0)
                except ValueError:
                    parsed = int(SETTING_DEFAULTS.get(key, '0') or 0)
                if parsed < 0:
                    parsed = 0
                value = str(parsed)
            else:
                value = request.form.get(key, '').strip()
            set_site_setting(key, value)
        log_admin_action(current_user.id, 'site_settings.update', target_type='site_settings')
        db.session.commit()
        flash('Настройки сохранены.', 'success')
        logger.info('Site settings updated')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to save site settings')
        flash('Ошибка при сохранении настроек.', 'danger')

    return redirect(url_for('settings_admin.settings_index'))
