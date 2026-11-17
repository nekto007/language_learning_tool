from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse, parse_qs
import base64, hashlib, secrets, time
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from test_native_full_integration import native_app, learner

PREFIX = "/api/mobile/auth"
PASSWORD = "River!Mango64"


@pytest.fixture(autouse=True)
def reset_disposable_throttles(native_app):
    from app.auth.mobile_models import MobileAuthThrottle
    from app.utils.db import db

    MobileAuthThrottle.query.delete()
    db.session.commit()


def address():
    return "native" + uuid4().hex[:12] + "@example.com"


def start(client, **extra):
    value = dict(
        username="learner" + uuid4().hex[:10],
        email=address(),
        password=PASSWORD,
        terms_accepted=True,
        level="A2",
    )
    value.update(extra)
    response = client.post(PREFIX + "/register/start", json=value)
    assert response.status_code == 200, response.json
    return response.json, value


def code(identifier):
    from app.auth.mobile_models import MobileAuthMail
    from app.auth.mobile_mail import cipher

    mail = MobileAuthMail.query.filter_by(challenge_id=identifier).one()
    return cipher().decrypt(mail.encrypted_code.encode()).decode()


def test_native_signup_creates_account_only_after_email_proof(native_app):
    from app.auth.models import User
    from app.auth.mobile_models import MobileAuthChallenge
    from app.modules.models import SystemModule, UserModule
    from app.utils.db import db

    module = SystemModule(
        code="native-default-" + uuid4().hex[:8],
        name="Test",
        is_default=True,
        is_active=True,
    )
    db.session.add(module)
    db.session.commit()
    client = native_app.test_client()
    proof, values = start(client)
    assert User.query.filter_by(email=values["email"]).first() is None
    pending = db.session.get(MobileAuthChallenge, proof["challenge_id"])
    assert PASSWORD not in str(pending.payload)
    response = client.post(
        PREFIX + "/register/verify",
        json={"challenge_id": pending.id, "code": code(pending.id)},
    )
    assert response.status_code == 200, response.json
    user = User.query.filter_by(email=values["email"]).one()
    assert (
        user.check_password(PASSWORD)
        and user.onboarding_completed
        and user.onboarding_level == "A2"
    )
    assert UserModule.query.filter_by(
        user_id=user.id, module_id=module.id, is_enabled=True
    ).one()
    assert response.json["user"]["id"] == user.id and response.json["refresh_token"]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert (
        client.post(
            PREFIX + "/register/verify",
            json={"challenge_id": pending.id, "code": "000000"},
        ).status_code
        == 400
    )
    assert User.query.filter_by(email=values["email"]).count() == 1


def test_weak_password_missing_consent_and_malformed_input_do_not_create_proof(
    native_app,
):
    from app.auth.mobile_models import MobileAuthChallenge

    client = native_app.test_client()
    before = MobileAuthChallenge.query.count()
    base = dict(
        username="learner" + uuid4().hex[:8],
        email=address(),
        password=PASSWORD,
        terms_accepted=True,
    )
    for change in [
        {"password": "password123"},
        {"terms_accepted": False},
        {"terms_accepted": 1},
        {"email": "invalid"},
        {"username": "<script>"},
        {"unexpected": "value"},
    ]:
        value = {**base, **change}
        assert client.post(PREFIX + "/register/start", json=value).status_code == 400
    assert MobileAuthChallenge.query.count() == before


def test_wrong_code_attempts_persist_and_lock_after_five(native_app):
    from app.auth.mobile_models import MobileAuthChallenge

    client = native_app.test_client()
    proof, _ = start(client)
    right = code(proof["challenge_id"])
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post(
                PREFIX + "/register/verify",
                json={"challenge_id": proof["challenge_id"], "code": wrong},
            ).status_code
            == 400
        )
    assert (
        client.post(
            PREFIX + "/register/verify",
            json={"challenge_id": proof["challenge_id"], "code": right},
        ).status_code
        == 400
    )
    assert MobileAuthChallenge.query.get(proof["challenge_id"]).attempts == 5


