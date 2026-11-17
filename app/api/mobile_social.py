"""Provider-specific proofs; all app sessions use LLT's existing JWT/Keychain contract."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode
import jwt
import requests
from flask import current_app, jsonify, redirect, request
from sqlalchemy.exc import IntegrityError
from app import csrf, limiter
from app.api.mobile_auth import (
    AuthProblem,
    body,
    text,
    digest,
    throttle,
    make_challenge,
    proof,
    response_for,
    create_user,
    username,
    email_address,
)
from app.auth.models import User
from app.auth.mobile_models import MobileAuthChallenge, SocialIdentity, utcnow
from app.auth.mobile_mail import cipher
from app.utils.db import db

CALLBACK = "com.llt.english.ios://auth/callback"
_apple_keys = jwt.PyJWKClient(
    "https://appleid.apple.com/auth/keys", cache_jwk_set=True, lifespan=300, timeout=5
)
_google_keys = jwt.PyJWKClient(
    "https://www.googleapis.com/oauth2/v3/certs",
    cache_jwk_set=True,
    lifespan=300,
    timeout=5,
)


def _challenge(value):
    value = text(value, 128, 43)
    if not re.fullmatch("[A-Za-z0-9_-]{43}", value):
        raise AuthProblem("invalid_input", "Не получилось начать вход. Попробуй снова.")
    return value


def _pkce(value):
    value = text(value, 128, 43)
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", value):
        raise AuthProblem(
            "invalid_input", "Не получилось завершить вход. Попробуй снова."
        )
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def _post_json(url, form):
    try:
        response = requests.post(url, data=form, timeout=(5, 5), allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 64000:
            raise ValueError()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except Exception:
        raise AuthProblem(
            "social_unavailable",
            "Не получилось войти через этот сервис. Попробуй ещё раз.",
            503,
        ) from None


def _identity(token, provider, nonce):
    token = text(token, 20000, 20)
    audience = (
        current_app.config.get("MOBILE_APPLE_CLIENT_ID", "com.llt.english.ios")
        if provider == "apple"
        else current_app.config.get("MOBILE_GOOGLE_CLIENT_ID")
    )
    issuer = (
        "https://appleid.apple.com"
        if provider == "apple"
        else ["https://accounts.google.com", "accounts.google.com"]
    )
    keys = _apple_keys if provider == "apple" else _google_keys
    try:
        key = keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
            claims["nonce"], nonce
        ):
            raise ValueError()
        if claims["iat"] < time.time() - 660 or claims["exp"] > time.time() + 86400:
            raise ValueError()
        if claims.get("azp") and claims["azp"] != audience:
            raise ValueError()
        subject = text(claims.get("sub"), 256)
    except Exception:
        raise AuthProblem(
            "invalid_identity",
            "Подтверждение входа не подошло. Начни вход ещё раз.",
            401,
        ) from None
    address = None
    if claims.get("email") and claims.get("email_verified") in [True, "true"]:
        address = email_address(claims["email"])
    return {"provider": provider, "subject": subject, "email": address}


def _apple_secret():
    now = int(time.time())
    key = current_app.config.get("MOBILE_APPLE_PRIVATE_KEY", "").replace("\\n", "\n")
    try:
        return jwt.encode(
            {
                "iss": current_app.config["MOBILE_APPLE_TEAM_ID"],
                "iat": now,
                "exp": now + 300,
                "aud": "https://appleid.apple.com",
                "sub": current_app.config.get(
                    "MOBILE_APPLE_CLIENT_ID", "com.llt.english.ios"
                ),
            },
            key,
            algorithm="ES256",
            headers={"kid": current_app.config["MOBILE_APPLE_KEY_ID"]},
        )
    except Exception:
        raise AuthProblem(
            "social_unavailable", "Вход через Apple пока недоступен.", 503
        ) from None


def _resolve(identity):
    found = SocialIdentity.query.filter_by(
        provider=identity["provider"], subject=identity["subject"]
    ).first()
    if found:
        user = db.session.get(User, found.user_id)
        if user is None or not user.active:
            raise AuthProblem(
                "account_inactive", "Аккаунт недоступен. Обратись в поддержку.", 403
            )
        if identity.get("encrypted_refresh"):
            found.encrypted_refresh = identity["encrypted_refresh"]
        reply = response_for(user, identity["provider"])
        if identity["provider"] == "apple":
            reply["apple_subject"] = identity["subject"]
        return reply
    # A matching email does not silently attach a new login method to an existing account.
    from app.api.mobile_auth import find_email

    existing = find_email(identity["email"]) if identity.get("email") else None
    if existing and not existing.active:
        raise AuthProblem(
            "account_inactive", "Аккаунт недоступен. Обратись в поддержку.", 403
        )
    ticket = make_challenge(
        "social_link" if existing else "social_join",
        email=identity.get("email"),
        user_id=existing.id if existing else None,
        payload=identity,
        minutes=10,
    )
    return {
        "success": True,
        "status": "link_required" if existing else "profile_required",
        "ticket": ticket.id,
        "email": identity.get("email"),
    }


def _attach(user, identity):
    found = SocialIdentity.query.filter_by(
        provider=identity["provider"], subject=identity["subject"]
    ).first()
    if found and found.user_id != user.id:
        raise AuthProblem(
            "identity_in_use", "Этот способ входа уже связан с другим аккаунтом.", 409
        )
    if found is None:
        db.session.add(
            SocialIdentity(
                user_id=user.id,
                provider=identity["provider"],
                subject=identity["subject"],
                encrypted_refresh=identity.get("encrypted_refresh"),
            )
        )
    elif identity.get("encrypted_refresh"):
        found.encrypted_refresh = identity["encrypted_refresh"]


def _enabled(provider):
    if provider == "apple":
        return bool(
            current_app.config.get("MOBILE_APPLE_ENABLED")
            and all(
                current_app.config.get(k)
                for k in [
                    "MOBILE_APPLE_PRIVATE_KEY",
                    "MOBILE_APPLE_TEAM_ID",
                    "MOBILE_APPLE_KEY_ID",
                ]
            )
        )
    return bool(
        current_app.config.get("MOBILE_GOOGLE_CLIENT_ID")
        and current_app.config.get("MOBILE_GOOGLE_CLIENT_SECRET")
    )


_routes_registered = False


def register_social_routes(blueprint):
    global _routes_registered
    if _routes_registered:
        return
    _routes_registered = True
    blueprint.add_url_rule("/social/start", view_func=social_start, methods=["POST"])
    blueprint.add_url_rule(
        "/apple/complete", view_func=apple_complete, methods=["POST"]
    )
    blueprint.add_url_rule(
        "/google/callback", view_func=google_callback, methods=["GET"]
    )
    blueprint.add_url_rule(
        "/social/exchange", view_func=social_exchange, methods=["POST"]
    )
    blueprint.add_url_rule(
        "/social/profile", view_func=social_profile, methods=["POST"]
    )
    blueprint.add_url_rule("/social/link", view_func=social_link, methods=["POST"])


@csrf.exempt
@limiter.limit("30 per hour")
def social_start():
    data = body(["provider", "code_challenge", "state"])
    provider = data.get("provider")
    if provider not in ["apple", "google"]:
        raise AuthProblem("invalid_provider", "Этот способ входа пока недоступен.")
    if not _enabled(provider):
        raise AuthProblem(
            "social_unavailable", "Этот способ входа пока недоступен.", 503
        )
    challenge = _challenge(data.get("code_challenge"))
    state = _challenge(data.get("state"))
    throttle(channel="social")
    nonce = secrets.token_urlsafe(32)
    row = make_challenge(
        "social_" + provider,
        payload={"pkce": challenge, "state": state, "nonce": nonce},
    )
    result = {
        "success": True,
        "challenge_id": row.id,
        "nonce": nonce,
        "expires_in": 600,
    }
    if provider == "google":
        redirect_uri = current_app.config.get(
            "MOBILE_GOOGLE_REDIRECT_URI",
            "https://llt-english.com/api/mobile/auth/google/callback",
        )
        result["authorization_url"] = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urlencode(
                {
                    "client_id": current_app.config["MOBILE_GOOGLE_CLIENT_ID"],
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": row.id,
                    "nonce": nonce,
                    "prompt": "select_account",
                }
            )
        )
    db.session.commit()
    return jsonify(result)


@csrf.exempt
@limiter.limit("30 per minute")
def apple_complete():
    if not _enabled("apple"):
        raise AuthProblem(
            "social_unavailable", "Вход через Apple пока недоступен.", 503
        )
    data = body(
        ["challenge_id", "identity_token", "authorization_code", "code_verifier"]
    )
    row = proof(data.get("challenge_id"), "social_apple")
    if not hmac.compare_digest(_pkce(data.get("code_verifier")), row.payload["pkce"]):
        raise AuthProblem("invalid_identity", "Начни вход ещё раз.", 401)
    identity = _identity(data.get("identity_token"), "apple", row.payload["nonce"])
    code = text(data.get("authorization_code"), 2048, 10)
    grant = _post_json(
        "https://appleid.apple.com/auth/token",
        {
            "client_id": current_app.config.get(
                "MOBILE_APPLE_CLIENT_ID", "com.llt.english.ios"
            ),
            "client_secret": _apple_secret(),
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    verified = _identity(grant.get("id_token"), "apple", row.payload["nonce"])
    if verified["subject"] != identity["subject"]:
        raise AuthProblem("invalid_identity", "Начни вход ещё раз.", 401)
    if grant.get("refresh_token"):
        identity["encrypted_refresh"] = (
            cipher().encrypt(text(grant["refresh_token"], 10000).encode()).decode()
        )
    row.used_at = utcnow()
    row.payload = {}
    reply = _resolve(identity)
    db.session.commit()
    return jsonify(reply)


@limiter.limit("60 per minute")
def google_callback():
    # Only a server-issued state is accepted, never a callback URL supplied by a client.
    row = proof(request.args.get("state"), "social_google")
    state = row.payload["state"]
    if request.args.get("error"):
        row.used_at = utcnow()
        row.payload = {}
        db.session.commit()
        return redirect(
            CALLBACK + "?" + urlencode({"error": "cancelled", "state": state}), code=303
        )
    code = text(request.args.get("code"), 4096, 10)
    payload = dict(row.payload)
    row.used_at = utcnow()
    row.payload = {}
    db.session.commit()
    try:
        grant = _post_json(
            "https://oauth2.googleapis.com/token",
            {
                "code": code,
                "client_id": current_app.config["MOBILE_GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["MOBILE_GOOGLE_CLIENT_SECRET"],
                "redirect_uri": current_app.config.get(
                    "MOBILE_GOOGLE_REDIRECT_URI",
                    "https://llt-english.com/api/mobile/auth/google/callback",
                ),
                "grant_type": "authorization_code",
            },
        )
        identity = _identity(grant.get("id_token"), "google", payload["nonce"])
        exchange_code = secrets.token_urlsafe(32)
        exchange = make_challenge(
            "social_exchange",
            payload={"identity": identity, "pkce": payload["pkce"]},
            minutes=2,
        )
        exchange.code_hash = digest(exchange_code)
        db.session.commit()
        return redirect(
            CALLBACK
            + "?"
            + urlencode(
                {"challenge_id": exchange.id, "code": exchange_code, "state": state}
            ),
            code=303,
        )
    except AuthProblem:
        db.session.rollback()
        return redirect(
            CALLBACK + "?" + urlencode({"error": "unavailable", "state": state}),
            code=303,
        )


@csrf.exempt
@limiter.limit("30 per minute")
def social_exchange():
    data = body(["challenge_id", "code", "code_verifier"])
    row = proof(data.get("challenge_id"), "social_exchange")
    if not hmac.compare_digest(
        digest(text(data.get("code"), 64, 20)), row.code_hash or ""
    ) or not hmac.compare_digest(_pkce(data.get("code_verifier")), row.payload["pkce"]):
        row.attempts += 1
        db.session.commit()
        raise AuthProblem("invalid_identity", "Начни вход ещё раз.", 401)
    reply = _resolve(row.payload["identity"])
    row.used_at = utcnow()
    row.payload = {}
    db.session.commit()
    return jsonify(reply)


@csrf.exempt
@limiter.limit("20 per hour")
def social_profile():
    data = body(["ticket", "username", "level", "terms_accepted"])
    row = proof(data.get("ticket"), "social_join")
    name = username(data.get("username"))
    level = data.get("level", "A1")
    if level not in ["A1", "A2", "B1", "B2", "C1"]:
        raise AuthProblem("invalid_level", "Выбери уровень английского.")
    if data.get("terms_accepted") is not True:
        raise AuthProblem("consent_required", "Прими политику конфиденциальности.")
    temporary = User()
    temporary.set_password(secrets.token_urlsafe(64))
    identity = row.payload
    try:
        user = create_user(
            name,
            row.email,
            {
                "password_hash": temporary.password_hash,
                "salt": temporary.salt,
                "method": identity["provider"],
            },
            level,
        )
        _attach(user, identity)
        row.used_at = utcnow()
        row.payload = {}
        reply = response_for(user, identity["provider"])
        if identity["provider"] == "apple":
            reply["apple_subject"] = identity["subject"]
        db.session.commit()
        return jsonify(reply)
    except IntegrityError:
        db.session.rollback()
        raise AuthProblem(
            "account_exists", "Имя или почта уже используются. Попробуй войти.", 409
        )


@csrf.exempt
@limiter.limit("20 per hour")
def social_link():
    data = body(["ticket", "password"])
    row = proof(data.get("ticket"), "social_link")
    raw = text(data.get("password"), 128)
    user = db.session.get(User, row.user_id)
    if user is None or not user.active:
        raise AuthProblem("account_inactive", "Аккаунт недоступен.", 403)
    if not user.check_password(raw):
        row.attempts += 1
        db.session.commit()
        raise AuthProblem(
            "invalid_credentials",
            "Пароль не подошёл. Проверь пароль от аккаунта LLT.",
            401,
        )
    identity = row.payload
    try:
        _attach(user, identity)
        row.used_at = utcnow()
        row.payload = {}
        reply = response_for(user, identity["provider"])
        if identity["provider"] == "apple":
            reply["apple_subject"] = identity["subject"]
        db.session.commit()
        return jsonify(reply)
    except IntegrityError:
        db.session.rollback()
        raise AuthProblem(
            "identity_in_use",
            "Этот способ входа уже связан с аккаунтом. Начни вход ещё раз.",
            409,
        )
