"""Admin reminders run against disposable data; all Telegram delivery is mocked."""
from datetime import timedelta
import pytest
from tests.api.test_account_deletion import native_app, administrator, submit
from tests.api.test_native_full_integration import learner


@pytest.fixture(autouse=True)
def clean_notices(native_app, monkeypatch):
    from app.auth.account_deletion import AccountDeletionRequest
    from app.auth.mobile_models import MobileAuthThrottle
    from app.auth.models import User
    from app.notifications.models import Notification
    from app.utils.db import db
    User.query.update({'is_admin': False}, synchronize_session=False)
    AccountDeletionRequest.query.delete(synchronize_session=False)
    Notification.query.delete(synchronize_session=False)
    MobileAuthThrottle.query.delete(synchronize_session=False)
    db.session.commit()
    monkeypatch.setitem(native_app.config, 'TELEGRAM_BOT_TOKEN', None)


def pending(app):
    from app.auth.account_deletion import AccountDeletionRequest
    from app.utils.db import db
    user, headers = learner(app)
    value = submit(app, headers)
    return user, headers, db.session.get(AccountDeletionRequest, value['id'])


def inbox(admin):
    from app.notifications.models import Notification
    return Notification.query.filter_by(user_id=admin.id, type='account_deletion').order_by(Notification.id).all()


