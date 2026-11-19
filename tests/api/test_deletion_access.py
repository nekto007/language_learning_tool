"""Confirmed deletion pauses web/JWT learning, not ownership or cancellation."""

from datetime import datetime, UTC
from types import SimpleNamespace

import pytest

from tests.api import test_account_deletion as original

native_app = original.native_app
PREFIX = original.PREFIX


@pytest.fixture(scope="module")
def access_app(native_app):
    from flask import jsonify
    from flask_jwt_extended import get_jwt_identity, jwt_required
    from flask_login import current_user, login_required
    from app import csrf

    calls = []

    @csrf.exempt
    @jwt_required()
    def raw_jwt_learning():
        calls.append(("jwt", get_jwt_identity()))
        return jsonify(success=True), 201

    @login_required
    def web_learning():
        calls.append(("web", current_user.id))
        return "learning", 200

    native_app.add_url_rule("/api/raw-jwt-learning", view_func=raw_jwt_learning, methods=["POST"])
    native_app.add_url_rule("/study/access-probe", view_func=web_learning, methods=["GET", "POST"])
    native_app.config["DELETION_TEST_CALLS"] = calls
    yield native_app
    # CSRFProtect is shared between app factories; undo this test-only exemption.
    csrf._exempt_views.discard(f"{raw_jwt_learning.__module__}.{raw_jwt_learning.__name__}")


@pytest.fixture
def owner(access_app):
    from flask import g
    from app.auth.mobile_models import MobileAuthThrottle
    from app.utils.db import db

    db.session.rollback()
    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    MobileAuthThrottle.query.delete()
    db.session.commit()
    user, headers = original.learner(access_app)
    user.onboarding_completed = True
    db.session.commit()
    return SimpleNamespace(
        app=access_app,
        user=user,
        headers=headers,
        client=access_app.test_client(),
        calls=access_app.config["DELETION_TEST_CALLS"],
    )


def cookie(owner):
    from flask import g

    with owner.client.session_transaction() as session:
        session["_user_id"] = owner.user.get_id()
        session["_fresh"] = True
    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    return owner.client.get("/csrf-token").json["csrf_token"]


def test_unconfirmed_challenge_does_not_pause_learning_but_confirmed_request_does(owner):
    challenge = original.begin(owner.app, owner.headers)
    before = len(owner.calls)
    assert owner.client.post("/api/raw-jwt-learning", headers=owner.headers).status_code == 201
    receipt = owner.client.post(PREFIX + "/confirm", headers=owner.headers, json=original.confirmation(challenge)).json[
        "request"
    ]
    response = owner.client.post("/api/raw-jwt-learning", headers=owner.headers)
    assert response.status_code == 403 and response.json["error"] == "account_deletion_pending"
    assert len(owner.calls) == before + 1
    assert receipt["status"] == "pending" and owner.user.active
    assert response.headers["Cache-Control"] == "private, no-store"
    assert owner.user.email not in str(response.json)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/daily-status"),
        ("GET", "/api/books/catalog"),
        ("GET", "/api/words"),
        ("GET", "/api/native/courses"),
        ("GET", "/api/native/grammar/topics"),
        ("POST", "/api/native/srs/session"),
        ("POST", "/api/native/srs/grade"),
        ("POST", "/api/native/lessons/999999/submit"),
        ("POST", "/api/native/lessons/999999/cards/grade"),
        ("PATCH", "/api/native/reading/progress"),
    ],
)
def test_native_learning_routes_are_blocked_before_their_handlers(owner, method, path):
    original.submit(owner.app, owner.headers)
    response = owner.client.open(
        path, method=method, headers=owner.headers, **({"json": {}} if method != "GET" else {})
    )
    assert response.status_code == 403, (path, response.status_code, response.json)
    assert response.json["error"] == "account_deletion_pending"