def test_resend_has_durable_cooldown_replaces_proof_and_preserves_registration(
    native_app,
):
    from app.auth.mobile_models import MobileAuthChallenge, MobileAuthThrottle, utcnow
    from app.utils.db import db

    client = native_app.test_client()
    proof, values = start(client)
    assert (
        client.post(
            PREFIX + "/code/resend", json={"challenge_id": proof["challenge_id"]}
        ).status_code
        == 429
    )
    for item in MobileAuthThrottle.query.all():
        item.last_at = utcnow() - timedelta(seconds=61)
    db.session.commit()
    replacement = client.post(
        PREFIX + "/code/resend", json={"challenge_id": proof["challenge_id"]}
    )
    assert replacement.status_code == 200, replacement.json
    assert db.session.get(MobileAuthChallenge, proof["challenge_id"]).used_at
    final = client.post(
        PREFIX + "/register/verify",
        json={
            "challenge_id": replacement.json["challenge_id"],
            "code": code(replacement.json["challenge_id"]),
        },
    )
    assert final.status_code == 200, final.json
    assert final.json["user"]["username"] == values["username"]


def test_reset_is_neutral_and_revokes_existing_sessions(native_app):
    from app.auth.models import User
    from app.auth.mobile_models import MobileAuthChallenge, MobileAuthMail
    from app.utils.db import db

    user, headers = learner(native_app)
    user.email = address()
    db.session.commit()
    client = native_app.test_client()
    old_version = user.auth_version()
    known = client.post(PREFIX + "/password/start", json={"email": user.email})
    unknown = client.post(PREFIX + "/password/start", json={"email": address()})
    assert known.status_code == unknown.status_code == 200
    assert known.json.keys() == unknown.json.keys()
    assert (
        MobileAuthMail.query.filter_by(
            challenge_id=unknown.json["challenge_id"]
        ).count()
        == 0
    )
    new = "Orange!Lake73"
    result = client.post(
        PREFIX + "/password/verify",
        json={
            "challenge_id": known.json["challenge_id"],
            "code": code(known.json["challenge_id"]),
            "password": new,
        },
    )
    assert result.status_code == 200, result.json
    db.session.refresh(user)
    assert user.check_password(new) and user.auth_version() != old_version
    assert client.get("/api/daily-status", headers=headers).status_code == 401
    assert (
        client.post(
            PREFIX + "/password/verify",
            json={
                "challenge_id": known.json["challenge_id"],
                "code": "000000",
                "password": new,
            },
        ).status_code
        == 400
    )
    login = client.post(
        "/api/login", json={"username": user.email.upper(), "password": new}
    )
    assert login.status_code == 200, login.json
    assert login.json["user"]["username"] == user.username


def test_expired_proofs_cannot_create_accounts(native_app):
    from app.auth.mobile_models import MobileAuthChallenge, utcnow
    from app.utils.db import db

    client = native_app.test_client()
    response, _ = start(client)
    identifier = response["challenge_id"]
    right = code(identifier)
    db.session.get(MobileAuthChallenge, identifier).expires_at = utcnow() - timedelta(
        seconds=1
    )
    db.session.commit()
    assert (
        client.post(
            PREFIX + "/register/verify",
            json={"challenge_id": identifier, "code": right},
        ).status_code
        == 400
    )


def test_mail_outbox_sends_code_once_and_never_contains_plaintext_code(
    native_app, monkeypatch
):
    from app.auth.mobile_mail import process_auth_mail, email_sender
    from app.auth.mobile_models import MobileAuthMail

    client = native_app.test_client()
    proof, _ = start(client)
    right = code(proof["challenge_id"])
    observed = []
    monkeypatch.setattr(
        email_sender, "send_email", lambda **kwargs: observed.append(kwargs) or True
    )
    process_auth_mail(batch_size=20)
    assert any(v["context"]["code"] == right for v in observed)
    row = MobileAuthMail.query.filter_by(challenge_id=proof["challenge_id"]).one()
    assert row.status == "sent" and row.encrypted_code is None
    before = len(observed)
    process_auth_mail(batch_size=20)
    assert len(observed) == before


@pytest.fixture
def social(native_app, monkeypatch):
    import app.api.mobile_social as module

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        module._google_keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=key.public_key()),
    )
    native_app.config.update(
        MOBILE_GOOGLE_CLIENT_ID="test-client", MOBILE_GOOGLE_CLIENT_SECRET="test-secret"
    )

    def token(nonce, **extra):
        values = dict(
            iss="https://accounts.google.com",
            aud="test-client",
            sub="provider-" + uuid4().hex,
            iat=int(time.time()),
            exp=int(time.time()) + 600,
            nonce=nonce,
            email=address(),
            email_verified=True,
        )
        values.update(extra)
        return jwt.encode(values, key, algorithm="RS256")

    return module, token


