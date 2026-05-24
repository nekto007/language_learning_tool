"""Task 4 of 2026-05-24 admin audit — destructive-endpoint audit-log coverage.

Two layers of coverage:

1. **Static analysis** — every admin route that accepts a mutating HTTP method
   (POST/PUT/DELETE/PATCH) must call :func:`app.admin.audit.log_admin_action`
   in its view body or be wrapped by ``admin_audit_required``. The check is
   parametrised over the live Flask URL map so newly-added routes are caught
   automatically. A small explicit whitelist documents endpoints that are
   intentionally exempt (search/preview APIs, OAuth start, plain redirects).

2. **Live hits** — a representative slice of destructive endpoints is exercised
   through the test client; we assert that the corresponding ``AdminAuditLog``
   row is written. These verify the static guarantee actually fires at runtime
   under the real decorator stack.

Naming-convention guard: every captured action string is asserted to match the
canonical ``entity.action`` snake_case pattern shared by ``CLAUDE.md``.
"""
from __future__ import annotations

import ast
import inspect
import re
import uuid

import pytest

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.utils.db import db


ADMIN_BLUEPRINT_PREFIXES = (
    'admin.',
    'admin_curriculum.',
    'activity_admin.',
    'audio_admin.',
    'audit_admin.',
    'book_admin.',
    'collection_admin.',
    'curriculum_admin.',
    'grammar_lab_admin.',
    'seo_admin.',
    'settings_admin.',
    'system_admin.',
    'topic_admin.',
    'user_admin.',
    'word_admin.',
)

MUTATING_METHODS = frozenset({'POST', 'PUT', 'DELETE', 'PATCH'})

# Endpoints where a mutating HTTP method does NOT actually persist a domain
# mutation. Each entry must justify itself: search/preview-only flows, OAuth
# start (which only redirects the browser), connection probes, and DB-state
# read-only tests.
AUDIT_LOG_WHITELIST = frozenset({
    # OAuth consent screen — only redirects to Google, no DB write.
    'seo_admin.gsc_connect',
    # GET-style listing helpers historically registered with POST so a download
    # button can post a search payload.
    'audio_admin.get_audio_download_list',
    # DB connectivity probe — read-only.
    'system_admin.test_db_connection',
    # Read-only metadata extractor: saves an upload to a temp dir, returns
    # parsed fields, and removes the file in `finally`. No DB mutation.
    'book_admin.extract_book_metadata',
    # Per-file batch importer; the helper `_import_exercises_json_file`
    # writes a `grammar_exercise.import_json` audit row for every imported
    # file, so the view itself is just a fan-out shell.
    'grammar_lab_admin.import_exercises_json',
})

ACTION_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$')


def _admin_mutating_rules(app):
    """Yield (rule, methods) for every admin route exposing a mutating verb."""
    rules = []
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith(ADMIN_BLUEPRINT_PREFIXES):
            continue
        methods = (rule.methods or set()) & MUTATING_METHODS
        if not methods:
            continue
        rules.append((rule, frozenset(methods)))
    rules.sort(key=lambda item: (item[0].endpoint, str(item[0])))
    return rules


def _view_source(app, endpoint: str) -> str:
    """Return the source of the registered view function (decorators stripped)."""
    view = app.view_functions[endpoint]
    # Walk through any ``@wraps``-aware decorator chain to find the user code.
    inner = view
    seen = set()
    while True:
        wrapped = getattr(inner, '__wrapped__', None)
        if wrapped is None or id(wrapped) in seen:
            break
        seen.add(id(wrapped))
        inner = wrapped
    try:
        return inspect.getsource(inner)
    except (OSError, TypeError):
        # Fall back to outer wrapper source — better than nothing.
        return inspect.getsource(view)


@pytest.mark.smoke
def test_audit_log_inventory_is_non_empty(app):
    """Sanity guard: the audit-log coverage check must see real endpoints."""
    rules = _admin_mutating_rules(app)
    assert len(rules) >= 30, (
        f'Mutating admin endpoint inventory looks broken — found {len(rules)} rules.'
    )


def _audit_param_ids():
    """Pytest IDs for the parametrised static-coverage scan.

    The actual rule list is resolved inside the test via ``app``, so this
    helper exists solely to give pytest a readable parametrize ID space.
    """
    return None


