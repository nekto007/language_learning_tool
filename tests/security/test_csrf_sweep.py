"""CSRF regression guard (finding of 2026-09-01).

Layers:

1. ``test_exempt_views_allowlist`` -- the static set of ``@csrf.exempt`` views
   must equal ``CSRF_EXEMPT_ALLOWLIST``. A new exemption fails here until it is
   listed together with its reason.
2. ``test_no_mutating_handler_runs_without_token`` -- dynamic sweep: with
   ``WTF_CSRF_ENABLED`` forced on, every POST/PUT/PATCH/DELETE rule is hit by a
   cookie-authenticated user without a token; every handler that still runs
   must be one the sweep may reach. Catches what the static check cannot see
   (blueprint-level exemptions, before_request short-circuits, and an
   allowlisted endpoint whose own manual check silently stopped working).
3. ``test_remember_cookie_alone_cannot_mutate`` -- the cross-site path: session
   cookie gone, only ``remember_token`` left (Flask-Login ships it without
   SameSite unless ``REMEMBER_COOKIE_SAMESITE`` is set). A formerly exempt
   endpoint must be blocked, and the cookie itself must be SameSite=Lax.
4. ``test_reading_session_end_validates_body_token`` -- the beacon endpoint is
   exempt at the framework level (sendBeacon cannot set headers) and validates
   ``csrf_token`` from the body itself.

Testing trap: the session-scoped ``app`` fixture keeps an app context pushed,
so the test client reuses it and ``flask.g`` -- including Flask-Login's
``g._login_user`` -- survives between requests. A client that deleted all its
cookies still looks logged in unless ``_clear_stale_g()`` runs first.
"""
import json
import re

import pytest

MUTATING = ('POST', 'PUT', 'PATCH', 'DELETE')

# module.function -> why the framework-level CSRF check is skipped there.
CSRF_EXEMPT_ALLOWLIST = {
    'app.health.health': 'unauthenticated liveness probe, GET only',
    'app.telegram.routes.webhook': 'external caller (Telegram), gated by the webhook secret header',
    'app.api.auth.api_login': 'issues the JWT; no session exists yet to protect',
    'app.api.auth.refresh': 'refresh token travels in Authorization, no cookie auth involved',
    'app.books.api.reading_session_end': (
        'sendBeacon cannot set headers: validates csrf_token from the body itself '
        '(app.books.api._require_csrf_token)'
    ),
}

# Handlers the dynamic sweep may reach without a token: the allowlist minus
# reading_session_end, whose own check must fire.
SWEEP_MAY_REACH = {
    'app.telegram.routes.webhook',
    'app.api.auth.api_login',
    'app.api.auth.refresh',
}

NO_SUCH_SESSION_ID = 10 ** 9


def _csrf_blocked(resp) -> bool:
    if resp.status_code != 400:
        return False
    data = resp.get_json(silent=True)
    return bool(isinstance(data, dict) and data.get('csrf_expired'))


def _exempt_key(app, endpoint: str) -> str:
    view = app.view_functions[endpoint]
    return f'{view.__module__}.{view.__name__}'


def _clear_stale_g() -> None:
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_login_user', None)


def _fresh_token(client) -> str:
    resp = client.get('/csrf-token')
    assert resp.status_code == 200, resp.status_code
    return resp.get_json()['csrf_token']


@pytest.fixture
def csrf_on(app):
    old = app.config['WTF_CSRF_ENABLED']
    app.config['WTF_CSRF_ENABLED'] = True
    yield
    app.config['WTF_CSRF_ENABLED'] = old


def test_exempt_views_allowlist(app):
    from app import csrf
    assert not csrf._exempt_blueprints, 'blueprint-level CSRF exemptions are not allowed'
    extra = set(csrf._exempt_views) - set(CSRF_EXEMPT_ALLOWLIST)
    missing = set(CSRF_EXEMPT_ALLOWLIST) - set(csrf._exempt_views)
    assert not extra, f'new @csrf.exempt without an allowlist entry and reason: {sorted(extra)}'
    assert not missing, f'allowlisted view is no longer exempt, drop it here too: {sorted(missing)}'


