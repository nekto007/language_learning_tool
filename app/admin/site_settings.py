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
}


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
