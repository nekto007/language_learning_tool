"""Malformed login keys stay safe before credential validation and throttling.

The Redis check uses only its real encoder, never a Redis connection. Actual
HTTP throttling uses an explicitly installed in-memory backend and disposable
SQLite app fixture, regardless of the developer's configured backend.
"""

from flask import Flask
from limits.storage import MemoryStorage
import pytest
from redis._parsers.encoders import Encoder

from app.utils.rate_limit_helpers import get_remote_address_key, get_username_key


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    import app as app_module
    from app.utils.db import db
    from config.settings import Config

    class C(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(tmp_path_factory.mktemp("login-throttle") / "test.db")
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = True
        RATELIMIT_ENABLED = True
        RATELIMIT_STORAGE_URI = "memory://"
        MAIL_SUPPRESS_SEND = True
        SERVER_NAME = "localhost"
        SESSION_COOKIE_DOMAIN = None
        SESSION_COOKIE_SECURE = False

    # Keep the existing extension instance: route decorators bind that instance
    # when the blueprint is imported. Force its storage to memory before init.
    limiter = app_module.limiter
    with pytest.MonkeyPatch.context() as changes:
        for attribute in ("enabled", "initialized", "_storage", "_limiter", "_request_identifier"):
            changes.setattr(limiter, attribute, getattr(limiter, attribute))
        changes.setattr(limiter, "_storage_uri", "memory://")
        changes.setattr(limiter, "_swallow_errors", False)
        application = app_module.create_app(config_class=C)
        assert limiter.enabled and limiter.initialized
        assert isinstance(limiter.storage, MemoryStorage)
        with application.app_context():
            db.create_all()
            yield application
            limiter.storage.reset()
            db.session.remove()
            db.engine.dispose()


@pytest.fixture
def memory_throttle(native_app):
    from app import limiter

    limiter.storage.reset()
    return native_app


@pytest.mark.parametrize("field", ["json", "username", "username_or_email"])
@pytest.mark.parametrize("identity", ["name\ud800rest", "\udfff@example.invalid", "person@example.\ud800"])
def test_malformed_identity_falls_back_to_utf8_encodable_ip_key(field, identity):
    app = Flask(__name__)
    arguments = {"json": {"username": identity}} if field == "json" else {"data": {field: identity}}
    # Form encoding cannot represent a surrogate either; construct form fields
    # in memory so this checks the helper before any network/form encoder.
    with app.test_request_context(
        method="POST",
        json={"username": identity} if field == "json" else None,
        environ_base={"REMOTE_ADDR": "192.0.2.41"},
    ):
        if field != "json":
            from werkzeug.datastructures import ImmutableMultiDict
            from flask import request

            request.form = ImmutableMultiDict(arguments["data"])
        key = get_username_key()
        assert key == "ip:192.0.2.41"
        assert Encoder("utf-8", "strict", False).encode(key) == b"ip:192.0.2.41"


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("  OrdinaryUser  ", "username:OrdinaryUser"),
        ("ordinaryuser", "username:ordinaryuser"),
        ("  Learner@EXAMPLE.COM ", "username:learner@example.com"),
        ("Семья 🙂", "username:Семья 🙂"),
    ],
)
def test_valid_identity_bucket_remains_compatible_and_is_not_hashed(identity, expected):
    app = Flask(__name__)
    with app.test_request_context(method="POST", json={"username": identity}):
        assert get_username_key() == expected
        assert Encoder("utf-8", "strict", False).encode(expected) == expected.encode("utf-8")


def test_native_malformed_json_identity_returns400_with_limiter_enabled(memory_throttle):
    app = memory_throttle
    client = app.test_client()
    for identity in ["name\ud800rest", "person@exam\udfffple.invalid"]:
        response = client.post("/api/login", json={"username": identity, "password": "test-password"})
        assert response.status_code == 400
        assert response.json["error"] == "invalid_credentials_format"
        assert "Set-Cookie" not in response.headers and "access_token" not in response.json