def test_no_mutating_handler_runs_without_token(app, authenticated_client, csrf_on):
    reached = {}
    checked = 0
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = sorted(m for m in (rule.methods or ()) if m in MUTATING)
        # logout is skipped only to keep the client authenticated for the
        # rest of the sweep; the static allowlist covers it.
        if not methods or rule.rule.startswith('/static') or 'logout' in rule.endpoint:
            continue
        path = re.sub(r'<(?:[^:>]+:)?[^>]+>', '1', rule.rule)
        for method in methods:
            checked += 1
            try:
                resp = authenticated_client.open(
                    path, method=method, headers={'Accept': 'application/json'},
                )
                status, blocked = resp.status_code, _csrf_blocked(resp)
            except Exception as exc:  # the handler ran and blew up: not blocked
                status, blocked = f'raised {type(exc).__name__}', False
            if not blocked:
                reached[(method, rule.rule)] = (_exempt_key(app, rule.endpoint), status)
    assert checked > 100, f'sweep saw only {checked} mutating rules, url_map looks wrong'
    offenders = {k: v for k, v in reached.items() if v[0] not in SWEEP_MAY_REACH}
    assert not offenders, (
        'handlers ran without a CSRF token for a cookie-authenticated user:\n'
        + '\n'.join(
            f'  {m} {rule} -> {key} ({status})'
            for (m, rule), (key, status) in sorted(offenders.items())
        )
    )


def test_remember_cookie_alone_cannot_mutate(app, authenticated_client, csrf_on):
    client = authenticated_client
    with client.session_transaction() as sess:
        sess['_remember'] = 'set'  # Flask-Login issues remember_token on the next response
    assert client.get('/csrf-token').status_code == 200
    remember = client.get_cookie('remember_token')
    assert remember is not None, 'remember_token was not issued'
    assert remember.same_site == 'Lax', (
        'REMEMBER_COOKIE_SAMESITE must match SESSION_COOKIE_SAMESITE, otherwise a '
        'cross-site form POST from Firefox/Safari carries the login'
    )

    client.delete_cookie('session')
    _clear_stale_g()
    resp = client.post('/api/plan/resume', headers={'Accept': 'application/json'})
    assert _csrf_blocked(resp), resp.get_data(as_text=True)

    _clear_stale_g()
    resp = client.post(
        '/api/streak/repair', data={'x': '1'}, headers={'Accept': 'application/json'},
    )
    assert _csrf_blocked(resp), resp.get_data(as_text=True)


def test_reading_session_end_validates_body_token(authenticated_client, csrf_on):
    client = authenticated_client
    token = _fresh_token(client)
    url = '/api/books/reading-session/end'
    beacon = {'session_id': NO_SUCH_SESSION_ID, 'current_offset_pct': 0.5}
    plain = {'content_type': 'text/plain', 'headers': {'Accept': 'application/json'}}

    # text/plain is what sendBeacon sends; without a token it must be refused.
    resp = client.post(url, data=json.dumps(beacon), **plain)
    assert _csrf_blocked(resp), resp.get_data(as_text=True)

    # A bogus body token is refused too.
    resp = client.post(url, data=json.dumps({**beacon, 'csrf_token': 'nope'}), **plain)
    assert _csrf_blocked(resp), resp.get_data(as_text=True)

    # Token in the body (the beacon path) passes the gate: handler reached,
    # answers "no such session".
    resp = client.post(url, data=json.dumps({**beacon, 'csrf_token': token}), **plain)
    assert not _csrf_blocked(resp) and resp.status_code == 404, resp.get_data(as_text=True)

    # ...and so does the header (the fetch path).
    resp = client.post(url, json=beacon, headers={'X-CSRFToken': token})
    assert not _csrf_blocked(resp) and resp.status_code == 404, resp.get_data(as_text=True)
