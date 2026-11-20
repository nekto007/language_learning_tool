"""Revoke delegated learning sessions centrally, including legacy JWT routes."""
import time

from flask import jsonify, request
from flask_jwt_extended import decode_token
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt import PyJWTError

from app.family.models import FamilyLink
from app.family.service import valid_link
from app.utils.db import db


def delegated_link(claims):
    identifier = claims.get("family_link")
    if not isinstance(identifier, str) or len(identifier) != 32:
        return None
    link = db.session.get(FamilyLink, identifier)
    if (not valid_link(link) or str(link.child_id) != claims.get("sub")
            or link.parent_id != claims.get("family_parent_id")):
        return None
    return link


def family_session_guard():
    raw = request.headers.get("Authorization", "")
    if not raw.startswith("Bearer "):
        return None
    try:
        # Expired tokens still cannot be used to create a browser session on an
        # unprotected auth route. Normal tokens retain existing error handling.
        claims = decode_token(raw[7:], allow_expired=True)
    except (JWTExtendedException, PyJWTError, ValueError, TypeError):
        return None
    if "family_link" not in claims:
        return None
    if claims.get("exp", 0) <= time.time() or not delegated_link(claims):
        response = jsonify(success=False, error="family_session_expired",
                           message="Семейный доступ завершён. Вернись в родительский аккаунт.")
        response.status_code = 401
    else:
        path = request.path
        allowed = (
            (path == "/api/refresh" and request.method == "POST")
            or (path == "/api/family/session" and request.method == "GET")
            or any(path == prefix or path.startswith(prefix + "/") for prefix in (
                "/api/native/books", "/api/native/reading", "/api/native/lessons", "/api/native/courses",
                "/api/native/modules", "/api/native/grammar", "/api/native/activities", "/api/native/srs",
                "/api/native/reader", "/api/native/vocabulary", "/api/books", "/api/words", "/api/daily-plan"))
            or (path in ("/api/daily-status", "/api/xp-leaderboard") and request.method == "GET")
        )
        if allowed:
            return None
        response = jsonify(success=False, error="family_session_restricted",
                           message="Это действие доступно только при обычном входе в аккаунт.")
        response.status_code = 403
    response.headers["Cache-Control"] = "private, no-store"
    return response