def oauth(client, social, email=None, subject=None):
    module, token = social
    verifier = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    started = client.post(
        PREFIX + "/social/start",
        json={"provider": "google", "code_challenge": challenge, "state": state},
    )
    assert started.status_code == 200, started.json
    claims = {}
    if email:
        claims["email"] = email
    if subject:
        claims["sub"] = subject
    grant = token(started.json["nonce"], **claims)
    original = module._post_json
    module._post_json = lambda *a, **k: {"id_token": grant}
    try:
        callback = client.get(
            PREFIX + "/google/callback",
            query_string={
                "state": started.json["challenge_id"],
                "code": "only-disposable-code",
            },
        )
    finally:
        module._post_json = original
    assert callback.status_code == 303, callback.json
    query = {k: v[0] for k, v in parse_qs(urlparse(callback.location).query).items()}
    assert (
        query["state"] == state
        and "access_token" not in callback.location
        and "id_token" not in callback.location
    )
    return query, verifier


def test_google_pkce_exchange_and_profile_create_one_private_identity(
    native_app, social
):
    from app.auth.mobile_models import SocialIdentity

    client = native_app.test_client()
    query, verifier = oauth(client, social)
    failed = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": secrets.token_urlsafe(32),
        },
    )
    assert failed.status_code == 401
    response = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.json
    assert response.json["status"] == "profile_required"
    finish = client.post(
        PREFIX + "/social/profile",
        json={
            "ticket": response.json["ticket"],
            "username": "social" + uuid4().hex[:8],
            "terms_accepted": True,
            "level": "B1",
        },
    )
    assert finish.status_code == 200, finish.json
    assert finish.json["access_token"] and finish.json["auth_provider"] == "google"
    assert (
        SocialIdentity.query.filter_by(
            user_id=finish.json["user"]["id"], provider="google"
        ).count()
        == 1
    )
    assert (
        client.post(
            PREFIX + "/social/exchange",
            json={
                "challenge_id": query["challenge_id"],
                "code": query["code"],
                "code_verifier": verifier,
            },
        ).status_code
        == 400
    )


def test_social_email_match_requires_existing_password_before_link(native_app, social):
    from app.auth.mobile_models import SocialIdentity
    from app.utils.db import db

    user, _ = learner(native_app)
    user.email = address()
    db.session.commit()
    client = native_app.test_client()
    query, verifier = oauth(client, social, email=user.email)
    result = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": verifier,
        },
    )
    assert result.json["status"] == "link_required"
    assert SocialIdentity.query.filter_by(user_id=user.id).count() == 0
    assert (
        client.post(
            PREFIX + "/social/link",
            json={"ticket": result.json["ticket"], "password": "wrong"},
        ).status_code
        == 401
    )
    linked = client.post(
        PREFIX + "/social/link",
        json={
            "ticket": result.json["ticket"],
            "password": "only-disposable-local-test-password",
        },
    )
    assert linked.status_code == 200, linked.json
    assert linked.json["user"]["id"] == user.id
    assert SocialIdentity.query.filter_by(user_id=user.id).count() == 1


def test_identity_verification_rejects_wrong_nonce_audience_and_issuer(
    native_app, social
):
    module, token = social
    for changes in [
        {"nonce": "wrong"},
        {"aud": "another-app"},
        {"iss": "https://example.com"},
        {"iat": int(time.time()) - 7200},
    ]:
        with pytest.raises(module.AuthProblem):
            module._identity(
                token(changes.pop("nonce", "expected"), **changes), "google", "expected"
            )


def test_unconfigured_providers_are_hidden_and_rejected(native_app):
    client = native_app.test_client()
    native_app.config.update(
        MOBILE_GOOGLE_CLIENT_ID="",
        MOBILE_GOOGLE_CLIENT_SECRET="",
        MOBILE_APPLE_ENABLED=False,
    )
    config = client.get(PREFIX + "/config")
    assert (
        config.status_code == 200
        and not config.json["google"]
        and not config.json["apple"]
    )
    assert (
        client.post(
            PREFIX + "/social/start",
            json={
                "provider": "apple",
                "state": secrets.token_urlsafe(32),
                "code_challenge": secrets.token_urlsafe(32),
            },
        ).status_code
        == 503
    )