def test_all_milestones_reach_active_admins_once_and_never_delete_user(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    from app.auth.models import User
    from app.utils.db import db
    user, _, row = pending(native_app); uid = user.id
    a = administrator(native_app); b = administrator(native_app)
    inactive = administrator(native_app); inactive.active = False; db.session.commit()
    start = row.requested_at
    calls = []
    monkeypatch.setattr(notices, '_telegram', lambda ids, title, body, link: calls.append((ids,title,body,link)))
    for day, expected in [(0,1),(0,0),(7,1),(7,0),(12,1),(13,0),(14,1),(14.9,0),(15,1)]:
        now = start + timedelta(days=day, seconds=1)
        monkeypatch.setattr(notices, 'utcnow', lambda: now)
        assert notices.process_admin_deletion_notices() == expected
    assert len(inbox(a)) == len(inbox(b)) == 5
    assert not inbox(inactive) and not inbox(user)
    assert len(calls) == 5
    assert all(set(ids)=={a.id,b.id} for ids,*_ in calls)
    for item in inbox(a):
        assert row.id in item.link
        assert user.username not in item.message and user.email not in item.message
        assert 'tracking_token' not in item.link
    assert db.session.get(User,uid) is not None
    assert row.status == 'pending'


def test_cancelled_and_completed_requests_stop_future_reminders(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    from app.auth.account_deletion import complete_account_deletion
    from app.utils.db import db
    admin = administrator(native_app)
    user, headers, row = pending(native_app)
    assert notices.process_admin_deletion_notices() == 1
    response = native_app.test_client().post('/api/mobile/auth/account/deletion/cancel',
        headers=headers, json={'request_id':row.id})
    assert response.status_code == 200
    row.admin_notice_after = row.requested_at; db.session.commit()
    assert notices.process_admin_deletion_notices() == 0
    other, _, completed = pending(native_app)
    assert notices.process_admin_deletion_notices() == 1
    from tests.api.test_account_deletion import age_request
    completed = age_request(completed.id)
    complete_account_deletion(completed.id, admin)
    completed.admin_notice_after = completed.requested_at; db.session.commit()
    assert notices.process_admin_deletion_notices() == 0
    assert len(inbox(admin)) == 2


def test_no_admin_keeps_notice_due_and_telegram_failure_cannot_lose_or_repeat_inbox_notice(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    user, _, row = pending(native_app)
    before = row.admin_notice_after
    assert notices.process_admin_deletion_notices() == 0
    assert row.admin_notice_after == before
    admin = administrator(native_app)
    def unavailable(*args): raise RuntimeError('fake Telegram outage')
    monkeypatch.setattr(notices, '_telegram', unavailable)
    assert notices.process_admin_deletion_notices() == 1
    assert len(inbox(admin)) == 1
    assert notices.process_admin_deletion_notices() == 0
    assert len(inbox(admin)) == 1


def test_inbox_transaction_failure_preserves_notice_for_retry(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    from app.utils.db import db
    _, _, row = pending(native_app); admin = administrator(native_app)
    original = notices.create_notification
    def failed(**kwargs):
        original(**kwargs)
        raise RuntimeError('fake database failure')
    monkeypatch.setattr(notices, 'create_notification', failed)
    with pytest.raises(RuntimeError): notices.process_admin_deletion_notices()
    db.session.rollback()
    assert not inbox(admin)
    assert row.admin_notice_after <= notices.utcnow()
    monkeypatch.setattr(notices, 'create_notification', original)
    assert notices.process_admin_deletion_notices() == 1
    assert len(inbox(admin)) == 1


def test_worker_resumes_with_only_current_urgency_after_long_outage(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    _, _, row = pending(native_app); admin = administrator(native_app)
    now = row.requested_at + timedelta(days=18)
    monkeypatch.setattr(notices, 'utcnow', lambda: now)
    assert notices.process_admin_deletion_notices() == 1
    assert inbox(admin)[0].title == 'Просрочена заявка на удаление аккаунта'
    assert row.admin_notice_after == now + timedelta(days=1)
    assert notices.process_admin_deletion_notices() == 0


def test_telegram_only_reaches_active_linked_admins_and_uses_configured_origin(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    from app.telegram.models import TelegramUser
    from app.telegram import bot
    from app.utils.db import db
    user, _, row = pending(native_app)
    good = administrator(native_app); unlinked = administrator(native_app)
    inactive = administrator(native_app); inactive.active = False
    paused = administrator(native_app)
    for index, (account, active) in enumerate([(good,True),(user,True),(inactive,True),(paused,False)],start=10001):
        db.session.add(TelegramUser(user_id=account.id, telegram_id=index, is_active=active))
    db.session.commit()
    monkeypatch.setitem(native_app.config,'TELEGRAM_BOT_TOKEN','fake-test-token')
    monkeypatch.setitem(native_app.config,'SITE_URL','https://learn.example.test')
    sent=[]
    monkeypatch.setattr(bot,'send_message',lambda *args,**kwargs: sent.append((args,kwargs)))
    assert notices.process_admin_deletion_notices() == 1
    assert len(sent) == 1 and sent[0][0][0] == 10001
    message = sent[0][0][1]
    assert 'https://learn.example.test/admin/account-deletions?request_id=' + row.id in message
    assert user.username not in message and user.email not in message
    assert len(inbox(unlinked)) == 1


def test_admin_notice_link_filters_queue_and_postgresql_locks_only_request_table(native_app, monkeypatch):
    from app.auth import account_deletion_notifications as notices
    from app.utils.db import db
    from sqlalchemy.dialects import postgresql
    from flask import g
    user, _, row = pending(native_app); other, _, another = pending(native_app)
    admin = administrator(native_app)
    session = db.session()
    captured=[]; original=session.execute
    def inspect_lock(statement,*args,**kwargs):
        if getattr(statement,'_for_update_arg',None) is not None:
            sql=str(statement.compile(dialect=postgresql.dialect()))
            if 'account_deletion_requests' in sql:
                captured.append(sql)
                assert 'FOR UPDATE OF account_deletion_requests' in sql
        return original(statement,*args,**kwargs)
    monkeypatch.setattr(session,'execute',inspect_lock)
    assert notices.process_admin_deletion_notices() == 2
    assert captured and any('SKIP LOCKED' in sql for sql in captured)
    client=native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id']=admin.get_id();session['_fresh']=True
    g.pop('_login_user',None)
    response=client.get('/admin/account-deletions',query_string={'request_id':row.id})
    assert response.status_code==200
    page=response.get_data(as_text=True)
    assert user.username in page and other.username not in page
