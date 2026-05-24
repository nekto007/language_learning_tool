"""Task 6 of 2026-05-24 admin audit — redirect safety / open-redirect coverage.

Two layers of coverage:

1. **Static scan** — every ``redirect(...)`` call in ``app/admin/`` must use
   either a constant ``url_for(...)`` (or constant string), ``request.url``
   (server-resolved current URL — safe), the canonical
   ``get_safe_redirect_url(...)`` wrapper, or a documented OAuth ``auth_url``
   from a provider flow. Raw ``redirect(request.args.get('next'))``,
   ``redirect(request.form.get('next'))``, and ``redirect(request.referrer)``
   are banned outright.

2. **Runtime** — the only admin endpoint that consumes a user-supplied ``next``
   parameter (``user_admin.toggle_mission_plan``) is exercised through the
   test client with hostile payloads (``https://evil.com``, ``//evil.com``,
   backslash trick) and the redirect ``Location`` is asserted to stay local.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

from app.auth.models import User
from app.utils.db import db


ADMIN_PKG_ROOT = Path(__file__).resolve().parent.parent.parent / 'app' / 'admin'


# Patterns that constitute an open-redirect smell in admin code:
#   redirect(request.args.get('next'...))
#   redirect(request.form.get('next'...))
#   redirect(request.referrer ...)
# A wrapped form like `redirect(get_safe_redirect_url(request.args.get('next')))`
# does not match because the inner call is consumed by the wrapper first.
_RAW_NEXT_RE = re.compile(
    r"redirect\(\s*request\.(args|form)\.get\(\s*['\"]next['\"]"
)
_RAW_REFERRER_RE = re.compile(r"redirect\(\s*request\.referrer")


class TestAdminRedirectStaticAudit:
    """No raw user-controlled value reaches ``redirect()`` in admin code."""

    def _iter_admin_python_files(self):
        for root, _dirs, files in os.walk(ADMIN_PKG_ROOT):
            for fname in files:
                if fname.endswith('.py'):
                    yield Path(root) / fname

    @pytest.mark.smoke
    def test_no_raw_next_redirect_in_admin(self):
        offenders: list[str] = []
        for path in self._iter_admin_python_files():
            with path.open(encoding='utf-8') as fh:
                for lineno, line in enumerate(fh, 1):
                    if _RAW_NEXT_RE.search(line):
                        offenders.append(f'{path}:{lineno}: {line.strip()}')
        assert offenders == [], (
            'Admin code must wrap user-supplied next params with '
            'get_safe_redirect_url(...). Offenders:\n' + '\n'.join(offenders)
        )

    def test_no_raw_referrer_redirect_in_admin(self):
        offenders: list[str] = []
        for path in self._iter_admin_python_files():
            with path.open(encoding='utf-8') as fh:
                for lineno, line in enumerate(fh, 1):
                    if _RAW_REFERRER_RE.search(line):
                        offenders.append(f'{path}:{lineno}: {line.strip()}')
        assert offenders == [], (
            'Admin code must wrap request.referrer with get_safe_redirect_url. '
            'Offenders:\n' + '\n'.join(offenders)
        )


def _make_admin(db_session):
    suffix = uuid.uuid4().hex[:8]
    admin = User(
        username=f'redir_admin_{suffix}',
        email=f'redir_admin_{suffix}@example.com',
        is_admin=True,
        active=True,
    )
    admin.set_password('pass1234')
    db_session.add(admin)
    db_session.flush()
    return admin


def _make_target_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = User(
        username=f'redir_target_{suffix}',
        email=f'redir_target_{suffix}@example.com',
        active=True,
    )
    target.set_password('pass1234')
    db_session.add(target)
    db_session.flush()
    return target


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.mark.smoke
class TestAdminToggleMissionPlanRedirect:
    """Runtime guard: the one admin endpoint that reads ``next`` is safe."""

    def _post(self, client, target_id, next_value):
        return client.post(
            f'/admin/users/{target_id}/toggle_mission_plan',
            data={'next': next_value},
            follow_redirects=False,
        )

    def test_external_https_next_blocked(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = self._post(client, target.id, 'https://evil.com/steal')
        assert resp.status_code in (302, 303)
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_protocol_relative_next_blocked(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = self._post(client, target.id, '//evil.com/steal')
        assert resp.status_code in (302, 303)
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_backslash_trick_next_blocked(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = self._post(client, target.id, '/\\evil.com')
        assert resp.status_code in (302, 303)
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_http_scheme_next_blocked(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = self._post(client, target.id, 'http://evil.com/path')
        assert resp.status_code in (302, 303)
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_internal_next_allowed(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = self._post(client, target.id, f'/admin/users/{target.id}')
        assert resp.status_code in (302, 303)
        location = resp.headers.get('Location', '')
        assert location.endswith(f'/admin/users/{target.id}')
