"""
Request ID middleware for Flask application.
Assigns a unique UUID to each request via g.request_id and
exposes it as an X-Request-ID response header.
"""
import logging
from uuid import uuid4

from flask import Flask, g

logger = logging.getLogger(__name__)


def add_request_id(app: Flask) -> None:
    """Register before/after request hooks that manage per-request IDs."""

    @app.before_request
    def set_request_id() -> None:
        g.request_id = uuid4().hex

    @app.after_request
    def attach_request_id_header(response):
        request_id = getattr(g, 'request_id', None)
        if request_id:
            response.headers['X-Request-ID'] = request_id
        return response

    app.logger.info("Request ID middleware initialized")
