"""Task 1 of 2026-05-24 admin audit — URL inventory + auth-gate guard.

The test enumerates every route registered under an admin-prefixed blueprint
and asserts two things:

1. Anonymous requests do NOT receive a 200 / 201 / 204 response (i.e. the
   endpoint is not exposed publicly).
2. Authenticated non-admin users do NOT receive a 200 / 201 / 204 response
   (i.e. the admin gate rejects regular users).

We deliberately whitelist a handful of endpoints that legitimately answer
unauthenticated requests by design — the OAuth callback for Google Search
Console is the only one today (the GSC server posts to it without our
session cookie). The whitelist must stay tiny; every addition deserves a
comment explaining why.

We only exercise routes that take no path parameters (or only ``<int:...>``
parameters that we can substitute with ``1``). Routes requiring strings or
complex converters are checked via their endpoint registration only.
"""
from __future__ import annotations

import re
import uuid

import pytest

from app.auth.models import User
from app.utils.db import db


ADMIN_BLUEPRINT_PREFIXES = (
    "admin.",
    "admin_curriculum.",
    "activity_admin.",
    "audio_admin.",
    "audit_admin.",
    "book_admin.",
    "collection_admin.",
    "curriculum_admin.",
    "dashboard_admin.",
    "grammar_lab_admin.",
    "seo_admin.",
    "settings_admin.",
    "system_admin.",
    "topic_admin.",
    "user_admin.",
    "word_admin.",
)

# Endpoints intentionally callable without an admin session. Keep this list
# tiny and document each entry.
PUBLIC_ENDPOINT_WHITELIST: frozenset[str] = frozenset()

# Path-parameter substitutions for converters Flask exposes. Anything not in
# this map causes the route to be skipped from the live-request assertion (it
# is still asserted that the endpoint exists in app.url_map).
_PARAM_FILLERS = {
    "int": "1",
    "string": "1",
    "path": "1",
    "uuid": str(uuid.uuid4()),
    "float": "1.0",
    "default": "1",
}

_RULE_VAR_RE = re.compile(r"<(?:([a-zA-Z_]+):)?([a-zA-Z_][a-zA-Z0-9_]*)>")


def _fill_rule(rule_str: str) -> str:
    def repl(match: re.Match[str]) -> str:
        converter = match.group(1) or "default"
        return _PARAM_FILLERS.get(converter, "1")

    return _RULE_VAR_RE.sub(repl, rule_str)


def _admin_rules(app):
    rules = []
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith(ADMIN_BLUEPRINT_PREFIXES):
            continue
        methods = {m for m in rule.methods if m not in ("HEAD", "OPTIONS")}
        if not methods:
            continue
        rules.append(rule)
    rules.sort(key=lambda r: (r.endpoint, str(r)))
    return rules


@pytest.fixture
def regular_user(db_session):
    username = f"regular_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        active=True,
        onboarding_completed=True,
    )
    user.set_password("regularpass123")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def regular_client(app, client, regular_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(regular_user.id)
        sess["_fresh"] = True
    return client


@pytest.mark.smoke
def test_url_inventory_is_non_empty(app):
    rules = _admin_rules(app)
    # Sanity check: if the admin module ever stopped registering routes the
    # rest of the audit becomes meaningless. We expect dozens of admin routes.
    assert len(rules) >= 50, f"Admin URL inventory looks broken — found {len(rules)} routes"


@pytest.mark.smoke
def test_admin_routes_reject_anonymous(app, client):
    """Anonymous requests must not succeed on any admin endpoint."""
    failures: list[str] = []
    for rule in _admin_rules(app):
        if rule.endpoint in PUBLIC_ENDPOINT_WHITELIST:
            continue
        methods = {m for m in rule.methods if m not in ("HEAD", "OPTIONS")}
        path = _fill_rule(str(rule))
        for method in sorted(methods):
            resp = client.open(path, method=method, follow_redirects=False)
            # Allowed outcomes: redirect to login (302/303) or 401/403/404/405.
            # 2xx responses to anonymous clients are bugs.
            if 200 <= resp.status_code < 300:
                failures.append(f"{method} {path} ({rule.endpoint}) -> {resp.status_code}")
    assert not failures, "Admin endpoints returned 2xx to anonymous clients:\n" + "\n".join(failures)


def test_admin_routes_reject_regular_user(app, regular_client):
    """Authenticated non-admin users must not succeed on any admin endpoint."""
    failures: list[str] = []
    for rule in _admin_rules(app):
        if rule.endpoint in PUBLIC_ENDPOINT_WHITELIST:
            continue
        methods = {m for m in rule.methods if m not in ("HEAD", "OPTIONS")}
        path = _fill_rule(str(rule))
        for method in sorted(methods):
            resp = regular_client.open(path, method=method, follow_redirects=False)
            if 200 <= resp.status_code < 300:
                failures.append(f"{method} {path} ({rule.endpoint}) -> {resp.status_code}")
    assert not failures, "Admin endpoints returned 2xx to regular users:\n" + "\n".join(failures)


def test_admin_audit_required_redirects_anonymous(app):
    """admin_audit_required must enforce the admin gate for anonymous callers."""
    from app.admin.utils.decorators import admin_audit_required, admin_required

    @admin_audit_required("test.action", target_type="Test", target_id_arg="item_id")
    def view(item_id: int):  # pragma: no cover - never invoked when anonymous
        return "ok"

    with app.test_request_context("/admin/test/123", method="POST"):
        # Anonymous request — login_required emits a 302 redirect to the login page.
        result = view(item_id=123)
    # Flask-Login returns a Response with a 3xx status code for unauthenticated
    # callers when login_required fires.
    status = getattr(result, "status_code", None)
    assert status in (301, 302, 303, 307, 308), (
        f"admin_audit_required did not bounce anonymous caller (status={status})"
    )
    # Smoke-import admin_required to keep the static reference alive for tools.
    assert callable(admin_required)


def test_admin_audit_required_writes_log_on_success(app, db_session, test_user):
    """A 2xx response must produce an AdminAuditLog entry."""
    from flask_login import login_user
    from app.admin.audit import AdminAuditLog
    from app.admin.utils.decorators import admin_audit_required

    test_user.is_admin = True
    db_session.commit()

    @admin_audit_required("inventory.test_ok", target_type="Inventory", target_id_arg="item_id")
    def view(item_id):
        return "ok", 200

    with app.test_request_context("/admin/inventory/123", method="POST"):
        login_user(test_user)
        response = view(item_id=123)
        assert response.status_code == 200

    db.session.commit()
    entry = (
        db.session.query(AdminAuditLog)
        .filter_by(admin_id=test_user.id, action="inventory.test_ok", target_id=123)
        .first()
    )
    assert entry is not None
    assert entry.target_type == "Inventory"


def test_admin_audit_required_skips_log_on_error(app, db_session, test_user):
    """A 4xx response must NOT produce an AdminAuditLog entry."""
    from flask_login import login_user
    from app.admin.audit import AdminAuditLog
    from app.admin.utils.decorators import admin_audit_required

    test_user.is_admin = True
    db_session.commit()

    @admin_audit_required("inventory.test_skip", target_type="Inventory")
    def view():
        return "bad", 400

    with app.test_request_context("/admin/inventory", method="POST"):
        login_user(test_user)
        response = view()
        assert response.status_code == 400

    db.session.commit()
    entry = (
        db.session.query(AdminAuditLog)
        .filter_by(admin_id=test_user.id, action="inventory.test_skip")
        .first()
    )
    assert entry is None