def test_returning_social_identity_keeps_the_existing_user_and_progress(
    native_app, social
):
    from app.auth.models import User
    from app.utils.db import db

    subject = "fixed-" + uuid4().hex
    client = native_app.test_client()
    query, verifier = oauth(client, social, subject=subject)
    reply = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": verifier,
        },
    ).json
    created = client.post(
        PREFIX + "/social/profile",
        json={
            "ticket": reply["ticket"],
            "username": "social" + uuid4().hex[:8],
            "terms_accepted": True,
        },
    ).json
    count = User.query.count()
    user_id = created["user"]["id"]
    query, verifier = oauth(client, social, subject=subject)
    returning = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": verifier,
        },
    )
    assert returning.status_code == 200, returning.json
    assert (
        returning.json["user"]["id"] == user_id
        and returning.json["status"] == "authenticated"
    )
    assert User.query.count() == count


def test_apple_checks_native_nonce_and_code_exchange_and_encrypts_provider_refresh(
    native_app, social, monkeypatch
):
    from app.auth.mobile_models import MobileAuthChallenge, SocialIdentity
    from app.auth.mobile_mail import cipher
    from app.utils.db import db
    import app.api.mobile_social as module

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        module._apple_keys,
        "get_signing_key_from_jwt",
        lambda _: SimpleNamespace(key=key.public_key()),
    )
    monkeypatch.setattr(module, "_apple_secret", lambda: "disposable-client-secret")
    native_app.config.update(
        MOBILE_APPLE_ENABLED=True,
        MOBILE_APPLE_PRIVATE_KEY="test",
        MOBILE_APPLE_TEAM_ID="test-team",
        MOBILE_APPLE_KEY_ID="test-key",
        MOBILE_APPLE_CLIENT_ID="com.llt.english.ios",
    )
    client = native_app.test_client()
    verifier = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    start = client.post(
        PREFIX + "/social/start",
        json={"provider": "apple", "code_challenge": challenge, "state": state},
    ).json
    subject = "apple-" + uuid4().hex
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": "com.llt.english.ios",
        "sub": subject,
        "nonce": start["nonce"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "email": address(),
        "email_verified": "true",
    }
    token = jwt.encode(claims, key, algorithm="RS256")

    def exchange(url, form):
        assert (
            url == "https://appleid.apple.com/auth/token"
            and form["client_secret"] == "disposable-client-secret"
        )
        assert form["code"] == "native-disposable-code"
        return {"id_token": token, "refresh_token": "private-provider-refresh"}

    monkeypatch.setattr(module, "_post_json", exchange)
    result = client.post(
        PREFIX + "/apple/complete",
        json={
            "challenge_id": start["challenge_id"],
            "identity_token": token,
            "authorization_code": "native-disposable-code",
            "code_verifier": verifier,
        },
    )
    assert result.status_code == 200, result.json
    pending = db.session.get(MobileAuthChallenge, result.json["ticket"])
    assert "private-provider-refresh" not in str(pending.payload)
    assert (
        cipher().decrypt(pending.payload["encrypted_refresh"].encode()).decode()
        == "private-provider-refresh"
    )
    profile = client.post(
        PREFIX + "/social/profile",
        json={
            "ticket": result.json["ticket"],
            "username": "apple" + uuid4().hex[:8],
            "terms_accepted": True,
        },
    )
    assert profile.status_code == 200, profile.json
    assert (
        profile.json["apple_subject"] == subject
        and profile.json["auth_provider"] == "apple"
    )
    assert (
        SocialIdentity.query.filter_by(provider="apple", subject=subject)
        .one()
        .encrypted_refresh
    )
    assert (
        client.post(
            PREFIX + "/apple/complete",
            json={
                "challenge_id": start["challenge_id"],
                "identity_token": token,
                "authorization_code": "native-disposable-code",
                "code_verifier": verifier,
            },
        ).status_code
        == 400
    )
    native_app.config["MOBILE_APPLE_ENABLED"] = False


