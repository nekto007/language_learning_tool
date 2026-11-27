"""Real API/ORM reminder policy; no outbound Apple traffic."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import Flask

from tests.api.test_native_full_integration import learner


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    from app import create_app
    from app.utils.db import db
    from config.settings import Config
    folder = tmp_path_factory.mktemp('native-push-db')
    class PushConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(folder / 'push.db')
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = True
        RATELIMIT_ENABLED = False
        SERVER_NAME = 'localhost'
        MAIL_SUPPRESS_SEND = True
    application = create_app(config_class=PushConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.engine.dispose()

PREFIX = '/api/native/push'
NOW = datetime(2026, 11, 17, 9, 5, tzinfo=timezone.utc)


def installation():
    return dict(installation_id=str(uuid4()), installation_secret=uuid4().hex+uuid4().hex)


def enroll(app, *, hours=None):
    from app.utils.db import db
    user, headers = learner(app)
    user.timezone = 'UTC'
    db.session.commit()
    identity = installation()
    client = app.test_client()
    registration = dict(**identity, token=uuid4().hex+uuid4().hex, environment='sandbox')
    assert client.post(PREFIX+'/devices', headers=headers, json=registration).status_code == 200
    assert client.put(PREFIX+'/settings', headers=headers,
                      json=dict(enabled=True, hours=hours or [9, 15, 20])).status_code == 200
    return user, headers, identity, registration


@pytest.fixture(autouse=True)
def isolate_reminders(native_app):
    from app.notifications.push_models import PushDevice, PushDelivery, PushPreference
    from app.utils.db import db
    for model in (PushDelivery, PushDevice, PushPreference):
        model.query.delete()
    db.session.commit()
    keys = ('APNS_TEAM_ID', 'APNS_KEY_ID', 'APNS_PRIVATE_KEY')
    old = {key: native_app.config.get(key) for key in keys}
    native_app.config.update(dict.fromkeys(keys, 'test-only-not-a-real-key'))
    yield
    native_app.config.update(old)


class Sender:
    def __init__(self, result=None):
        from app.notifications.apns import PushResult
        self.result = result or PushResult(True)
        self.sent = []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def send(self, device, **payload):
        self.sent.append((device.id, payload))
        return self.result


def tick(sender, now=NOW):
    from app.notifications.push_scheduler import send_due_reminders
    return send_due_reminders(now=now, sender_factory=lambda: sender)


def test_opt_in_defaults_and_validation(native_app):
    user, headers = learner(native_app)
    client = native_app.test_client()
    response = client.get(PREFIX+'/settings', headers=headers)
    assert response.json['enabled'] is False
    assert response.json['hours'] == [9, 15, 20]
    assert response.headers['Cache-Control'] == 'private, no-store'
    for hours in ([9, 15], [9, 15, 22], [9, 15, 15], [9, 10, 20], [True, 15, 20], ['9', 15, 20], {}):
        assert client.put(PREFIX+'/settings', headers=headers, json=dict(enabled=True, hours=hours)).status_code == 400
    assert client.put(PREFIX+'/settings', headers=headers, json=dict(enabled=1, hours=[9,15,20])).status_code == 400
    assert client.put(PREFIX+'/settings', headers=headers, json=dict(enabled=True, hours=[8,14,21])).json['hours'] == [8,14,21]


def test_mutations_require_bearer_and_revoke_requires_device_secret(native_app):
    from app.notifications.push_models import PushDevice
    user, headers, identity, registration = enroll(native_app)
    client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for method, path, body in [('put', '/settings', dict(enabled=False, hours=[9,15,20])),
                               ('post', '/devices', registration), ('post', '/test', identity)]:
        assert getattr(client, method)(PREFIX+path, json=body).status_code == 401
    device = PushDevice.query.filter_by(id=identity['installation_id']).one()
    wrong = dict(identity, installation_secret='0'*64)
    assert client.post(PREFIX+'/revoke', json=wrong).status_code == 200
    assert device.active
    assert client.post(PREFIX+'/revoke', json=identity).status_code == 200
    assert not device.active
    assert tick(Sender()) == 0


def test_device_ownership_token_rotation_and_account_switch(native_app):
    from app.notifications.push_models import PushDevice
    user, headers, identity, registration = enroll(native_app)
    other, other_headers = learner(native_app)
    client = native_app.test_client()
    assert client.post(PREFIX+'/devices', headers=other_headers,
        json=dict(registration, installation_secret='1'*64)).status_code == 403
    assert client.post(PREFIX+'/test', headers=other_headers, json=identity).status_code == 404
    updated = dict(registration, token=uuid4().hex*2)
    assert client.post(PREFIX+'/devices', headers=headers, json=updated).status_code == 200
    assert PushDevice.query.filter_by(user_id=user.id).one().token == updated['token']
    assert client.post(PREFIX+'/devices', headers=other_headers, json=updated).status_code == 200
    assert PushDevice.query.filter_by(id=identity['installation_id']).one().user_id == other.id
    assert tick(Sender()) == 0  # other account never opted in


@pytest.mark.parametrize('change', [dict(token='broken'), dict(environment='other'), dict(installation_id='nope'), dict(installation_secret='short')])
def test_registration_rejects_bad_input(native_app, change):
    _, headers, _, registration = enroll(native_app)
    assert native_app.test_client().post(PREFIX+'/devices', headers=headers, json=dict(registration, **change)).status_code == 400


def test_three_windows_are_deduplicated_across_restarts_and_schedule_changes(native_app):
    from app.notifications.push_models import PushDelivery
    _, headers, _, _ = enroll(native_app)
    sender = Sender()
    for hour in (9, 15, 20):
        instant = NOW.replace(hour=hour)
        assert tick(sender, instant) == 1
        assert tick(sender, instant+timedelta(minutes=5)) == 0
    assert len(sender.sent) == 3
    assert PushDelivery.query.count() == 3
    assert all(p['account_key'].startswith('account:native_') for _, p in sender.sent)
    native_app.test_client().put(PREFIX+'/settings', headers=headers, json=dict(enabled=True,hours=[10,16,21]))
    assert tick(sender, NOW.replace(hour=21)) == 0
    assert tick(sender, NOW+timedelta(days=1)) == 0  # schedule now starts at 10
    assert tick(sender, NOW.replace(hour=10)+timedelta(days=1)) == 1


def test_first_real_study_stops_all_later_reminders_from_web_or_mobile(native_app):
    from app.study.models import StudySession
    from app.utils.db import db
    user, _, _, _ = enroll(native_app)
    sender = Sender()
    assert tick(sender) == 1
    db.session.add(StudySession(user_id=user.id, start_time=NOW.replace(hour=10,tzinfo=None)))
    db.session.commit()
    assert tick(sender, NOW.replace(hour=15)) == 0
    assert tick(sender, NOW.replace(hour=20)) == 0
    assert tick(sender, NOW+timedelta(days=1)) == 1


@pytest.mark.parametrize('suppression', ['disabled', 'paused', 'inactive', 'password_changed', 'stale_device', 'unconfigured'])
def test_suppression_policy(native_app, suppression):
    from app.notifications.push_models import PushDevice, PushPreference, PushDelivery
    from app.utils.db import db
    user, _, _, _ = enroll(native_app)
    if suppression == 'disabled': db.session.get(PushPreference,user.id).enabled = False
    elif suppression == 'paused': user.plan_paused_until = NOW.date()+timedelta(days=1)
    elif suppression == 'inactive': user.active = False
    elif suppression == 'password_changed': user.set_password('another-disposable-password')
    elif suppression == 'stale_device': PushDevice.query.filter_by(user_id=user.id).one().updated_at = NOW.replace(tzinfo=None)-timedelta(days=91)
    else: native_app.config['APNS_PRIVATE_KEY'] = ''
    db.session.commit()
    assert tick(Sender()) == 0
    assert PushDelivery.query.count() == 0


def test_timezone_study_day_and_no_backlog_outside_window(native_app):
    from app.study.models import StudySession
    from app.utils.db import db
    user, _, _, _ = enroll(native_app)
    user.timezone = 'Asia/Tokyo'
    # Local 01:00 belongs to yesterday's study day and must not suppress today.
    db.session.add(StudySession(user_id=user.id, start_time=NOW.replace(hour=16,tzinfo=None)-timedelta(days=1)))
    db.session.commit()
    sender = Sender()
    assert tick(sender, NOW.replace(hour=0)) == 1  # 09:05 local
    assert tick(sender, NOW.replace(hour=6, minute=30)) == 0  # 15:30, window over
    assert tick(sender, NOW.replace(hour=14)) == 0  # 23:05, quiet hours


@pytest.mark.parametrize(('from_zone', 'to_zone', 'first_tick', 'valid_tick', 'study_date'), [
    ('UTC', 'America/New_York', NOW, NOW.replace(hour=14), '2026-11-17'),
    ('Pacific/Honolulu', 'Pacific/Kiritimati', NOW.replace(hour=19), NOW.replace(hour=19), '2026-11-18'),
], ids=['same-key-later-window', 'same-hour-different-study-day'])
def test_zone_change_before_send_releases_old_claim(
    native_app: Flask, monkeypatch: pytest.MonkeyPatch, from_zone: str, to_zone: str,
    first_tick: datetime, valid_tick: datetime, study_date: str,
) -> None:
    from app.auth.models import User
    from app.notifications.push_models import PushDelivery
    from app.utils.db import db

    user, _, _, _ = enroll(native_app)
    user.timezone = from_zone
    db.session.commit()
    refresh = db.session.refresh
    changed = False

    def refresh_after_zone_change(row: object) -> None:
        nonlocal changed
        if isinstance(row, User) and not changed:
            assert PushDelivery.query.count() == 1
            row.timezone = to_zone
            db.session.flush()
            changed = True
        refresh(row)

    monkeypatch.setattr(db.session, 'refresh', refresh_after_zone_change)
    sender = Sender()
    assert tick(sender, first_tick) == 0
    assert changed and sender.sent == [] and PushDelivery.query.count() == 0

    assert tick(sender, valid_tick) == 1
    assert tick(sender, valid_tick + timedelta(minutes=5)) == 0
    assert len(sender.sent) == 1
    assert sender.sent[0][1]['collapse_id'] == f'study-{study_date}-0'
    claim = PushDelivery.query.one()
    assert (claim.study_date.isoformat(), claim.slot, claim.accepted) == (study_date, 0, 1)


def test_invalid_apns_device_is_deactivated_and_failure_does_not_duplicate(native_app):
    from app.notifications.apns import PushResult
    from app.notifications.push_models import PushDevice, PushDelivery
    _, _, identity, _ = enroll(native_app)
    sender = Sender(PushResult(False, True))
    assert tick(sender) == 0
    assert not db_device(identity).active
    assert PushDelivery.query.one().accepted == 0
    assert tick(sender) == 0
    assert len(sender.sent) == 1


def db_device(identity):
    from app.notifications.push_models import PushDevice
    return PushDevice.query.filter_by(id=identity['installation_id']).one()


def test_transient_apns_failure_consumes_window_but_next_window_remains(native_app):
    from app.notifications.apns import PushResult
    enroll(native_app)
    sender = Sender(PushResult(False))
    assert tick(sender) == tick(sender) == 0
    assert len(sender.sent) == 1
    sender.result = PushResult(True)
    assert tick(sender, NOW.replace(hour=15)) == 1


def test_resume_date_and_multiple_devices_share_one_user_window(native_app):
    from app.utils.db import db
    user, headers, _, _ = enroll(native_app)
    user.plan_paused_until = NOW.date()
    db.session.commit()
    second = dict(**installation(), token=uuid4().hex*2, environment='production')
    assert native_app.test_client().post(PREFIX+'/devices', headers=headers,json=second).status_code == 200
    sender = Sender()
    assert tick(sender) == 2
    assert tick(sender) == 0
    assert len(sender.sent) == 2


def test_native_linear_learning_event_stops_reminders(native_app):
    from app.achievements.models import StreakEvent
    from app.utils.db import db
    user, _, _, _ = enroll(native_app)
    db.session.add(StreakEvent(user_id=user.id, event_type='xp_linear_reading',
        event_date=NOW.date(), created_at=NOW.replace(hour=8, tzinfo=None)))
    db.session.commit()
    assert tick(Sender()) == 0


def test_test_push_is_owner_scoped_and_honest_about_unconfigured_server(native_app, monkeypatch):
    import app.api.native_push as routes
    user, headers, identity, _ = enroll(native_app)
    client = native_app.test_client()
    native_app.config['APNS_PRIVATE_KEY'] = ''
    assert client.post(PREFIX+'/test',headers=headers,json=identity).status_code == 503
    native_app.config['APNS_PRIVATE_KEY'] = 'test-only'
    sender = Sender()
    monkeypatch.setattr(routes, 'APNsClient', lambda: sender)
    response = client.post(PREFIX+'/test',headers=headers,json=identity)
    assert response.status_code == 200
    assert sender.sent[0][1]['is_test'] is True
    assert sender.sent[0][1]['account_key'] == 'account:'+user.username


def test_push_endpoints_keep_csrf_exemptions_explicit(native_app):
    from tests.security.test_csrf_sweep import test_exempt_views_allowlist
    test_exempt_views_allowlist(native_app)


def test_push_migration_upgrades_and_downgrades_without_touching_user_data(native_app):
    import runpy
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine('sqlite://')
    migration = runpy.run_path(str(Path(__file__).parents[2] / 'migrations/versions/20261117_mobile_push.py'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO users (id) VALUES (7)'))
        operations = Operations(MigrationContext.configure(connection))
        migration['upgrade'].__globals__['op'] = operations
        migration['upgrade']()
        assert set(inspect(connection).get_table_names()) == {'users', 'native_push_devices', 'native_push_preferences', 'native_push_deliveries'}
        assert inspect(connection).get_unique_constraints('native_push_deliveries')[0]['column_names'] == ['user_id','study_date','slot']
        migration['downgrade']()
        assert inspect(connection).get_table_names() == ['users']
        assert connection.execute(text('SELECT id FROM users')).scalar() == 7
    engine.dispose()


@pytest.mark.parametrize('status,reason,invalid', [(200,None,False),(410,'Unregistered',True),
    (400,'BadDeviceToken',True),(403,'ExpiredProviderToken',False),(429,'TooManyRequests',False)])
def test_apns_http2_signed_headers_payload_and_error_classification(native_app, monkeypatch, status, reason, invalid):
    import json
    import httpx
    import jwt
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from app.notifications.apns import APNsClient
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    native_app.config['APNS_PRIVATE_KEY'] = pem.replace('\n','\\n')
    seen = []
    client_class = httpx.Client
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={'reason':reason} if reason else {})
    def client(**kwargs):
        assert kwargs['http2'] is True and kwargs['trust_env'] is False
        return client_class(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    with APNsClient() as sender:
        result = sender.send(SimpleNamespace(token='ab'*32,environment='sandbox'),
            title='English',body='Start today',collapse_id='study-2026-11-17-0',
            expires_at=12345,account_key='account:learner')
    assert result.accepted == (status == 200)
    assert result.invalid_device is invalid
    request = seen[0]
    assert request.url.host == 'api.sandbox.push.apple.com'
    assert request.headers['apns-push-type'] == 'alert'
    assert request.headers['apns-topic'] == 'com.llt.english.ios'
    assert request.headers['apns-expiration'] == '12345'
    proof = request.headers['authorization'].removeprefix('bearer ')
    assert jwt.decode(proof, key.public_key(),algorithms=['ES256'])['iss'] == native_app.config['APNS_TEAM_ID']
    payload = json.loads(request.content)
    assert payload['account'] == 'account:learner' and payload['route'] == 'daily-plan'
    assert payload['aps']['alert']['body'] == 'Start today'
