"""Security checks use disposable accounts; no real email or Telegram is sent."""

from datetime import timedelta
from pathlib import Path
import importlib.util

import pytest

from tests.api import test_account_deletion as original

native_app = original.native_app
PREFIX = original.PREFIX
REASON = "Нужно убедиться, что удаление запросил владелец аккаунта."


@pytest.fixture
def case(native_app):
    from flask import g
    from app.auth.mobile_models import MobileAuthThrottle
    from app.auth.account_deletion import AccountDeletionMail
    from app.utils.db import db
    from types import SimpleNamespace

    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    db.session.rollback()
    MobileAuthThrottle.query.delete()
    AccountDeletionMail.query.delete()
    db.session.commit()
    user, headers = original.learner(native_app)
    user.onboarding_completed = True
    db.session.commit()
    receipt = original.submit(native_app, headers)
    admin = original.administrator(native_app)
    return SimpleNamespace(
        app=native_app, client=native_app.test_client(), user=user, headers=headers, receipt=receipt, admin=admin
    )


def ask(case, reason=REASON):
    from app.auth.account_deletion import request_deletion_reconfirmation

    return request_deletion_reconfirmation(case.receipt["id"], case.admin, reason)


def clear_cooldown():
    from app.auth.mobile_models import MobileAuthThrottle
    from app.utils.db import db

    MobileAuthThrottle.query.delete()
    db.session.commit()


def login(case, user):
    from flask import g

    client = case.app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
        session["_fresh"] = True
    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    csrf = client.get("/csrf-token").json["csrf_token"]
    return client, csrf


def test_admin_check_blocks_erasure_preserves_dates_and_requires_fresh_owner_proof(case):
    from app.auth.account_deletion import complete_account_deletion
    from app.api.mobile_auth import AuthProblem
    from app.auth.models import User
    from app.utils.db import db

    row = original.age_request(case.receipt["id"])
    dates = row.requested_at, row.earliest_deletion_at, row.latest_deletion_at
    clear_cooldown()
    old = original.confirmation(original.begin(case.app, case.headers))
    row = ask(case)
    assert row.requires_reconfirmation and row.reconfirmation_reason == REASON
    with pytest.raises(AuthProblem) as error:
        complete_account_deletion(row.id, case.admin)
    assert error.value.code == "reconfirmation_required"
    db.session.rollback()
    stale = case.client.post(PREFIX + "/confirm", headers=case.headers, json=old)
    assert stale.status_code == 400 and stale.json["error"] == "challenge_expired"
    clear_cooldown()
    fresh = original.confirmation(original.begin(case.app, case.headers))
    result = case.client.post(PREFIX + "/confirm", headers=case.headers, json=fresh)
    assert result.status_code == 200, result.json
    assert result.json["request"]["requires_reconfirmation"] is False
    db.session.refresh(row)
    assert (row.requested_at, row.earliest_deletion_at, row.latest_deletion_at) == dates
    assert row.status == "pending" and db.session.get(User, case.user.id)
    assert [event["action"] for event in row.history] == ["requested", "reconfirmation_requested", "reconfirmed"]
    assert row.history[1]["admin_id"] == case.admin.id
    with pytest.raises(AuthProblem) as repeated:
        ask(case)
    assert repeated.value.code == "reconfirmation_already_requested"
    db.session.rollback()
    uid = case.user.id
    complete_account_deletion(row.id, case.admin)
    assert db.session.get(User, uid) is None
    assert row.history[-1]["action"] == "completed"
    assert row.reconfirmation_reason is None
    assert all("reason" not in event for event in row.history)


@pytest.mark.parametrize("reason", [None, "", "short", " " * 20, "a" * 1001])
def test_reason_is_mandatory_and_invalid_request_has_no_side_effects(case, reason):
    from app.api.mobile_auth import AuthProblem
    from app.auth.account_deletion import AccountDeletionRequest, AccountDeletionMail
    from app.notifications.models import Notification
    from app.utils.db import db

    with pytest.raises(AuthProblem) as error:
        ask(case, reason)
    assert error.value.code == "invalid_reason"
    db.session.rollback()
    assert not db.session.get(AccountDeletionRequest, case.receipt["id"]).requires_reconfirmation
    assert db.session.get(AccountDeletionMail, case.receipt["id"]) is None
    assert Notification.query.filter_by(user_id=case.user.id, type="account_deletion").count() == 0


def test_owner_can_cancel_security_check_and_old_code_cannot_reopen_request(case):
    from app.auth.account_deletion import AccountDeletionRequest, process_account_deletion_mail
    from app.utils.db import db

    row = ask(case)
    clear_cooldown()
    proof = original.confirmation(original.begin(case.app, case.headers))
    response = case.client.post(PREFIX + "/cancel", headers=case.headers, json={"request_id": row.id})
    assert response.status_code == 200 and response.json["request"]["status"] == "cancelled"
    assert response.json["request"]["requires_reconfirmation"] is False
    assert case.client.post(PREFIX + "/confirm", headers=case.headers, json=proof).json["error"] == "challenge_expired"
    assert process_account_deletion_mail() == 0
    assert db.session.get(AccountDeletionRequest, row.id).history[-1]["action"] == "cancelled"