def test_reset_proof_cannot_be_used_after_another_password_change(native_app):
    from app.utils.db import db

    user, _ = learner(native_app)
    user.email = address()
    db.session.commit()
    client = native_app.test_client()
    result = client.post(PREFIX + "/password/start", json={"email": user.email}).json
    right = code(result["challenge_id"])
    user.set_password("New!Secret73")
    db.session.commit()
    response = client.post(
        PREFIX + "/password/verify",
        json={
            "challenge_id": result["challenge_id"],
            "code": right,
            "password": "Orange!Lake73",
        },
    )
    assert response.status_code == 400
    db.session.refresh(user)
    assert user.check_password("New!Secret73")


def test_disabled_account_cannot_reset_or_obtain_social_session(native_app, social):
    from app.auth.mobile_models import MobileAuthMail
    from app.utils.db import db

    user, _ = learner(native_app)
    user.email = address()
    user.active = False
    db.session.commit()
    client = native_app.test_client()
    pending = client.post(PREFIX + "/password/start", json={"email": user.email})
    assert (
        pending.status_code == 200
        and not MobileAuthMail.query.filter_by(
            challenge_id=pending.json["challenge_id"]
        ).first()
    )
    query, verifier = oauth(client, social, email=user.email)
    reply = client.post(
        PREFIX + "/social/exchange",
        json={
            "challenge_id": query["challenge_id"],
            "code": query["code"],
            "code_verifier": verifier,
        },
    )
    assert reply.status_code == 403 and "access_token" not in reply.json


def test_new_sessions_do_not_log_in_browser_cookies(native_app):
    client = native_app.test_client()
    started, _ = start(client)
    result = client.post(
        PREFIX + "/register/verify",
        json={
            "challenge_id": started["challenge_id"],
            "code": code(started["challenge_id"]),
        },
    )
    assert result.status_code == 200
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_auth_migration_round_trip_and_single_head():
    from pathlib import Path
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    root = Path(__file__).parents[2]
    path = root / "migrations/versions/20261117_mobile_auth.py"
    spec = importlib.util.spec_from_file_location("mobile_auth_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        names = sa.inspect(connection).get_table_names()
        assert all(
            name in names
            for name in [
                "mobile_auth_challenges",
                "mobile_auth_mail",
                "mobile_auth_throttles",
                "social_identities",
            ]
        )
        module.downgrade()
        assert sa.inspect(connection).get_table_names() == ["users"]
    assert ScriptDirectory(str(root / "migrations")).get_heads() == [
        "20261117_mobile_auth"
    ]


def test_auth_mail_retries_are_bounded_and_clear_expired_code(native_app, monkeypatch):
    from app.auth.mobile_mail import process_auth_mail, email_sender
    from app.auth.mobile_models import MobileAuthMail, utcnow
    from app.utils.db import db

    client = native_app.test_client()
    challenge, _ = start(client)
    monkeypatch.setattr(email_sender, "send_email", lambda **kwargs: False)
    identifier = challenge["challenge_id"]
    for attempt in range(1, 4):
        row = MobileAuthMail.query.filter_by(challenge_id=identifier).one()
        row.available_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
        process_auth_mail(batch_size=20)
        db.session.refresh(row)
        assert row.attempts == attempt and row.status == "pending"
    row.available_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    process_auth_mail(batch_size=20)
    db.session.refresh(row)
    assert row.status == "expired" and row.attempts == 3 and row.encrypted_code is None


def test_auth_mail_scheduler_has_context_and_always_cleans_session(
    native_app, monkeypatch
):
    from unittest.mock import MagicMock, patch
    from flask import current_app
    from app import email_scheduler
    from app.auth import mobile_mail
    from app.utils.db import db

    scheduler = MagicMock()
    monkeypatch.setattr(email_scheduler, "_scheduler", None)
    monkeypatch.setattr(email_scheduler, "BackgroundScheduler", lambda: scheduler)
    email_scheduler.init_email_scheduler(native_app)
    jobs = {call.kwargs["id"]: call for call in scheduler.add_job.call_args_list}
    job = jobs["native_auth_mail"]
    assert job.kwargs["seconds"] == 30 and job.kwargs["max_instances"] == 1

    def fail():
        assert current_app._get_current_object() is native_app
        raise RuntimeError("disposable test failure")

    with patch.object(mobile_mail, "process_auth_mail", side_effect=fail), patch.object(
        db.session, "rollback"
    ) as rollback, patch.object(db.session, "remove") as remove:
        job.args[0]()
        rollback.assert_called_once()
        assert remove.call_count >= 1
