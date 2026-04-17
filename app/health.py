"""Health check blueprint — exposes GET /health for uptime monitoring."""
import logging

from flask import Blueprint, jsonify

from app.utils.db import db

logger = logging.getLogger(__name__)

health_bp = Blueprint('health_check', __name__)


@health_bp.route('/health', methods=['GET'])
def health():
    """Return service health status.

    Returns 200 ``{'status': 'ok', 'db': 'ok'}`` when the database is
    reachable, or 503 ``{'status': 'error', 'db': 'error'}`` otherwise.
    """
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok', 'db': 'ok'}), 200
    except Exception:
        logger.exception('Health check: database connectivity failure')
        return jsonify({'status': 'error', 'db': 'error'}), 503
