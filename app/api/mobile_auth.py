"""Native account entry points. No browser session is created by these endpoints."""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError
from app import csrf, limiter
from app.api.native_lessons import private_response
from app.auth.models import User
from app.auth.mobile_models import (
    MobileAuthChallenge,
    MobileAuthThrottle,
    MobileAuthMail,
    utcnow,
)
from app.auth.mobile_mail import cipher, nudge_auth_mail
from app.utils.db import db
from app.utils.password_validator import validate_password_strength

mobile_auth = Blueprint("mobile_auth", __name__)
mobile_auth.after_request(private_response)


class AuthProblem(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


@mobile_auth.errorhandler(AuthProblem)
def problem(error):
    db.session.rollback()
    return jsonify(success=False, error=error.code, message=error.message), error.status


def body(keys):
    if request.content_length and request.content_length > 32000:
        raise AuthProblem("invalid_input", "Слишком большой запрос.", 413)
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - set(keys):
        raise AuthProblem("invalid_input", "Проверь заполненные поля.")
    return value


def text(value, limit, minimum=1):
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= limit
        or "\x00" in value
    ):
        raise AuthProblem("invalid_input", "Проверь заполненные поля.")
    return value


def email_address(value):
    try:
        value = validate_email(
            text(value, 120).strip(), check_deliverability=False, allow_smtputf8=False
        ).normalized.lower()
    except (EmailNotValidError, AuthProblem):
        raise AuthProblem("invalid_email", "Проверь адрес электронной почты.")
    if len(value) > 120:
        raise AuthProblem("invalid_email", "Адрес почты слишком длинный.")
    return value


def username(value):
    value = text(value, 64, 3).strip()
    if not re.fullmatch(r"[\w.-]{3,64}", value):
        raise AuthProblem(
            "invalid_username",
            "Имя: от 3 до 64 букв, цифр, точек, тире или подчёркиваний.",
        )
    return value


def password(value, name=None, email=None):
    value = text(value, 128, 8)
    valid, errors = validate_password_strength(value, username=name, email=email)
    if not valid:
        raise AuthProblem("weak_password", " ".join(errors))
    return value


