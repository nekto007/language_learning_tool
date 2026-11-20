"""Confirmed existing-account links and revocable delegated sessions, on SQLite only."""
from datetime import timedelta, UTC

import pytest
from flask_jwt_extended import decode_token

from tests.api.test_native_full_integration import learner
from tests.api.test_account_deletion import native_app as _native_app
from app.family.models import FamilyInvitation, FamilyLink
from app.family.service import now
from app.utils.db import db


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def invite(app, headers, child):
    response = app.test_client().post('/api/family/invitations', headers=headers, json={'username': child.username})
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Set-Cookie' not in response.headers
    return response.json['invitation']['code']


def linked(app):
    parent, ph = learner(app)
    child, ch = learner(app)
    code = invite(app, ph, child)
    response = app.test_client().post('/api/family/accept', headers=ch, json={'code': code, 'consent': True})
    assert response.status_code == 200, response.json
    identifier = response.json['link_id']
    response = app.test_client().post(f'/api/family/members/{child.id}/session', headers=ph, json={})
    assert response.status_code == 200, response.json
    return parent, ph, child, ch, identifier, response.json


def test_invite_is_bound_to_child_and_requires_consent(native_app):
    parent, ph = learner(native_app)
    child, ch = learner(native_app)
    stranger, sh = learner(native_app)
    code = invite(native_app, ph, child)
    assert FamilyInvitation.query.filter_by(parent_id=parent.id).one().code_hash != code
    client = native_app.test_client()
    for headers, body in [(sh, {'code': code, 'consent': True}), (ch, {'code': code, 'consent': False}), (ch, {'code': code})]:
        assert client.post('/api/family/accept', headers=headers, json=body).status_code == 400
    assert not FamilyLink.query.filter_by(parent_id=parent.id).first()
    assert client.post('/api/family/accept', headers=ch, json={'code': code, 'consent': True}).status_code == 200
    assert client.post('/api/family/accept', headers=ch, json={'code': code, 'consent': True}).status_code == 400
    assert not FamilyLink.query.filter_by(child_id=stranger.id).first()


def test_expired_invitation_and_password_change_reject_accept(native_app):
    for changed in ('expiry', 'child_password', 'parent_password'):
        parent, ph = learner(native_app)
        child, ch = learner(native_app)
        code = invite(native_app, ph, child)
        if changed == 'expiry':
            FamilyInvitation.query.filter_by(parent_id=parent.id).one().expires_at = now() - timedelta(seconds=1)
        else:
            (child if changed == 'child_password' else parent).set_password('changed-test-password')
        db.session.commit()
        # Fresh login after password change still cannot accept a stale grant.
        from app.utils.jwt_auth import create_tokens_for_user
        ch = {'Authorization': 'Bearer ' + create_tokens_for_user(child)['access_token']}
        assert native_app.test_client().post('/api/family/accept', headers=ch, json={'code': code, 'consent': True}).status_code == 400


def test_delegated_session_keeps_child_identity_and_scope_after_refresh(native_app):
    parent, _ph, child, _ch, identifier, tokens = linked(native_app)
    access = decode_token(tokens['access_token'])
    assert access['sub'] == str(child.id) and access['family_parent_id'] == parent.id
    assert access['family_link'] == identifier and access['is_admin'] is False and access['fresh'] is False
    client = native_app.test_client()
    response = client.post('/api/refresh', headers={'Authorization': 'Bearer ' + tokens['refresh_token']})
    assert response.status_code == 200, response.json
    renewed = decode_token(response.json['access_token'])
    assert renewed['sub'] == str(child.id) and renewed['family_link'] == identifier and renewed['fresh'] is False
    headers = {'Authorization': 'Bearer ' + response.json['access_token']}
    assert client.get('/api/family/session', headers=headers).json['child_id'] == child.id
    assert client.get('/api/native/courses', headers=headers).status_code == 200
    for method, path, body in [('get', '/api/family', None), ('post', '/api/family/invitations', {'username': 'x'}),
        ('post', '/api/mobile/auth/account/deletion/start', {}), ('post', '/api/native/plan/pause', {'days': 3}),
        ('get', '/api/native/push/settings', None), ('get', '/admin/', None), ('get', '/family', None),
        ('post', '/api/login', {}), ('get', '/api/books-admin', None), ('get', '/api/native/unknown', None)]:
        result = getattr(client, method)(path, headers=headers, json=body)
        assert result.status_code == 403, (path, result.json)
        assert result.json['error'] == 'family_session_restricted'


