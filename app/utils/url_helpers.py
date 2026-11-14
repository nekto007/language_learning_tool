"""Canonical origins for emailed security links; never take them from Host."""
import logging
from urllib.parse import urlsplit

from flask import current_app, url_for

logger = logging.getLogger(__name__)
_DEFAULT_ORIGIN = 'https://llt-english.com'


def canonical_external_url(endpoint, **values):
    configured = current_app.config.get('SITE_URL') or _DEFAULT_ORIGIN
    if not isinstance(configured, str):
        logger.error('SITE_URL must be a string; using the canonical default origin')
        configured = _DEFAULT_ORIGIN
    try:
        parsed = urlsplit(configured)
        valid = (parsed.scheme in {'https', 'http'} and parsed.hostname
                 and not parsed.username and not parsed.password)
        origin = f'{parsed.scheme}://{parsed.netloc}' if valid else _DEFAULT_ORIGIN
    except (ValueError, TypeError):
        origin = _DEFAULT_ORIGIN
    if origin == _DEFAULT_ORIGIN and configured != _DEFAULT_ORIGIN:
        logger.error('Invalid SITE_URL; security email uses the canonical default origin')
    return origin + url_for(endpoint, _external=False, **values)
