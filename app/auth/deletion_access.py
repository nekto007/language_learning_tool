"""A confirmed deletion request pauses learning, never account management."""

from flask import jsonify, redirect, request, url_for
from flask_login import current_user

from app.auth.account_deletion import AccountDeletionRequest


def learning_suspended(user_id):
    return (
        AccountDeletionRequest.query.with_entities(AccountDeletionRequest.id)
        .filter_by(user_id=user_id, status="pending")
        .first()
        is not None
    )


def learning_enabled_user_filter():
    from app.auth.models import User
    from app.utils.db import db

    return (
        ~db.session.query(AccountDeletionRequest.id)
        .filter(AccountDeletionRequest.user_id == User.id, AccountDeletionRequest.status == "pending")
        .exists()
    )


def _management_endpoint():
    endpoint = request.endpoint or ""
    if request.method == "OPTIONS" or not endpoint:
        return True
    if endpoint == "static" or endpoint.endswith(".static"):
        return True
    if request.path == "/admin" or request.path.startswith("/admin/"):
        # This does not grant admin access: the normal admin/CSRF gates still run.
        return True
    if endpoint.startswith(
        ("auth.", "mobile_auth.", "legal.", "landing.", "health_check.", "feedback.", "notifications.")
    ):
        return True
    return request.path in {
        "/csrf-token",
        "/api/login",
        "/api/refresh",
        "/api/native/push/settings",
        "/api/native/push/devices",
        "/api/native/push/revoke",
    }


def deletion_access_guard():
    if _management_endpoint():
        return None
    users = {}
    if current_user.is_authenticated:
        users[current_user.id] = current_user
    if request.headers.get("Authorization", "").startswith("Bearer "):
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        from flask_jwt_extended.exceptions import JWTExtendedException
        from jwt import PyJWTError
        from app.auth.models import User

        try:
            verify_jwt_in_request()
            identifier = int(get_jwt_identity())
            if 0 < identifier <= 2147483647:
                user = User.query.filter_by(id=identifier).first()
                if user:
                    # This only denies learning; the endpoint still validates
                    # active/auth_version itself. Even old signed tokens cannot
                    # bypass the pause on a legacy JWT-only route.
                    users[user.id] = user
        except (JWTExtendedException, PyJWTError, ValueError, TypeError):
            # Invalid tokens still reach the endpoint's existing auth handler.
            # A valid cookie cannot bypass the policy by adding a bad token.
            pass
    if not any(learning_suspended(user_id) for user_id in users):
        return None
    if (
        request.path.startswith("/api/")
        or request.is_json
        or (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in request.headers.get("Accept", "")
        )
    ):
        response = jsonify(
            success=False,
            error="account_deletion_pending",
            message="Обучение приостановлено: аккаунт ожидает удаления. Отмени заявку, чтобы продолжить занятия.",
            status_url="/account-deletion",
        )
        response.status_code = 403
    else:
        response = redirect(url_for("auth.account_deletion"), code=303 if request.method != "GET" else 302)
    response.headers["Cache-Control"] = "private, no-store"
    return response
