"""A content moderator can correct exercises without account-management access."""
from importlib import import_module
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import scoped_session
from werkzeug.datastructures import MultiDict

from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.telegram.models import TelegramUser
from tests.admin.test_content_package_routes import (
    APPLY, INDEX, _page, _preview_id, _updated, _upload, finals, staged_files,
)
from app.curriculum.models import Lessons


def sign_in(client: FlaskClient, user: User) -> None:
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True


def test_admin_grants_and_revokes_exact_state_once(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    target = f'/admin/users/{test_user.id}/moderator'
    detail = f'/admin/users/{test_user.id}'
    original = BeautifulSoup(admin_client.get(detail).data, 'html.parser')
    csrf = original.select_one(f'form[action="{target}"] input[name="csrf_token"]')['value']
    denied = admin_client.post(target, data={'is_moderator': '1'}, headers={'Accept': 'application/json'})
    assert denied.status_code == 400 and denied.json['csrf_expired']
    def set_role(value: str) -> int:
        return admin_client.post(target, data={'is_moderator': value, 'csrf_token': csrf}).status_code

    assert set_role('true') == 400 and not test_user.can_edit_content
    duplicate = MultiDict([('csrf_token', csrf), ('is_moderator', '1'), ('is_moderator', '0')])
    assert admin_client.post(target, data=duplicate).status_code == 400
    assert set_role('1') == set_role('1') == 303
    assert test_user.is_moderator and test_user.can_edit_content and not test_user.is_admin
    assert 'Снять роль модератора контента' in admin_client.get(detail).text
    assert test_user.username in admin_client.get('/admin/users?role=moderator').text

    account = app.test_client()
    sign_in(account, test_user)
    assert 'Модерация заданий' in account.get('/profile').text
    assert account.get(INDEX).status_code == 200
    for path in ('/admin/users', '/admin/users/export', '/admin/settings', '/admin/audit-log'):
        assert account.get(path).status_code != 200, path

    sign_in(admin_client, admin_user)
    assert set_role('0') == set_role('0') == 303
    assert not test_user.can_edit_content and not test_user.is_admin
    actions = AdminAuditLog.query.filter_by(admin_id=admin_user.id, target_type='user', target_id=test_user.id)
    assert [entry.action for entry in actions.order_by(AdminAuditLog.id)] == ['user.grant_moderator', 'user.revoke_moderator']
    sign_in(account, test_user)
    assert account.get(INDEX).status_code in (302, 403)
    assert 'Модерация заданий' not in account.get('/profile').text


def test_moderator_scope_and_revocation_between_preview_and_apply(
    app: Flask, client: FlaskClient, test_user: User, admin_user: User, db_session: scoped_session,
    staged_files: Path, finals: list[Lessons],  # noqa: F811
) -> None:
    test_user.is_moderator = True
    db_session.add(TelegramUser(user_id=test_user.id, telegram_id=test_user.id + 10000000, is_active=True))
    db_session.commit()
    assert not TelegramUser.active_admin_links().filter(TelegramUser.user_id == test_user.id).first()
    sign_in(client, test_user)
    forbidden = client.post(f'/admin/users/{test_user.id}/moderator', data={'is_moderator': '1'})
    assert forbidden.status_code in (302, 403)
    assert client.post(f'/admin/users/{test_user.id}/toggle_admin').status_code in (302, 403)
    assert not test_user.is_admin

    lesson = finals[0]
    new = _updated(lesson)
    token = _preview_id(_page(client, _upload(client, {'final.json': new})))
    response = client.post(APPLY, data={'preview_id': token})
    assert response.status_code == 303
    assert lesson.content == new
    token = _preview_id(_page(client, _upload(client, {'final.json': _updated(lesson, 'Other text')})))
    manager = app.test_client()
    sign_in(manager, admin_user)
    assert manager.post(f'/admin/users/{test_user.id}/moderator', data={'is_moderator': '0'}).status_code == 303
    sign_in(client, test_user)
    assert client.post(APPLY, data={'preview_id': token}).status_code in (302, 403)
    assert lesson.content == new
    assert AdminAuditLog.query.filter_by(admin_id=test_user.id, action='content_package.apply').count() == 1
    assert not AdminAuditLog.query.filter_by(admin_id=test_user.id, target_type='user').count()


@pytest.mark.parametrize('active,is_admin,is_moderator,expected', [
    (True, False, False, False), (True, True, False, True), (True, False, True, True), (True, True, True, True),
    (False, True, True, False), (None, False, True, False),
])
def test_content_editor_requires_active_account(
    active: bool | None, is_admin: bool, is_moderator: bool, expected: bool,
) -> None:
    assert User(active=active, is_admin=is_admin, is_moderator=is_moderator).can_edit_content is expected


def test_migration_leaves_existing_and_future_accounts_unprivileged() -> None:
    migration = import_module('migrations.versions.20261125_content_moderator')
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as conn:
            users = Table('users', MetaData(), Column('id', Integer, primary_key=True))
            users.create(conn)
            conn.execute(users.insert().values(id=1))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            users = Table('users', MetaData(), autoload_with=conn)
            conn.execute(users.insert().values(id=2))
            assert conn.execute(select(users.c.is_moderator).order_by(users.c.id)).scalars().all() == [False, False]
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            assert [field['name'] for field in inspect(conn).get_columns('users')] == ['id']
    finally:
        engine.dispose()
