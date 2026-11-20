"""Repeated menu checks share a request-local read; access guards remain live."""
from uuid import uuid4

import pytest
from flask import g
from flask_login import AnonymousUserMixin
from sqlalchemy import event

from app.modules.models import SystemModule, UserModule
from app.modules.service import ModuleService
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def grant(user):
    module = SystemModule(code="nav-" + uuid4().hex[:12], name="Navigation fixture", is_active=True)
    db.session.add(module)
    db.session.flush()
    db.session.add(UserModule(user_id=user.id, module_id=module.id, is_enabled=True))
    db.session.commit()
    return module


def test_many_navigation_checks_use_one_joined_query(native_app):
    user, _ = learner(native_app)
    module = grant(user)
    code = module.code
    statements = []
    def listener(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    with native_app.test_request_context("/profile"):
        g._login_user = user
        event.listen(db.engine, "before_cursor_execute", listener)
        try:
            for _ in range(20):
                assert native_app.jinja_env.globals["has_module"](code)
                assert not native_app.jinja_env.globals["has_module"]("absent-module")
                assert native_app.jinja_env.globals["get_user_modules"]()
        finally:
            event.remove(db.engine, "before_cursor_execute", listener)
    selects = [statement for statement in statements if "system_modules" in statement]
    assert len(selects) == 1


def test_new_request_sees_revocation_and_route_checks_are_not_cached(native_app):
    user, _ = learner(native_app)
    module = grant(user)
    with native_app.test_request_context("/profile"):
        g._login_user = user
        assert native_app.jinja_env.globals["has_module"](module.code)
        assert ModuleService.revoke_module_from_user(user.id, module.id)
        # Presentation cache must never become an authorization cache.
        assert not ModuleService.is_module_enabled_for_user(user.id, module.code)
    with native_app.test_request_context("/profile"):
        g._login_user = user
        assert not native_app.jinja_env.globals["has_module"](module.code)


def test_navigation_cache_never_crosses_account_identity(native_app):
    owner, _ = learner(native_app)
    other, _ = learner(native_app)
    module = grant(owner)
    with native_app.test_request_context("/profile"):
        g._login_user = owner
        assert native_app.jinja_env.globals["has_module"](module.code)
        g._login_user = other
        assert not native_app.jinja_env.globals["has_module"](module.code)
        g._login_user = AnonymousUserMixin()
        assert not native_app.jinja_env.globals["has_module"](module.code)
        assert native_app.jinja_env.globals["get_user_modules"]() == []