@pytest.mark.parametrize('side', ['parent', 'child'])
def test_unlink_revokes_access_and_refresh_and_retains_accounts(native_app, side):
    parent, ph, child, ch, identifier, tokens = linked(native_app)
    client = native_app.test_client()
    assert client.delete('/api/family/links/' + identifier, headers=ph if side == 'parent' else ch).status_code == 200
    headers = {'Authorization': 'Bearer ' + tokens['access_token']}
    assert client.get('/api/native/courses', headers=headers).status_code == 401
    assert client.post('/api/refresh', headers={'Authorization': 'Bearer ' + tokens['refresh_token']}).status_code == 401
    from app.auth.models import User
    assert db.session.get(User, child.id) and db.session.get(User, parent.id)
    assert client.get('/api/native/courses', headers=ch).status_code == 200
    # Re-linking never revives the old delegated grant.
    code = invite(native_app, ph, child)
    assert client.post('/api/family/accept', headers=ch, json={'code': code, 'consent': True}).status_code == 200
    assert client.get('/api/family/session', headers=headers).status_code == 401


@pytest.mark.parametrize('change', ['parent_password', 'child_password', 'parent_inactive', 'child_inactive', 'child_admin'])
def test_changed_credentials_or_account_state_revokes_grant(native_app, change):
    parent, _ph, child, _ch, _identifier, tokens = linked(native_app)
    target = parent if change.startswith('parent') else child
    if change.endswith('password'):
        target.set_password('new-private-test-password')
    elif change.endswith('inactive'):
        target.active = False
    else:
        target.is_admin = True
    db.session.commit()
    client = native_app.test_client()
    assert client.get('/api/family/session', headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code == 401
    assert client.post('/api/refresh', headers={'Authorization': 'Bearer ' + tokens['refresh_token']}).status_code == 401


def test_family_dashboard_is_private_and_read_only(native_app):
    parent, ph, child, ch, identifier, _tokens = linked(native_app)
    _other, oh = learner(native_app)
    from app.daily_plan.models import DailyPlanLog
    before = DailyPlanLog.query.count()
    client = native_app.test_client()
    value = client.get('/api/family', headers=ph).json
    assert value['members'][0]['id'] == child.id
    assert value['members'][0]['summary']['active_days'] == []
    assert value['members'][0]['summary']['day_secured'] is None
    assert 'email' not in str(value) and 'password' not in str(value)
    assert DailyPlanLog.query.count() == before
    assert client.get('/api/family', headers=oh).json['members'] == []
    assert client.get('/api/family', headers=ch).json['parent']['id'] == parent.id
    assert client.delete('/api/family/links/' + identifier, headers=oh).status_code == 404
    assert client.post(f'/api/family/members/{child.id}/session', headers=oh, json={}).status_code == 403


def test_no_cookie_only_api_and_web_csrf_remains_required(native_app):
    parent, _ph = learner(native_app)
    child, _ch = learner(native_app)
    parent.onboarding_completed = True
    db.session.commit()
    client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = parent.get_id()
        session['_fresh'] = True
    assert client.get('/api/family').status_code == 401
    assert client.post('/api/family/invitations', json={'username': child.username}).status_code in (400, 401)
    assert client.post('/family', data={'action': 'invite', 'username': child.username}).status_code in (302, 400)
    from flask import g
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]  # The module fixture retains an outer app context.
    response = client.get('/family')
    assert response.status_code == 200, response.headers.get("Location")
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'csrf_token' in response.text


def test_role_cycles_admin_targets_self_and_second_parent_are_rejected(native_app):
    parent, ph, child, ch, _identifier, _tokens = linked(native_app)
    another, ah = learner(native_app)
    client = native_app.test_client()
    for headers, target in [(ph, parent), (ch, another), (ah, child)]:
        assert client.post('/api/family/invitations', headers=headers, json={'username': target.username}).status_code in (400, 409)
    another.is_admin = True
    db.session.commit()
    assert client.post('/api/family/invitations', headers=ph, json={'username': another.username}).status_code == 400


def test_csrf_allowlist_includes_only_reviewed_bearer_mutations(native_app):
    from tests.security.test_csrf_sweep import test_exempt_views_allowlist
    test_exempt_views_allowlist(native_app)


