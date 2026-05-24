"""Task 2 of 2026-05-24 admin audit — per-blueprint admin-gate guards.

The Task 1 inventory test already enforces the global rule that *no* admin
route returns 2xx to an anonymous or a regular (non-admin) user. This module
adds two pieces on top:

1. A per-blueprint parametrized test, so that when a regression slips through
   the developer sees which blueprint group is at fault rather than a single
   monolithic failure with dozens of paths.
2. Targeted smoke checks confirming a known-admin endpoint returns a 200 to
   an authenticated admin — a positive control that protects the auth gate
   from being "fixed" by accidentally breaking everything.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

import pytest

from app.auth.models import User


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
PUBLIC_ENDPOINT_WHITELIST = frozenset({
    # OAuth callback hit by Google's servers; auth is delegated to the OAuth
    # state token, not the Flask session.
    "seo_admin.gsc_callback",
})

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


def _blueprint_of(endpoint: str) -> str:
    return endpoint.split(".", 1)[0] if "." in endpoint else endpoint


def _group_admin_rules(app):
    """Group all admin rules by their blueprint name."""
    grouped: dict[str, list] = defaultdict(list)
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith(ADMIN_BLUEPRINT_PREFIXES):
            continue
        methods = {m for m in rule.methods if m not in ("HEAD", "OPTIONS")}
        if not methods:
            continue
        grouped[_blueprint_of(rule.endpoint)].append(rule)
    return grouped


@pytest.fixture
def regular_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"acl_regular_{suffix}",
        email=f"acl_regular_{suffix}@example.com",
        active=True,
        onboarding_completed=True,
    )
    user.set_password("regularpass123")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def regular_client(client, regular_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(regular_user.id)
        sess["_fresh"] = True
    return client


def _collect_blueprint_names(app) -> list[str]:
    return sorted(_group_admin_rules(app).keys())


# Static list of blueprint names that we expect to exist; parametrization
# resolves at collection time, before the `app` fixture can give us the live
# url_map. The dynamic test below double-checks that every live blueprint is
# represented here, so the static list cannot silently drift.
ADMIN_BLUEPRINT_NAMES = sorted(prefix.rstrip(".") for prefix in ADMIN_BLUEPRINT_PREFIXES)


def _assert_no_2xx(client_obj, rules):
    failures: list[str] = []
    for rule in rules:
        if rule.endpoint in PUBLIC_ENDPOINT_WHITELIST:
            continue
        methods = {m for m in rule.methods if m not in ("HEAD", "OPTIONS")}
        path = _fill_rule(str(rule))
        for method in sorted(methods):
            resp = client_obj.open(path, method=method, follow_redirects=False)
            if 200 <= resp.status_code < 300:
                failures.append(
                    f"{method} {path} ({rule.endpoint}) -> {resp.status_code}"
                )
    return failures


@pytest.mark.parametrize("blueprint_name", ADMIN_BLUEPRINT_NAMES)
def test_blueprint_rejects_anonymous(app, client, blueprint_name):
    """Every route in each admin blueprint must reject anonymous callers."""
    rules = _group_admin_rules(app).get(blueprint_name, [])
    assert rules, f"No rules discovered for blueprint {blueprint_name}"
    failures = _assert_no_2xx(client, rules)
    assert not failures, (
        f"{blueprint_name}: anonymous client got 2xx on:\n" + "\n".join(failures)
    )


@pytest.mark.parametrize("blueprint_name", ADMIN_BLUEPRINT_NAMES)
def test_blueprint_rejects_regular_user(app, regular_client, blueprint_name):
    """Every route in each admin blueprint must reject authenticated non-admin users."""
    rules = _group_admin_rules(app).get(blueprint_name, [])
    assert rules, f"No rules discovered for blueprint {blueprint_name}"
    failures = _assert_no_2xx(regular_client, rules)
    assert not failures, (
        f"{blueprint_name}: regular user got 2xx on:\n" + "\n".join(failures)
    )


def test_static_blueprint_list_matches_live_app(app):
    """The hardcoded blueprint list must cover every blueprint the app registers.

    If a new admin blueprint is added, update both
    ``ADMIN_BLUEPRINT_PREFIXES`` here and in ``test_admin_url_inventory.py``.
    """
    live = set(_collect_blueprint_names(app))
    declared = set(ADMIN_BLUEPRINT_NAMES)
    missing_in_static = live - declared
    assert not missing_in_static, (
        "App registers admin blueprints not covered by ADMIN_BLUEPRINT_PREFIXES: "
        f"{sorted(missing_in_static)}"
    )


@pytest.mark.smoke
def test_admin_dashboard_accessible_to_admin(admin_client):
    """Positive control: an admin user must reach the admin dashboard.

    If this fails while the negative-control tests pass, the auth gate is
    blocking everyone — not just non-admins.
    """
    resp = admin_client.get("/admin/", follow_redirects=False)
    assert resp.status_code in (200, 302), (
        f"Admin dashboard returned {resp.status_code} for an admin user"
    )


@pytest.mark.smoke
def test_whitelisted_public_endpoints_still_registered(app):
    """If a whitelisted endpoint disappears the whitelist becomes a lie."""
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    missing = PUBLIC_ENDPOINT_WHITELIST - endpoints
    assert not missing, f"Whitelisted endpoints missing from app: {sorted(missing)}"