class TestAuditLogStaticCoverage:
    """Static guarantee: every mutating admin route logs an admin action."""

    @pytest.mark.smoke
    def test_every_mutating_route_logs(self, app):
        offenders: list[str] = []
        for rule, methods in _admin_mutating_rules(app):
            if rule.endpoint in AUDIT_LOG_WHITELIST:
                continue
            source = _view_source(app, rule.endpoint)
            uses_helper = 'log_admin_action(' in source
            uses_decorator = '@admin_audit_required' in source or 'admin_audit_required(' in source
            if not (uses_helper or uses_decorator):
                offenders.append(
                    f'{rule.endpoint} ({sorted(methods)} {rule.rule}): '
                    f'no log_admin_action / @admin_audit_required call found.'
                )
        assert not offenders, (
            'Mutating admin endpoints missing audit-log coverage. '
            'Add log_admin_action(...) (or decorate with @admin_audit_required) '
            'to each, or document the exemption in AUDIT_LOG_WHITELIST.\n'
            + '\n'.join(offenders)
        )

    def test_action_names_follow_entity_action_pattern(self, app):
        """Captured action strings must follow the ``entity.action`` style."""
        bad_actions: list[str] = []
        seen: set[tuple[str, str]] = set()
        for rule, _methods in _admin_mutating_rules(app):
            source = _view_source(app, rule.endpoint)
            for action in _extract_action_literals(source):
                if not ACTION_NAME_RE.match(action):
                    key = (rule.endpoint, action)
                    if key not in seen:
                        seen.add(key)
                        bad_actions.append(f'{rule.endpoint}: {action!r}')
        assert not bad_actions, (
            'Audit action names must match `entity.action` snake_case '
            '(e.g. "user.delete", "book_course.update"). Offenders:\n'
            + '\n'.join(bad_actions)
        )


def _extract_action_literals(source: str) -> list[str]:
    """Return string-literal action ids passed to log_admin_action(...) calls.

    Variables and f-strings are skipped — only literal action ids participate
    in the naming-convention guard.
    """
    try:
        tree = ast.parse(inspect.cleandoc(source))
    except SyntaxError:
        return []
    literals: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name != 'log_admin_action':
            continue
        action_node = None
        for kw in node.keywords:
            if kw.arg == 'action':
                action_node = kw.value
                break
        if action_node is None and len(node.args) >= 2:
            action_node = node.args[1]
        if isinstance(action_node, ast.Constant) and isinstance(action_node.value, str):
            literals.append(action_node.value)
    return literals


def _make_admin(db_session):
    suffix = uuid.uuid4().hex[:8]
    admin = User(
        username=f'audit_cov_admin_{suffix}',
        email=f'audit_cov_admin_{suffix}@example.com',
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
        username=f'audit_cov_target_{suffix}',
        email=f'audit_cov_target_{suffix}@example.com',
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
class TestAuditLogRuntimeCoverage:
    """Hit a representative slice of mutating endpoints and verify audit rows."""

    def test_toggle_user_status_writes_audit_row(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = client.post(f'/admin/users/{target.id}/toggle_status', follow_redirects=False)
        assert resp.status_code in (302, 303)

        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(admin_id=admin.id, target_type='user', target_id=target.id)
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.action in ('user.activate', 'user.deactivate')

    def test_grant_admin_writes_audit_row(self, app, client, db_session):
        admin = _make_admin(db_session)
        target = _make_target_user(db_session)
        db_session.commit()
        _login(client, admin)

        resp = client.post(f'/admin/users/{target.id}/toggle_admin', follow_redirects=False)
        assert resp.status_code in (302, 303)

        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(admin_id=admin.id, target_type='user', target_id=target.id)
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert entry is not None
        assert entry.action in ('user.grant_admin', 'user.revoke_admin')

    def test_system_clear_cache_writes_audit_row(self, app, client, db_session):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)

        resp = client.post(
            '/admin/system/clear-cache',
            data={'confirm': 'CLEAR_CACHE'},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(admin_id=admin.id, action='system.clear_cache')
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert entry is not None

    def test_seo_refresh_cache_writes_audit_row(self, app, client, db_session):
        admin = _make_admin(db_session)
        db_session.commit()
        _login(client, admin)

        resp = client.post('/admin/seo/refresh', follow_redirects=False)
        assert resp.status_code in (302, 303)

        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(admin_id=admin.id, action='seo.refresh_cache')
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert entry is not None

    def test_curriculum_lesson_delete_writes_audit_row(
        self, app, client, db_session, test_lesson_vocabulary
    ):
        admin = _make_admin(db_session)
        db_session.commit()
        lesson_id = test_lesson_vocabulary.id
        _login(client, admin)

        resp = client.post(
            f'/admin/curriculum/lessons/{lesson_id}/delete',
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

        entry = (
            db.session.query(AdminAuditLog)
            .filter_by(
                admin_id=admin.id,
                action='curriculum.lesson.delete',
                target_type='lesson',
                target_id=lesson_id,
            )
            .first()
        )
        assert entry is not None