def test_pending_deletion_revokes_delegation_but_allows_normal_family_management(native_app):
    from app.auth.account_deletion import AccountDeletionRequest
    _parent, ph, child, ch, identifier, tokens = linked(native_app)
    db.session.add(AccountDeletionRequest(user_id=child.id, earliest_deletion_at=now() + timedelta(days=7),
                                         latest_deletion_at=now() + timedelta(days=14)))
    db.session.commit()
    client = native_app.test_client()
    assert client.get('/api/native/courses', headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code == 401
    assert client.get('/api/family', headers=ph).json['members'][0]['summary'] is None
    assert client.delete('/api/family/links/' + identifier, headers=ch).status_code == 200


def test_web_child_can_confirm_and_revoke_on_phone_with_real_csrf(native_app):
    import re
    from flask import g
    parent, ph = learner(native_app)
    child, _ch = learner(native_app)
    code = invite(native_app, ph, child)
    client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = child.get_id()
        session['_fresh'] = True
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]
    response = client.get('/family')
    assert response.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]
    response = client.post('/family', data={'action': 'preview', 'code': code, 'csrf_token': csrf})
    assert response.status_code == 200 and parent.username in response.text
    assert not FamilyLink.query.filter_by(child_id=child.id).first()
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]
    response = client.post('/family', data={'action': 'accept', 'code': code, 'consent': 'yes', 'csrf_token': csrf})
    assert response.status_code == 303, (response.headers.get("Location"), response.text)
    link = FamilyLink.query.filter_by(child_id=child.id).one()
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]
    response = client.get('/family')
    assert parent.username in response.text and 'Отключить семейный доступ' in response.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    [g.pop(key, None) for key in ('_login_user', 'csrf_token', 'csrf_valid')]
    assert client.post('/family', data={'action': 'unlink', 'link_id': link.id, 'csrf_token': csrf}).status_code == 303
    assert not FamilyLink.query.filter_by(child_id=child.id).first()


def test_summary_respects_child_timezone_and_does_not_count_login_as_study(native_app):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.daily_plan.models import DailyPlanLog
    from app.study.models import StudySession
    from app.utils.time_utils import get_user_local_date
    _parent, ph, child, _ch, _identifier, _tokens = linked(native_app)
    child.timezone = 'Asia/Tokyo'
    today = datetime.now(UTC).astimezone(ZoneInfo(child.timezone)).date()
    first_local = datetime.combine(today - timedelta(days=6), datetime.min.time(), ZoneInfo(child.timezone))
    start = first_local.astimezone(UTC).replace(tzinfo=None)
    db.session.add_all([
        StudySession(user_id=child.id, start_time=start, end_time=start, words_studied=3),
        StudySession(user_id=child.id, start_time=start - timedelta(seconds=1), end_time=start - timedelta(seconds=1), words_studied=2),
        StudySession(user_id=child.id, start_time=now(), end_time=now(), words_studied=0),
        DailyPlanLog(user_id=child.id, plan_date=get_user_local_date(child.id, db), secured_at=now()),
    ])
    db.session.commit()
    summary = native_app.test_client().get('/api/family', headers=ph).json['members'][0]['summary']
    assert summary['active_days'] == [first_local.date().isoformat()]
    assert summary['today_active'] is False and summary['day_secured'] is True


def test_migration_upgrade_cascade_and_downgrade_are_reversible(tmp_path):
    import runpy
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    migration = runpy.run_path(str(Path(__file__).parents[2] / 'migrations/versions/20261120_family_accounts.py'))
    engine = create_engine('sqlite:///' + str(tmp_path / 'family-migration.db'))
    try:
        with engine.begin() as connection:
            connection.execute(text('PRAGMA foreign_keys=ON'))
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            with Operations.context(MigrationContext.configure(connection)):
                migration['upgrade']()
                assert set(inspect(connection).get_table_names()) == {'users', 'family_links', 'family_invitations'}
                connection.execute(text('INSERT INTO users VALUES (1), (2)'))
                connection.execute(text("INSERT INTO family_links VALUES (:id, 1, 2, 'p', 'c', CURRENT_TIMESTAMP)"), {'id': 'a' * 32})
                connection.execute(text('DELETE FROM users WHERE id=2'))
                assert connection.execute(text('SELECT count(*) FROM family_links')).scalar() == 0
                migration['downgrade']()
                assert inspect(connection).get_table_names() == ['users']
    finally:
        engine.dispose()