def test_security_details_are_visible_only_to_owner_and_admin_not_tracking_receipt(case):
    row = ask(case)
    owner = case.client.get(PREFIX + "/current", headers=case.headers)
    assert owner.json["request"]["reconfirmation_reason"] == REASON
    _, headers = original.learner(case.app)
    assert case.client.get(PREFIX + "/current", headers=headers).json["request"] is None
    tracking = case.client.post(
        PREFIX + "/status", json={"request_id": row.id, "tracking_token": case.receipt["tracking_token"]}
    )
    assert tracking.status_code == 200
    assert "reconfirmation_reason" not in tracking.json["request"]
    assert "history" not in tracking.json["request"]
    assert REASON not in str(tracking.json)


def test_owner_can_cancel_and_immediately_create_new_request_before_mail_worker_runs(case):
    from app.auth.account_deletion import AccountDeletionMail, request_deletion_reconfirmation
    from app.utils.db import db

    old = ask(case)
    old_id = old.id
    assert db.session.get(AccountDeletionMail, old_id) is not None
    assert case.client.post(PREFIX + "/cancel", headers=case.headers, json={"request_id": old_id}).status_code == 200
    clear_cooldown()
    newer = original.submit(case.app, case.headers)
    assert newer["id"] != old_id and not newer["requires_reconfirmation"]
    assert request_deletion_reconfirmation(newer["id"], case.admin, REASON).requires_reconfirmation


def test_legacy_owner_without_email_can_reconfirm_password(case):
    from app.auth.mobile_models import MobileAuthMail
    from app.utils.db import db

    case.user.email = None
    db.session.commit()
    original_row = ask(case)
    original_dates = original_row.earliest_deletion_at, original_row.latest_deletion_at
    clear_cooldown()
    challenge = original.begin(case.app, case.headers)
    assert challenge["verification"] == "password"
    assert MobileAuthMail.query.filter_by(challenge_id=challenge["challenge_id"]).count() == 0
    response = case.client.post(
        PREFIX + "/confirm",
        headers=case.headers,
        json={
            "challenge_id": challenge["challenge_id"],
            "confirm": True,
            "password": "only-disposable-local-test-password",
        },
    )
    assert response.status_code == 200 and not response.json["request"]["requires_reconfirmation"]
    assert (original_row.earliest_deletion_at, original_row.latest_deletion_at) == original_dates


def test_user_notification_and_email_are_transactional_and_real_mail_signature_is_used(case, monkeypatch):
    from app.auth.account_deletion import AccountDeletionMail, process_account_deletion_mail
    from app.notifications.models import Notification
    from app.utils.email_utils import email_sender
    from app.utils.db import db
    from flask import current_app

    row = ask(case, "Проверка безопасности <script>alert(1)</script>")
    notice = Notification.query.filter_by(user_id=case.user.id, type="account_deletion").one()
    assert notice.link == "/account-deletion"
    mail = db.session.get(AccountDeletionMail, row.id)
    assert mail.purpose == "reconfirmation" and case.user.email not in mail.encrypted_email
    calls = []

    def send(subject, to_email, template_name, context=None, *, timeout=None, standalone=False):
        calls.append((to_email, template_name))
        html = current_app.jinja_env.get_template("emails/" + template_name + ".html").render(**context)
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert "/account-deletion" in html
        return True

    monkeypatch.setattr(email_sender, "send_email", send)
    assert process_account_deletion_mail() == 1
    assert process_account_deletion_mail() == 0
    assert calls == [(case.user.email, "account_deletion_reconfirmation")]
    assert mail.encrypted_email is None


def test_queued_verification_mail_is_not_sent_after_owner_already_reconfirmed(case, monkeypatch):
    from app.auth.account_deletion import process_account_deletion_mail
    from app.utils.email_utils import email_sender

    ask(case)
    clear_cooldown()
    original.submit(case.app, case.headers)
    monkeypatch.setattr(email_sender, "send_email", lambda **kw: pytest.fail("stale mail sent"))
    assert process_account_deletion_mail() == 0


def test_admin_route_requires_csrf_admin_role_and_records_history(case):
    from app.auth.account_deletion import AccountDeletionRequest
    from app.admin.audit import AdminAuditLog
    from app.utils.db import db

    path = "/admin/account-deletions/" + case.receipt["id"] + "/reconfirm"
    regular, csrf = login(case, case.user)
    assert regular.post(path, data={"reason": REASON, "csrf_token": csrf}).status_code == 302
    assert not db.session.get(AccountDeletionRequest, case.receipt["id"]).requires_reconfirmation
    admin, csrf = login(case, case.admin)
    assert admin.post(path, data={"reason": REASON}, headers={"Accept": "application/json"}).status_code == 400
    assert admin.post(path, data={"reason": "bad", "csrf_token": csrf}).status_code == 400
    assert admin.post(path, data={"reason": REASON, "csrf_token": csrf}).status_code == 302
    page = admin.get("/admin/account-deletions", query_string={"status": "verification"})
    assert REASON in page.get_data(as_text=True)
    assert 'name="confirmation"' not in page.get_data(as_text=True)
    assert AdminAuditLog.query.filter_by(admin_id=case.admin.id, action="account.deletion.reconfirm").count() == 1


