"""
Acquisition attribution middleware.

Captures first-touch UTM parameters and referrer into the Flask session
when an anonymous visitor lands on the site. At registration the auth
flow copies session['acq_meta'] into User.acquisition_meta for permanent
attribution.

First-touch policy: once captured, the session entry is never overwritten
by a later visit. This avoids losing the original source when a user
bounces between channels before signing up.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Flask, request, session

logger = logging.getLogger(__name__)

# Standard UTM keys (Google Analytics convention). Limited to these five
# to avoid trusting arbitrary query strings as attribution data.
_UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')

# Path prefixes that should never trigger UTM capture (assets, internal
# tracking pixels, API endpoints, etc.).
_SKIP_PREFIXES = ('/static/', '/api/', '/admin/', '/uploads/', '/sitemap.xml', '/robots.txt')

# Max length for any single captured value — defends against session bloat
# and pathological referrer strings.
_MAX_VALUE_LEN = 200


def _trim(value: str | None) -> str:
    """Strip and truncate a captured string; empty string if None/empty."""
    if not value:
        return ''
    return value.strip()[:_MAX_VALUE_LEN]


def add_acquisition_capture(app: Flask) -> None:
    """Register a before_request hook that snapshots UTM data once per session."""

    @app.before_request
    def capture_acquisition() -> None:
        # Cheap early-outs first.
        if request.method != 'GET':
            return
        path = request.path or ''
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return
        # First-touch only: never overwrite an existing entry.
        if session.get('acq_meta'):
            return

        utm = {key: _trim(request.args.get(key)) for key in _UTM_KEYS}
        has_utm = any(utm.values())
        referrer = _trim(request.referrer)

        # Skip capture when there is nothing to attribute: no UTM tags and
        # the referrer is empty or already on our own host (internal navigation).
        if not has_utm and not referrer:
            return
        host = (request.host or '').lower()
        if not has_utm and host and host in referrer.lower():
            return

        session['acq_meta'] = {
            **utm,
            'referrer': referrer,
            'landing_path': path,
            'captured_at_iso': datetime.now(timezone.utc).isoformat(),
        }

    app.logger.info("Acquisition capture middleware initialized")


def consume_acquisition_meta() -> dict | None:
    """Return the captured acquisition snapshot (or None) and clear the session key.

    Call this at the end of registration so the snapshot is persisted to the
    User row and the session no longer carries it. Removing the entry lets a
    returning anonymous visitor capture a fresh attribution for any future
    second account creation flow (rare, but cleaner).
    """
    meta = session.pop('acq_meta', None)
    if not meta:
        return None
    # Drop empty UTM keys so JSON stays compact.
    cleaned = {k: v for k, v in meta.items() if v}
    return cleaned or None