def test_cookie_learning_redirects_to_management_and_cancel_restores_immediately(owner):
    receipt = original.submit(owner.app, owner.headers)
    csrf = cookie(owner)
    before = len(owner.calls)
    get = owner.client.get("/study/access-probe")
    assert get.status_code == 302 and get.headers["Location"].endswith("/account-deletion")
    post = owner.client.post("/study/access-probe", data={"csrf_token": csrf})
    assert post.status_code == 303 and len(owner.calls) == before
    page = owner.client.get("/account-deletion")
    assert page.status_code == 200 and "Обучение приостановлено" in page.get_data(as_text=True)
    assert (
        owner.client.post(PREFIX + "/cancel", headers=owner.headers, json={"request_id": receipt["id"]}).status_code
        == 200
    )
    assert owner.client.get("/study/access-probe").status_code == 200
    assert owner.client.post("/api/raw-jwt-learning", headers=owner.headers).status_code == 201
    assert owner.user.active


def test_login_current_cancellation_privacy_and_security_check_remain_accessible(owner):
    receipt = original.submit(owner.app, owner.headers)
    login = owner.client.post(
        "/api/login", json={"username": owner.user.username, "password": "only-disposable-local-test-password"}
    )
    assert login.status_code == 200
    assert owner.client.get(PREFIX + "/current", headers=owner.headers).json["request"]["id"] == receipt["id"]
    for path in ["/privacy", "/support/mobile"]:
        assert owner.client.get(path).status_code == 200
    from app.auth.account_deletion import request_deletion_reconfirmation
    from app.auth.mobile_models import MobileAuthThrottle
    from app.utils.db import db

    row = request_deletion_reconfirmation(
        receipt["id"], original.administrator(owner.app), "Подтверди, что удаление запросил владелец аккаунта."
    )
    MobileAuthThrottle.query.delete()
    db.session.commit()
    confirmed = original.submit(owner.app, owner.headers)
    assert not confirmed["requires_reconfirmation"]
    assert owner.client.post("/api/raw-jwt-learning", headers=owner.headers).status_code == 403
    assert owner.client.post(PREFIX + "/cancel", headers=owner.headers, json={"request_id": row.id}).status_code == 200


def test_invalid_token_and_another_valid_token_cannot_bypass_a_pending_cookie(owner):
    original.submit(owner.app, owner.headers)
    cookie(owner)
    _, other_headers = original.learner(owner.app)
    for headers in [{"Authorization": "Bearer invalid"}, other_headers]:
        response = owner.client.post("/api/raw-jwt-learning", headers=headers)
        assert response.status_code == 403


def test_old_signed_access_token_cannot_bypass_pause_on_legacy_jwt_route(owner):
    original.submit(owner.app, owner.headers)
    from app.utils.db import db

    owner.user.set_password("changed-test-password")
    db.session.commit()
    assert owner.client.post("/api/raw-jwt-learning", headers=owner.headers).status_code == 403


def test_another_user_and_anonymous_public_pages_are_unaffected(owner):
    original.submit(owner.app, owner.headers)
    _, headers = original.learner(owner.app)
    assert owner.app.test_client().post("/api/raw-jwt-learning", headers=headers).status_code == 201
    assert owner.app.test_client().get("/privacy").status_code == 200


def test_learning_reminders_stop_but_preferences_survive_cancellation(owner, monkeypatch):
    from app.notifications import push_scheduler
    from app.telegram import scheduler, bot
    from app.reminders.routes import _eligible_users_query
    from app.auth.models import User

    receipt = original.submit(owner.app, owner.headers)
    monkeypatch.setattr(push_scheduler, "has_learning_activity", lambda *a: False)
    now = datetime.now(UTC)
    assert push_scheduler._eligible(owner.user, now) is None
    assert _eligible_users_query().filter(User.id == owner.user.id).count() == 0
    monkeypatch.setattr(bot, "send_message", lambda *a, **kw: pytest.fail("learning nudge sent"))
    scheduler._process_user(
        SimpleNamespace(user_id=owner.user.id, telegram_id=12345), 9, now.date(), False, "https://example.test"
    )
    owner.client.post(PREFIX + "/cancel", headers=owner.headers, json={"request_id": receipt["id"]})
    assert push_scheduler._eligible(owner.user, now) is not None
    assert _eligible_users_query().filter(User.id == owner.user.id).count() == 1