def digest(value):
    return hmac.new(
        str(current_app.config["SECRET_KEY"]).encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def throttle(address=None, channel="email"):
    now = utcnow()
    identifiers = [(channel + ":ip:" + (request.remote_addr or "unknown"), 30, 0)]
    if address:
        identifiers.append((channel + ":email:" + address, 5, 60))
    for raw, limit, cooldown in sorted(identifiers):
        key = digest(raw)
        row = db.session.get(MobileAuthThrottle, key)
        if row is None:
            try:
                with db.session.begin_nested():
                    row = MobileAuthThrottle(
                        key=key, window_at=now, last_at=now - timedelta(days=1), count=0
                    )
                    db.session.add(row)
                    db.session.flush()
            except IntegrityError:
                pass
        row = MobileAuthThrottle.query.filter_by(key=key).with_for_update().one()
        if now - row.window_at >= timedelta(hours=1):
            row.window_at = now
            row.count = 0
        if row.count >= limit or (now - row.last_at).total_seconds() < cooldown:
            raise AuthProblem(
                "rate_limited", "Подожди немного перед новой попыткой.", 429
            )
        row.count += 1
        row.last_at = now


def make_challenge(kind, *, email=None, user_id=None, payload=None, minutes=10):
    now = utcnow()
    row = MobileAuthChallenge(
        id=secrets.token_urlsafe(32),
        kind=kind,
        email=email,
        user_id=user_id,
        payload=payload or {},
        created_at=now,
        expires_at=now + timedelta(minutes=minutes),
        attempts=0,
    )
    db.session.add(row)
    return row


def proof(identifier, kind):
    identifier = text(identifier, 64, 20)
    row = MobileAuthChallenge.query.filter_by(id=identifier).with_for_update().first()
    if (
        row is None
        or row.kind != kind
        or row.used_at
        or row.expires_at <= utcnow()
        or row.attempts >= 5
    ):
        raise AuthProblem(
            "challenge_expired", "Код больше не действует. Запроси новый."
        )
    return row


def check_code(row, value):
    value = text(value, 6, 6)
    if not value.isascii() or not value.isdigit():
        raise AuthProblem("invalid_code", "Введи шесть цифр из письма.")
    if not hmac.compare_digest(row.code_hash or "", digest(row.id + "|" + value)):
        row.attempts += 1
        db.session.commit()
        raise AuthProblem(
            "invalid_code", "Код не подошёл. Проверь письмо и попробуй ещё раз."
        )


def code_mail(row, deliver=True):
    code = f"{secrets.randbelow(1000000):06d}"
    row.code_hash = digest(row.id + "|" + code)
    if deliver:
        db.session.add(
            MobileAuthMail(
                challenge_id=row.id,
                email=row.email,
                encrypted_code=cipher().encrypt(code.encode()).decode(),
            )
        )


def find_email(address):
    return User.query.filter(func.lower(User.email) == address).first()


def response_for(user, provider=None):
    from app.utils.jwt_auth import create_tokens_for_user

    if not user.active:
        raise AuthProblem(
            "account_inactive", "Аккаунт недоступен. Обратись в поддержку.", 403
        )
    user.last_login = utcnow()
    return {
        "success": True,
        "status": "authenticated",
        **create_tokens_for_user(user),
        "user": {
            "id": user.id,
            "username": user.username,
            "is_admin": bool(user.is_admin),
        },
        "auth_provider": provider or "password",
    }


def create_user(name, address, encoded_password, level="A1"):
    from app.modules.models import UserModule
    from app.modules.service import ModuleService
    from app.auth.welcome_email import enqueue_welcome_email

    if User.query.filter(func.lower(User.username) == name.lower()).first():
        raise AuthProblem("username_taken", "Это имя уже занято. Выбери другое.", 409)
    if address and find_email(address):
        raise AuthProblem(
            "account_exists",
            "Этот адрес уже зарегистрирован. Войди в аккаунт или восстанови пароль.",
            409,
        )
    user = User(
        username=name,
        email=address,
        active=True,
        onboarding_completed=True,
        onboarding_level=level,
        onboarding_focus="all",
        daily_goal_minutes=15,
    )
    user.password_hash = encoded_password["password_hash"]
    user.salt = encoded_password["salt"]
    user.acquisition_meta = {
        "entry_point": "native_ios",
        "terms_accepted_at": utcnow().isoformat(),
        "method": encoded_password.get("method", "email"),
    }
    db.session.add(user)
    db.session.flush()
    for module in ModuleService.get_default_modules():
        db.session.add(
            UserModule(
                user_id=user.id,
                module_id=module.id,
                is_enabled=True,
                granted_by_admin=False,
            )
        )
    if address:
        enqueue_welcome_email(user)
    return user


@mobile_auth.get("/config")
def config():
    return jsonify(
        success=True,
        email_registration=True,
        apple=bool(
            current_app.config.get("MOBILE_APPLE_ENABLED")
            and current_app.config.get("MOBILE_APPLE_PRIVATE_KEY")
            and current_app.config.get("MOBILE_APPLE_TEAM_ID")
            and current_app.config.get("MOBILE_APPLE_KEY_ID")
        ),
        google=bool(
            current_app.config.get("MOBILE_GOOGLE_CLIENT_ID")
            and current_app.config.get("MOBILE_GOOGLE_CLIENT_SECRET")
        ),
    )


@mobile_auth.post("/register/start")
@csrf.exempt
@limiter.limit("20 per hour")
def register_start():
    data = body(["email", "username", "password", "terms_accepted", "level"])
    address = email_address(data.get("email"))
    name = username(data.get("username"))
    raw = password(data.get("password"), name, address)
    if data.get("terms_accepted") is not True:
        raise AuthProblem(
            "consent_required",
            "Чтобы создать аккаунт, прими политику конфиденциальности.",
        )
    level = data.get("level", "A1")
    if level not in ["A1", "A2", "B1", "B2", "C1"]:
        raise AuthProblem("invalid_level", "Выбери уровень английского.")
    if User.query.filter(func.lower(User.username) == name.lower()).first():
        raise AuthProblem("username_taken", "Это имя уже занято. Выбери другое.", 409)
    throttle(address)
    temporary = User(username=name, email=address)
    temporary.set_password(raw)
    row = make_challenge(
        "register",
        email=address,
        payload={
            "username": name,
            "password_hash": temporary.password_hash,
            "salt": temporary.salt,
            "level": level,
        },
    )
    code_mail(row)
    db.session.commit()
    nudge_auth_mail()
    return jsonify(success=True, challenge_id=row.id, expires_in=600, resend_after=60)


@mobile_auth.post("/register/verify")
@csrf.exempt
@limiter.limit("30 per minute")
def register_verify():
    data = body(["challenge_id", "code"])
    row = proof(data.get("challenge_id"), "register")
    check_code(row, data.get("code"))
    try:
        user = create_user(
            row.payload["username"],
            row.email,
            row.payload,
            row.payload.get("level", "A1"),
        )
        row.used_at = utcnow()
        row.payload = {}
        reply = response_for(user)
        db.session.commit()
        return jsonify(reply)
    except IntegrityError:
        db.session.rollback()
        raise AuthProblem(
            "account_exists", "Имя или почта уже используются. Попробуй войти.", 409
        )


@mobile_auth.post("/password/start")
@csrf.exempt
@limiter.limit("20 per hour")
def password_start():
    data = body(["email"])
    address = email_address(data.get("email"))
    throttle(address)
    user = find_email(address)
    row = make_challenge(
        "reset",
        email=address,
        user_id=user.id if user and user.active else None,
        payload={"auth_version": user.auth_version()} if user and user.active else {},
    )
    code_mail(row, deliver=bool(user and user.active))
    db.session.commit()
    nudge_auth_mail()
    return jsonify(success=True, challenge_id=row.id, expires_in=600, resend_after=60)


@mobile_auth.post("/password/verify")
@csrf.exempt
@limiter.limit("30 per minute")
def password_verify():
    data = body(["challenge_id", "code", "password"])
    raw = password(data.get("password"))
    row = proof(data.get("challenge_id"), "reset")
    check_code(row, data.get("code"))
    user = db.session.get(User, row.user_id) if row.user_id else None
    if (
        user is None
        or not user.active
        or not user.has_auth_version(row.payload.get("auth_version"))
    ):
        raise AuthProblem(
            "invalid_code", "Код не подошёл или больше не действует. Запроси новый."
        )
    password(raw, user.username, user.email)
    user.set_password(raw)
    row.used_at = utcnow()
    row.payload = {}
    # Password reset invalidates every earlier reset proof and auth_version rejects existing JWTs/cookies.
    MobileAuthChallenge.query.filter_by(
        user_id=user.id, kind="reset", used_at=None
    ).update({"used_at": utcnow()}, synchronize_session=False)
    db.session.commit()
    return jsonify(success=True, status="password_changed")


@mobile_auth.post("/code/resend")
@csrf.exempt
@limiter.limit("20 per hour")
def resend_code():
    data = body(["challenge_id"])
    identifier = text(data.get("challenge_id"), 64, 20)
    row = MobileAuthChallenge.query.filter_by(id=identifier).with_for_update().first()
    if (
        row is None
        or row.kind not in ["register", "reset"]
        or row.used_at
        or row.created_at < utcnow() - timedelta(hours=1)
    ):
        raise AuthProblem(
            "challenge_expired",
            "Запроси новый код с экрана регистрации или восстановления.",
        )
    throttle(row.email)
    row.used_at = utcnow()
    replacement = make_challenge(
        row.kind, email=row.email, user_id=row.user_id, payload=dict(row.payload)
    )
    code_mail(replacement, deliver=row.kind == "register" or row.user_id is not None)
    row.payload = {}
    db.session.commit()
    nudge_auth_mail()
    return jsonify(
        success=True, challenge_id=replacement.id, expires_in=600, resend_after=60
    )