def test_malformed_identity_variants_share_real_throttle_instead_of_skipping_it(memory_throttle):
    client = memory_throttle.test_client()
    for index in range(15):
        response = client.post("/api/login", json={"username": f"name{index}\ud800rest", "password": "test-password"})
        assert response.status_code == 400, (index, response.status_code, response.json)
    response = client.post("/api/login", json={"username": "another\udfffname", "password": "test-password"})
    assert response.status_code == 429


def test_static_login_limits_are_exact_and_isolated_by_identity_and_ip(memory_throttle, monkeypatch):
    from types import SimpleNamespace
    import app.api.auth as auth_module
    from app import limiter

    # No password verification, last_login writes or token generation; this
    # exercises the real registered route and extension with a failed account.
    query = SimpleNamespace(first=lambda: None)
    query.filter_by = lambda **kwargs: query
    monkeypatch.setattr(auth_module, "User", SimpleNamespace(query=query))
    before = {key: len(value) for key, value in limiter.limit_manager._decorated_limits.items()}
    first, second = memory_throttle.test_client(), memory_throttle.test_client()

    def attempt(client, name, ip):
        return client.post(
            "/api/login",
            json={"username": name, "password": "not-a-real-password"},
            environ_overrides={"REMOTE_ADDR": ip},
        )

    for index in range(15):
        response = attempt(first, "review_user_one", "192.0.2.61")
        assert response.status_code == 401, (index, response.status_code)
    assert attempt(first, "review_user_one", "192.0.2.61").status_code == 429
    # Account throttle follows the identity across IPs; another account stays
    # usable on either IP until that account or the IP actually hits its limit.
    assert attempt(second, "review_user_one", "192.0.2.62").status_code == 429
    assert attempt(second, "review_user_two", "192.0.2.62").status_code == 401
    assert attempt(first, "review_user_two", "192.0.2.61").status_code == 401
    after = {key: len(value) for key, value in limiter.limit_manager._decorated_limits.items()}
    assert after == before


def test_malformed_identity_ip_bucket_does_not_block_another_ip(memory_throttle):
    first, second = memory_throttle.test_client(), memory_throttle.test_client()
    for index in range(15):
        response = first.post(
            "/api/login",
            json={"username": f"bad{index}\ud800", "password": "test-password"},
            environ_overrides={"REMOTE_ADDR": "192.0.2.71"},
        )
        assert response.status_code == 400
    response = first.post(
        "/api/login",
        json={"username": "bad\ud800", "password": "test-password"},
        environ_overrides={"REMOTE_ADDR": "192.0.2.71"},
    )
    assert response.status_code == 429
    response = second.post(
        "/api/login",
        json={"username": "bad\ud800", "password": "test-password"},
        environ_overrides={"REMOTE_ADDR": "192.0.2.72"},
    )
    assert response.status_code == 400


def test_per_ip_hourly_limit_remains_60_across_different_accounts(memory_throttle, monkeypatch):
    from types import SimpleNamespace
    import app.api.auth as auth_module

    query = SimpleNamespace(first=lambda: None)
    query.filter_by = lambda **kwargs: query
    monkeypatch.setattr(auth_module, "User", SimpleNamespace(query=query))
    client = memory_throttle.test_client()
    for index in range(60):
        response = client.post(
            "/api/login",
            json={"username": f"unknown_{index}", "password": "wrong-password"},
            environ_overrides={"REMOTE_ADDR": "192.0.2.81"},
        )
        assert response.status_code == 401, (index, response.status_code)
    response = client.post(
        "/api/login",
        json={"username": "unknown_61", "password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "192.0.2.81"},
    )
    assert response.status_code == 429
    response = client.post(
        "/api/login",
        json={"username": "unknown_62", "password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "192.0.2.82"},
    )
    assert response.status_code == 401
