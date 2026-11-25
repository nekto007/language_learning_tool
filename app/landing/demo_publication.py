"""SiteSettings editions of the existing landing demonstrations."""

import json
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.admin.site_settings import SiteSettings, set_site_setting
from app.landing.previews import PREVIEWS_BY_ID
from app.public_copy import StalePublication, digest
from app.utils.db import db

logger = logging.getLogger(__name__)


def _setting_key(preview_id: str) -> str:
    return f'landing_demo.{preview_id}'


def _demo_snapshot(preview_id: str, raw: str | None) -> tuple[dict, str]:
    original = PREVIEWS_BY_ID[preview_id]
    if raw is None:
        return {**original, 'options': list(original['options'])}, digest(original)
    return {**json.loads(raw), 'id': preview_id}, digest(raw)


def published_demo(preview_id: str) -> tuple[dict, str]:
    """Read the latest edition of an existing demonstration by its stable ID."""
    raw = db.session.execute(
        db.select(SiteSettings.value).where(SiteSettings.key == _setting_key(preview_id)),
    ).scalar_one_or_none()
    return _demo_snapshot(preview_id, raw)


def demos_for_editing() -> list[dict]:
    keys = [_setting_key(preview_id) for preview_id in PREVIEWS_BY_ID]
    editions = dict(db.session.execute(
        db.select(SiteSettings.key, SiteSettings.value).where(SiteSettings.key.in_(keys)),
    ).all())
    return [_demo_snapshot(preview_id, editions.get(_setting_key(preview_id)))[0] for preview_id in PREVIEWS_BY_ID]


def demo_for_landing(preview_id: str) -> dict:
    try:
        return published_demo(preview_id)[0]
    except SQLAlchemyError:
        db.session.rollback()
        logger.warning('Cannot read landing demonstration %s; using default', preview_id)
        return PREVIEWS_BY_ID[preview_id]


def publish_demo(preview_id: str, document: dict, expected: str) -> bool:
    """Serialize publications per stable ID even before the first edition."""
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(db.text('SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))'), {
            'namespace': 624117032, 'key': _setting_key(preview_id),
        })
    current, revision = published_demo(preview_id)
    if revision != expected:
        raise StalePublication()
    if document == current:
        return False
    set_site_setting(_setting_key(preview_id), json.dumps(document, ensure_ascii=False, separators=(',', ':')))
    return True
