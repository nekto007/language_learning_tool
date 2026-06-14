"""
Request ID middleware for Flask application.
Assigns a unique UUID to each request via g.request_id and
exposes it as an X-Request-ID response header.

Accepts an incoming X-Request-ID header if it is a valid 32-char hex string
(uuid4().hex format); otherwise generates a fresh ID. Validates incoming
values to prevent header-injection attacks.
"""
import logging
import re
from uuid import uuid4

from flask import Flask, g
from flask import request as flask_request

logger = logging.getLogger(__name__)

# Case-insensitive so a valid 32-char uppercase X-Request-ID from an upstream
# proxy is preserved rather than discarded, keeping cross-service traces linked
# (audit E-085). CR/LF/':' still can't pass, so header injection stays blocked.
_HEX32_RE = re.compile(r'^[0-9a-f]{32}$', re.IGNORECASE)


class RequestIdFilter(logging.Filter):
    """Inject g.request_id into every log record emitted during a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g as flask_g
            record.request_id = getattr(flask_g, 'request_id', '-')
        except RuntimeError:
            # Outside application context (startup, background tasks)
            record.request_id = '-'
        return True


def add_request_id(app: Flask) -> None:
    """Register before/after request hooks that manage per-request IDs."""

    # Attach the filter to all root logger handlers so g.request_id is
    # available as %(request_id)s in every log record emitted during a request.
    _filter = RequestIdFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(_filter)
    # Also add to any handler attached after this point via app.logger
    if not any(isinstance(f, RequestIdFilter) for f in app.logger.filters):
        app.logger.addFilter(_filter)

    @app.before_request
    def set_request_id() -> None:
        incoming = flask_request.headers.get('X-Request-ID', '')
        if incoming and _HEX32_RE.match(incoming):
            g.request_id = incoming
        else:
            g.request_id = uuid4().hex

    @app.after_request
    def attach_request_id_header(response):
        request_id = getattr(g, 'request_id', None)
        if request_id:
            response.headers['X-Request-ID'] = request_id
        return response

    app.logger.info("Request ID middleware initialized")
