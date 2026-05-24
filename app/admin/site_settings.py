# app/admin/site_settings.py

"""SiteSettings: key-value store for admin-configurable site parameters."""

import logging
from datetime import datetime, UTC
from typing import Any, Optional

from app.utils.db import db

logger = logging.getLogger(__name__)


# Defaults for all settings used across admin tasks.
# Values are stored as TEXT; callers cast to the appropriate type.
SETTING_DEFAULTS: dict[str, str] = {
    # Feature flags
    'default_linear_plan': 'false',
    'default_mission_plan': 'false',
    'daily_race_enabled': 'true',
    'streak_shield_enabled': 'true',
    # SEO defaults
    # site_title intentionally empty — templates fall back to their built-in
    # default copy when no admin has configured a value yet (prevents a silent
    # branding/SEO change on deploy).
    'site_title': '',
    'site_description': '',
    'og_image_url': '',
    'meta_keywords': '',
    # Contact
    'support_email': '',
    'support_phone': '',
    # Referral program
    'referral_bonus_xp': '100',
    # Google Search Console (populated via OAuth flow)
    'gsc_refresh_token': '',
    'gsc_site_url': '',
    # SEO audit cache version — bumped on admin refresh to invalidate the
    # per-worker in-memory cache across all gunicorn workers (each worker
    # recomputes once on next read instead of serving stale data).
    'seo_audit_cache_version': '1',
}


# Metadata for each setting key — type and human-readable description.
# Used by the admin UI to render tooltips and by the settings save handler
# to validate values before they hit the DB. Keys here must mirror
# SETTING_DEFAULTS exactly; an entry missing from SETTING_META falls back
# to type='str' with no description.
SETTING_META: dict[str, dict[str, str]] = {
    'default_linear_plan': {
        'type': 'bool',
        'description': 'Новые пользователи получают use_linear_plan=True при регистрации.',
    },
    'default_mission_plan': {
        'type': 'bool',
        'description': 'Новые пользователи получают use_mission_plan=True при регистрации.',
    },
    'daily_race_enabled': {
        'type': 'bool',
        'description': 'Включает функцию ежедневной гонки (daily race) на дашборде.',
    },
    'streak_shield_enabled': {
        'type': 'bool',
        'description': 'Включает защиту streak: пропущенный день не сбрасывает серию, если щит активен.',
    },
    'site_title': {
        'type': 'str',
        'description': 'Заголовок сайта (используется в <title> и og:title по умолчанию). Максимум 200 символов.',
        'max_length': '200',
    },
    'site_description': {
        'type': 'str',
        'description': 'Мета-описание для главных страниц (meta description / og:description). Максимум 300 символов.',
        'max_length': '300',
    },
    'og_image_url': {
        'type': 'url',
        'description': 'URL изображения для Open Graph превью (1200×630 рекомендуется). Максимум 500 символов.',
        'max_length': '500',
    },
    'meta_keywords': {
        'type': 'str',
        'description': 'Ключевые слова через запятую для meta keywords. Максимум 500 символов.',
        'max_length': '500',
    },
    'support_email': {
        'type': 'email',
        'description': 'Email поддержки, отображается в подвале и контактах. Максимум 200 символов.',
        'max_length': '200',
    },
    'support_phone': {
        'type': 'str',
        'description': 'Телефон поддержки, отображается в подвале и контактах. Максимум 50 символов.',
        'max_length': '50',
    },
    'referral_bonus_xp': {
        'type': 'int',
        'description': 'XP, начисляемые рефереру после онбординга приглашённого. Диапазон 0..10000.',
        'min': '0',
        'max': '10000',
    },
    'gsc_refresh_token': {
        'type': 'str',
        'description': 'OAuth refresh-токен Google Search Console (управляется через OAuth-флоу).',
    },
    'gsc_site_url': {
        'type': 'str',
        'description': 'URL сайта, выбранный при подключении GSC (управляется через OAuth-флоу).',
    },
    'seo_audit_cache_version': {
        'type': 'int',
        'description': 'Версия кэша SEO-аудита. Bump инвалидируется per-worker кэш.',
        'min': '0',
    },
}


_BOOL_TRUE_VALUES = {'true', '1', 'yes', 'on'}
_BOOL_FALSE_VALUES = {'false', '0', 'no', 'off', ''}


class SettingValidationError(ValueError):
    """Raised when a setting value fails type validation."""


