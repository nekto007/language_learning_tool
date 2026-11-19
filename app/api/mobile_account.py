"""Reverified requests for manual admin review; this API never deletes users."""
from datetime import timedelta
import hmac
from flask import jsonify
from flask_login import current_user
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.mobile_auth import (
    AuthProblem, body, check_code, code_mail, digest, make_challenge, proof, text, throttle,
)
from app.auth.mobile_mail import nudge_auth_mail
from app.auth.mobile_models import MobileAuthChallenge, utcnow
from app.auth.models import User
from app.utils.db import db


def _user():
    return User.query.filter_by(id=current_user.id, active=True).with_for_update().one()


@csrf.exempt
@api_bearer_required
@limiter.limit("10 per minute")
def deletion_start():
    body([])
    return jsonify(start_verification(_user()))


def start_verification(user):
    from app.auth.account_deletion import AccountDeletionRequest
    throttle("account:" + str(user.id), channel="account_deletion")
    MobileAuthChallenge.query.filter_by(user_id=user.id, kind="account_deletion").filter(
        MobileAuthChallenge.used_at.is_(None)
    ).update({"used_at": utcnow(), "payload": {}}, synchronize_session=False)
    method = "email_code" if user.email and "@" in user.email else "password"
    pending = AccountDeletionRequest.query.filter_by(user_id=user.id).first()
    binding = (pending.id + "|" + pending.reconfirmation_requested_at.isoformat()
        if pending and pending.status == "pending" and pending.requires_reconfirmation else None)
    row = make_challenge("account_deletion", email=user.email, user_id=user.id,
        payload={"auth_version": user.auth_version(), "method": method, "reconfirmation_for": binding})
    if method == "email_code":
        code_mail(row)
    db.session.commit()
    if method == "email_code":
        nudge_auth_mail()
    hint = None
    if method == "email_code":
        local, domain = user.email.rsplit("@", 1)
        hint = local[:1] + "***@" + domain
    return dict(success=True, challenge_id=row.id, verification=method,
        email_hint=hint, expires_in=600, resend_after=60)


@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute")
def deletion_confirm():
    data = body(["challenge_id", "code", "password", "confirm"])
    pending = confirm_request(_user(), data)
    return jsonify(success=True, status="pending_admin_review", request=pending.response(tracking=True))


def confirm_request(user, data):
    if data.get("confirm") is not True:
        raise AuthProblem("confirmation_required", "Подтверди отправку заявки на удаление.")
    row = proof(data.get("challenge_id"), "account_deletion")
    if row.user_id != user.id or not hmac.compare_digest(
        row.payload.get("auth_version", ""), user.auth_version()
    ):
        raise AuthProblem("challenge_expired", "Запроси подтверждение удаления заново.")
    from app.auth.account_deletion import AccountDeletionRequest
    pending = AccountDeletionRequest.query.filter_by(user_id=user.id).with_for_update(of=AccountDeletionRequest).first()
    if pending and pending.status == "pending" and pending.requires_reconfirmation:
        binding = pending.id + "|" + pending.reconfirmation_requested_at.isoformat()
        if row.payload.get("reconfirmation_for") != binding:
            raise AuthProblem("challenge_expired", "Для проверки администратора запроси новый код подтверждения.")
    if row.payload.get("method") == "email_code":
        check_code(row, data.get("code"))
    elif row.payload.get("method") == "password":
        password = text(data.get("password"), 128)
        if not user.check_password(password):
            row.attempts += 1
            db.session.commit()
            raise AuthProblem("invalid_verification", "Пароль не подошёл. Попробуй ещё раз.")
    else:
        raise AuthProblem("challenge_expired", "Запроси подтверждение удаления заново.")
    if pending is None:
        pending = AccountDeletionRequest(user_id=user.id)
        db.session.add(pending)
    if pending.status != "pending" or pending.id is None:
        import secrets
        pending.id = secrets.token_urlsafe(32)
        pending.requested_at = utcnow()
        pending.earliest_deletion_at = pending.requested_at + timedelta(days=7)
        pending.latest_deletion_at = pending.requested_at + timedelta(days=14)
        pending.admin_notice_after = pending.requested_at
        pending.cancelled_at = None
        pending.completed_at = None
        pending.reviewed_by = None
        pending.status = "pending"
        pending.requires_reconfirmation = False
        pending.reconfirmation_reason = None
        pending.reconfirmation_requested_at = None
        pending.record("requested")
    elif pending.requires_reconfirmation:
        pending.requires_reconfirmation = False
        pending.admin_notice_after = utcnow()
        pending.record("reconfirmed")
    row.used_at = utcnow()
    row.payload = {}
    db.session.commit()
    return pending


@api_bearer_required
def deletion_current():
    from app.auth.account_deletion import AccountDeletionRequest
    row = AccountDeletionRequest.query.filter_by(user_id=current_user.id).first()
    return jsonify(success=True, request=row.response(tracking=True) if row else None)


@csrf.exempt
@api_bearer_required
@limiter.limit("10 per minute")
def deletion_cancel():
    data = body(["request_id"])
    row = cancel_request(_user(), data.get("request_id"))
    return jsonify(success=True, request=row.response(tracking=True))


def cancel_request(user, identifier):
    from app.auth.account_deletion import AccountDeletionRequest, AccountDeletionMail
    row = AccountDeletionRequest.query.filter_by(id=text(identifier,64,20),user_id=user.id).with_for_update(of=AccountDeletionRequest).first()
    if row is None:
        raise AuthProblem("not_found", "Заявка не найдена.", 404)
    if row.status == "pending":
        row.status = "cancelled"
        row.cancelled_at = utcnow()
        row.requires_reconfirmation = False
        row.record("cancelled")
        # No stale verification mail/FK may survive an immediate new request.
        AccountDeletionMail.query.filter_by(request_id=row.id, purpose="reconfirmation").delete(synchronize_session=False)
        MobileAuthChallenge.query.filter_by(user_id=user.id, kind="account_deletion").filter(
            MobileAuthChallenge.used_at.is_(None)
        ).update({"used_at": utcnow(), "payload": {}}, synchronize_session=False)
        db.session.commit()
    return row


@csrf.exempt
@limiter.limit("60 per minute")
def deletion_status():
    from app.auth.account_deletion import AccountDeletionRequest
    data = body(["request_id", "tracking_token"])
    identifier = text(data.get("request_id"),64,20)
    token = text(data.get("tracking_token"),64,64)
    if not hmac.compare_digest(digest("account-deletion-status|" + identifier),token):
        raise AuthProblem("not_found", "Заявка не найдена.", 404)
    row = db.session.get(AccountDeletionRequest,identifier)
    if row is None:
        raise AuthProblem("not_found", "Заявка не найдена.", 404)
    return jsonify(success=True, request=row.response())


def register_account_routes(blueprint):
    if getattr(blueprint, "_account_registered", False):
        return
    blueprint._account_registered = True
    blueprint.add_url_rule("/account/deletion/start", view_func=deletion_start, methods=["POST"])
    blueprint.add_url_rule("/account/deletion/confirm", view_func=deletion_confirm, methods=["POST"])
    blueprint.add_url_rule("/account/deletion/current", view_func=deletion_current, methods=["GET"])
    blueprint.add_url_rule("/account/deletion/cancel", view_func=deletion_cancel, methods=["POST"])
    blueprint.add_url_rule("/account/deletion/status", view_func=deletion_status, methods=["POST"])
