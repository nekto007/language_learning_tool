"""Standardized API error response helper."""
from flask import jsonify


def api_error(code: str, message: str, status: int) -> tuple:
    """Return a standardized JSON error response.

    Args:
        code: Machine-readable error code (e.g. 'invalid_credentials').
        message: Human-readable description.
        status: HTTP status code.

    Returns:
        Tuple of (Response, status_code) ready for Flask to return.
    """
    return jsonify({'error': code, 'message': message, 'status': status}), status