def test_web_owner_can_reconfirm_with_same_checks_and_other_user_cannot_access_reason(case):
    from app.auth.account_deletion import AccountDeletionRequest
    from app.utils.db import db

    row = ask(case)
    owner, csrf = login(case, case.user)
    page = owner.get("/account-deletion")
    assert page.status_code == 200 and page.headers["Cache-Control"] == "private, no-store"
    assert REASON in page.get_data(as_text=True)
    assert (
        owner.post("/account-deletion", data={"action": "start"}, headers={"Accept": "application/json"}).status_code
        == 400
    )
    clear_cooldown()
    response = owner.post("/account-deletion", data={"action": "start", "csrf_token": csrf})
    assert response.status_code == 200
    with owner.session_transaction() as session:
        challenge = dict(session["account_deletion_challenge"])
    proof = original.confirmation(challenge)
    bad = owner.post(
        "/account-deletion",
        data={
            "action": "confirm",
            "csrf_token": csrf,
            "challenge_id": challenge["challenge_id"],
            "code": "000000" if proof["code"] != "000000" else "999999",
        },
    )
    assert bad.status_code == 400
    response = owner.post(
        "/account-deletion",
        data={
            "action": "confirm",
            "csrf_token": csrf,
            "challenge_id": challenge["challenge_id"],
            "code": proof["code"],
        },
    )
    assert response.status_code == 302
    assert not db.session.get(AccountDeletionRequest, row.id).requires_reconfirmation
    other, _ = original.learner(case.app)
    other.onboarding_completed = True
    db.session.commit()
    outsider, _ = login(case, other)
    assert REASON not in outsider.get("/account-deletion").get_data(as_text=True)


def test_notification_failure_rolls_back_pause_history_and_mail_together(case, monkeypatch):
    from app.notifications import services
    from app.auth.account_deletion import AccountDeletionRequest, AccountDeletionMail
    from app.utils.db import db

    def failure(**kw):
        raise RuntimeError("local notification failure")

    monkeypatch.setattr(services, "create_notification", failure)
    with pytest.raises(RuntimeError):
        ask(case)
    db.session.rollback()
    row = db.session.get(AccountDeletionRequest, case.receipt["id"])
    assert not row.requires_reconfirmation and row.history[-1]["action"] == "requested"
    assert db.session.get(AccountDeletionMail, row.id) is None


def test_reminders_never_tell_admin_to_delete_before_owner_confirmation(case, monkeypatch):
    from app.auth import account_deletion_notifications as reminders
    from app.notifications.models import Notification
    from app.utils.db import db

    row = ask(case)
    now = row.latest_deletion_at + timedelta(days=2)
    monkeypatch.setattr(reminders, "utcnow", lambda: now)
    assert reminders.process_admin_deletion_notices() >= 1
    db.session.refresh(row)
    notice = (
        Notification.query.filter_by(user_id=case.admin.id, type="account_deletion")
        .order_by(Notification.id.desc())
        .first()
    )
    assert "Ожидается повторное подтверждение" in notice.title
    assert row.requires_reconfirmation and row.status == "pending"


def test_migration_keeps_existing_pending_requests_and_completion_mail(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    modules = []
    for name in ["20261118_account_deletion", "20261119_deletion_reconfirmation"]:
        spec = importlib.util.spec_from_file_location(name, Path("migrations/versions") / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "migration.sqlite"))
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users VALUES (1)")
        with Operations.context(MigrationContext.configure(connection)):
            modules[0].upgrade()
            connection.exec_driver_sql(
                "INSERT INTO account_deletion_requests (id,user_id,status,requested_at,earliest_deletion_at,latest_deletion_at,admin_notice_after) VALUES ('legacy',1,'pending','2026-11-19','2026-11-26','2026-12-03','2026-11-19')"
            )
            connection.exec_driver_sql(
                "INSERT INTO account_deletion_mail (request_id,available_at) VALUES ('legacy','2026-11-19')"
            )
            modules[1].upgrade()
            assert connection.exec_driver_sql(
                "SELECT requires_reconfirmation, history FROM account_deletion_requests"
            ).one() == (0, "[]")
            assert connection.exec_driver_sql("SELECT purpose FROM account_deletion_mail").scalar() == "completed"
            modules[1].downgrade()
            assert connection.exec_driver_sql("SELECT id FROM account_deletion_requests").scalar() == "legacy"
            assert connection.exec_driver_sql("SELECT id FROM users").scalar() == 1
    engine.dispose()