def validate_setting_value(key: str, raw_value: str) -> str:
    """Validate and normalise *raw_value* for *key* against SETTING_META.

    Returns the canonical string representation safe to persist (e.g. bool
    inputs collapse to 'true'/'false'; int inputs strip whitespace and apply
    min/max clamping; url/email inputs reject obviously broken values).
    Raises SettingValidationError when the value cannot be normalised.

    Empty strings are allowed for non-bool types — callers explicitly clear
    a setting by submitting an empty form field, so blanks should never
    trigger a validation failure.
    """
    meta = SETTING_META.get(key, {})
    value_type = meta.get('type', 'str')
    raw = (raw_value or '').strip()

    if value_type == 'bool':
        lowered = raw.lower()
        if lowered in _BOOL_TRUE_VALUES:
            return 'true'
        if lowered in _BOOL_FALSE_VALUES:
            return 'false'
        raise SettingValidationError(
            f'{key}: ожидалось булево значение, получено {raw_value!r}'
        )

    if value_type == 'int':
        if raw == '':
            return SETTING_DEFAULTS.get(key, '0') or '0'
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise SettingValidationError(
                f'{key}: ожидалось целое число, получено {raw_value!r}'
            ) from exc
        try:
            lo = int(meta.get('min', '')) if 'min' in meta else None
            hi = int(meta.get('max', '')) if 'max' in meta else None
        except ValueError:
            lo, hi = None, None
        if lo is not None and parsed < lo:
            parsed = lo
        if hi is not None and parsed > hi:
            parsed = hi
        return str(parsed)

    # str/url/email
    try:
        max_length = int(meta.get('max_length', '0')) if 'max_length' in meta else 0
    except ValueError:
        max_length = 0
    if max_length and len(raw) > max_length:
        raise SettingValidationError(
            f'{key}: длина превышает максимум {max_length} символов'
        )

    if raw == '':
        return ''

    if value_type == 'email':
        # Lightweight email shape check: presence of "@" and "." after it.
        if '@' not in raw or '.' not in raw.split('@')[-1]:
            raise SettingValidationError(
                f'{key}: ожидался email, получено {raw_value!r}'
            )

    if value_type == 'url':
        if not (raw.startswith('http://') or raw.startswith('https://')):
            raise SettingValidationError(
                f'{key}: ожидался URL, начинающийся с http(s)://, получено {raw_value!r}'
            )

    return raw


class SiteSettings(db.Model):
    """Key-value store for site-wide configuration managed by admins."""

    __tablename__ = 'site_settings'

    key = db.Column(db.Text, primary_key=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    def __repr__(self) -> str:
        return f'<SiteSettings key={self.key!r} value={self.value!r}>'


def get_site_setting(key: str, default: Any = None, db_session=None) -> Optional[str]:
    """Return the stored value for *key*, or a default if not found.

    Read-only — never writes to the DB. Falls back first to *default*, then to
    `SETTING_DEFAULTS[key]`, then to None. Use `ensure_defaults_seeded()` (or
    the admin settings POST) to persist defaults.
    """
    session = db_session or db.session
    row = session.get(SiteSettings, key)
    if row is not None:
        return row.value
    if default is not None:
        return default
    return SETTING_DEFAULTS.get(key)


def set_site_setting(key: str, value: str, db_session=None) -> SiteSettings:
    """Upsert *key* → *value*.  Flush only — caller commits."""
    session = db_session or db.session
    row = session.get(SiteSettings, key)
    if row is None:
        row = SiteSettings(key=key, value=value)
        session.add(row)
    else:
        row.value = value
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.flush()
    return row


_PUBLIC_SETTING_KEYS = (
    'site_title',
    'site_description',
    'og_image_url',
    'meta_keywords',
    'support_email',
    'support_phone',
)


def get_referral_bonus_xp(db_session=None) -> int:
    """Return the referral bonus XP as an int, with safe fallback to 100."""
    try:
        raw = get_site_setting('referral_bonus_xp', '100', db_session=db_session) or '100'
        return int(raw)
    except (TypeError, ValueError):
        return 100


def is_streak_shield_enabled(db_session=None) -> bool:
    """Return True when the streak-shield feature flag is enabled."""
    try:
        return (
            get_site_setting('streak_shield_enabled', 'true', db_session=db_session)
            == 'true'
        )
    except Exception:
        return True


def get_public_settings(db_session=None) -> dict[str, str]:
    """Return the subset of SiteSettings safe to expose to public templates.

    Single bulk query — called from a global template context processor on
    every public page render, so the per-key `session.get()` loop is avoided.
    """
    session = db_session or db.session
    rows = (
        session.query(SiteSettings.key, SiteSettings.value)
        .filter(SiteSettings.key.in_(_PUBLIC_SETTING_KEYS))
        .all()
    )
    stored = {key: (value or '') for key, value in rows}
    return {
        key: stored.get(key) or SETTING_DEFAULTS.get(key, '') or ''
        for key in _PUBLIC_SETTING_KEYS
    }


def ensure_defaults_seeded(db_session=None) -> None:
    """Create any missing default rows in site_settings.  Caller commits."""
    session = db_session or db.session
    for key, default_value in SETTING_DEFAULTS.items():
        existing = session.get(SiteSettings, key)
        if existing is None:
            session.add(SiteSettings(key=key, value=default_value))
    session.flush()
