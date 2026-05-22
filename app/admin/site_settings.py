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
    'site_title': 'Language Learning Tool',
    'site_description': '',
    'og_image_url': '',
    'meta_keywords': '',
    # Contact
    'support_email': '',
    'support_phone': '',
    # Referral program
    'referral_bonus_xp': '50',
    'referral_bonus_days': '7',
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
    """Return the stored value for *key*, or *default* if not found.

    On first access seeds the row with the default from SETTING_DEFAULTS so the
    value is visible in the admin UI immediately.  Flush only — caller commits.
    """
    session = db_session or db.session
    row = session.get(SiteSettings, key)
    if row is not None:
        return row.value

    # Seed from SETTING_DEFAULTS on first access
    seed_value = SETTING_DEFAULTS.get(key, default)
    if seed_value is not None:
        try:
            row = SiteSettings(
                key=key,
                value=str(seed_value) if seed_value is not None else '',
            )
            session.add(row)
            session.flush()
            return row.value
        except Exception:
            session.rollback()
            logger.warning('Could not seed site setting %r', key)

    return default if default is not None else (SETTING_DEFAULTS.get(key))


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


def ensure_defaults_seeded(db_session=None) -> None:
    """Create any missing default rows in site_settings.  Caller commits."""
    session = db_session or db.session
    for key, default_value in SETTING_DEFAULTS.items():
        existing = session.get(SiteSettings, key)
        if existing is None:
            session.add(SiteSettings(key=key, value=default_value))
    session.flush()
