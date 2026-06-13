"""Health check blueprint — exposes GET /health for uptime monitoring."""
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from app.utils.db import db

logger = logging.getLogger(__name__)

health_bp = Blueprint('health_check', __name__)

# Maximum milliseconds to wait for the DB ping before declaring it unavailable.
_DB_TIMEOUT_MS = 3000


@health_bp.route('/health', methods=['GET'])
def health():
    """Return service health status.

    Returns 200 ``{'status': 'ok', 'db': 'ok', 'version': ..., 'timestamp': ...}``
    when the database is reachable within _DB_TIMEOUT_MS, or
    503 ``{'status': 'error', 'db': 'error', ...}`` otherwise.

    This endpoint must never require authentication and must never block
    longer than _DB_TIMEOUT_MS (uses PostgreSQL statement_timeout).
    """
    db_status = 'ok'
    http_status = 200
    try:
        # Use a dedicated connection with an explicit transaction so
        # SET LOCAL statement_timeout actually scopes the SELECT (under the
        # codebase's AUTOCOMMIT isolation, SET LOCAL on the shared session
        # would apply to only that one statement). A fresh connection also
        # keeps a DB failure from leaving the request-scoped db.session in an
        # aborted state for the next request on this connection (audit E-083).
        with db.engine.connect() as conn:
            with conn.begin():
                conn.execute(db.text('SET LOCAL statement_timeout = ' + str(_DB_TIMEOUT_MS)))
                conn.execute(db.text('SELECT 1'))
    except Exception:
        logger.exception('Health check: database connectivity failure')
        db_status = 'error'
        http_status = 503

    payload = {
        'status': 'ok' if db_status == 'ok' else 'error',
        'db': db_status,
        'version': current_app.config.get('APP_VERSION', '1.0.0'),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(payload), http_status
