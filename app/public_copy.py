"""Published overrides for public pages rendered from the existing templates."""

import json
import logging
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.admin.site_settings import SiteSettings, set_site_setting
from app.public_copy_markup import apply_copy, digest
from app.utils.db import db

PAGES = {
    'home': ('Главная и FAQ', 'landing.index'),
    'support': ('Поддержка', 'legal.mobile_support'),
    'privacy': ('Политика конфиденциальности', 'legal.privacy'),
}
MAX_FAQ = 24
TEXT_LIMIT = 2000
QUESTION_LIMIT = 250
_LOCK_NAMESPACE = 624117031
logger = logging.getLogger(__name__)


class StalePublication(Exception):
    """The published version changed since this draft was prepared."""


def _key(page: str) -> str:
    return f'public_copy.{page}'


def _read_override(page: str) -> str | None:
    return db.session.execute(db.select(SiteSettings.value).where(SiteSettings.key == _key(page))).scalar_one_or_none()


def published_copy(page: str, defaults: dict) -> tuple[dict, str]:
    raw = _read_override(page)
    stored = json.loads(raw) if raw is not None else {}
    current = {**defaults, 'text': {key: stored.get('text', {}).get(key, value)
                                    for key, value in defaults['text'].items()}}
    if page == 'home':
        current['faq'] = stored.get('faq', defaults['faq'])
    return current, digest([raw, defaults])


def copy_for_public_view(page: str, original: str) -> str:
    """Serve the original HTML on the fast path, including a failed settings read."""
    try:
        raw = _read_override(page)
    except SQLAlchemyError:
        db.session.rollback()
        logger.warning('Cannot read published copy for %s; using original render', page)
        return original
    if raw is None:
        return original
    try:
        overrides = json.loads(raw)
        if not overrides['text'] and 'faq' not in overrides:
            return original
        return apply_copy(page, original, overrides)
    except (KeyError, TypeError, ValueError):
        logger.warning('Published copy layout mismatch on %s; using original render', page)
        return original


def field_limit(key: str) -> int:
    if key in ('seo.title', 'seo.og_title'):
        return 160
    if key in ('seo.description', 'seo.og_description'):
        return 320
    return TEXT_LIMIT


def publish_copy(page: str, document: dict, expected: str, defaults: dict) -> bool:
    """Serialize writers for one page, including its first publication."""
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(db.text('SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))'), {
            'namespace': _LOCK_NAMESPACE, 'key': _key(page),
        })
    current, revision = published_copy(page, defaults)
    if revision != expected:
        raise StalePublication()
    if document == current:
        return False
    raw = _read_override(page)
    stored = json.loads(raw) if raw is not None else {}
    text = {key: value for key, value in stored.get('text', {}).items() if key not in defaults['text']}
    text.update({key: value for key, value in document['text'].items() if value != defaults['text'][key]})
    base = {key: value for key, value in stored.get('base', {}).items() if key in text and key not in defaults['text']}
    base.update({key: digest(defaults['text'][key]) for key in text if key in defaults['text']})
    patches = {'text': text, 'base': base, 'revision': uuid4().hex}
    if page == 'home' and document['faq'] != defaults['faq']:
        patches['faq'] = document['faq']
        base['faq'] = digest(defaults['faq'])
    set_site_setting(_key(page), json.dumps(patches, ensure_ascii=False, separators=(',', ':')))
    return True
