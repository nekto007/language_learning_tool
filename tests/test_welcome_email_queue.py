"""Welcome mail is transactional at signup and delivered by the scheduler."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import current_app, has_app_context, has_request_context
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import welcome_email as queue
from app.auth.models import User
from app.utils.db import db


@pytest.fixture(autouse=True)
def clean_welcome_queue(request):
    if 'committed_welcome_job' in request.fixturenames:
        return  # These tests manage real commits and cleanup independently.
    db_session = request.getfixturevalue('db_session')
    # Registration tests may have left legitimate pending mail in this test DB.
    queue.WelcomeEmail.query.delete()
    db_session.commit()


@pytest.fixture
def welcome_job(db_session, test_user):
    job = queue.enqueue_welcome_email(test_user)
    db_session.commit()
    return job


@pytest.fixture
def committed_welcome_job(app):
    """Expose a real committed job to separate worker/database connections."""
    engine = db.engine
    with Session(engine) as session:
        session.execute(delete(queue.WelcomeEmail))
        username = f'welcome_worker_{uuid4().hex[:12]}'
        user = User(username=username, email=f'{username}@example.com', active=True)
        user.set_password('test')
        session.add(user)
        session.flush()
        job = queue.WelcomeEmail(user_id=user.id)
        session.add(job)
        session.flush()
        record = {'id': job.id, 'user_id': user.id, 'email': user.email, 'username': username}
        session.commit()
    try:
        yield record
    finally:
        with Session(engine) as session:
            session.execute(delete(queue.WelcomeEmail).where(queue.WelcomeEmail.id == record['id']))
            session.execute(delete(User).where(User.id == record['user_id']))
            session.commit()


def _run_worker_in_app_context(app):
    with app.app_context():
        return queue.run_welcome_email_job()


def test_enqueue_does_not_send_or_commit(db_session, test_user):
    with patch.object(queue.email_sender, 'send_email') as send, \
            patch.object(db_session, 'commit', wraps=db_session.commit) as commit:
        job = queue.enqueue_welcome_email(test_user)
        assert queue.enqueue_welcome_email(test_user) is job
        assert job in db_session.new
        send.assert_not_called()
        commit.assert_not_called()
        db_session.flush()
        assert job.status == 'pending'
        assert job.attempts == 0
        assert queue.WelcomeEmail.query.filter_by(user_id=test_user.id).count() == 1


def test_enqueue_requires_flushed_user():
    with pytest.raises(ValueError, match='Flush'):
        queue.enqueue_welcome_email(User(username='unflushed'))


def test_worker_sends_once_from_app_context(app, committed_welcome_job, monkeypatch):
    monkeypatch.setitem(app.config, 'SITE_URL', 'https://learn.example.com/')

    def deliver(**kwargs):
        assert has_app_context()
        assert not has_request_context()
        assert not db.session().in_transaction()
        assert kwargs['to_email'] == committed_welcome_job['email']
        assert kwargs['template_name'] == 'welcome'
        assert kwargs['context'] == {
            'username': committed_welcome_job['username'],
            'dashboard_url': 'https://learn.example.com/onboarding',
        }
        assert kwargs['timeout'] == queue.SMTP_TIMEOUT_SECONDS
        assert kwargs['standalone'] is True
        # A fresh app context has a separate DB session, like another worker.
        with app.app_context():
            assert queue._claim_next() is None
        return True

    with patch.object(queue.email_sender, 'send_email', side_effect=deliver) as send:
        # pytest-flask pushes a request context in the test thread. A fresh
        # thread models APScheduler's app-context-only environment faithfully.
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(_run_worker_in_app_context, app).result(timeout=10) == 1
            assert executor.submit(_run_worker_in_app_context, app).result(timeout=10) == 0
        send.assert_called_once()
    with Session(db.engine) as session:
        job = session.get(queue.WelcomeEmail, committed_welcome_job['id'])
        assert job.status == 'sent'
        assert job.attempts == 1
        assert job.sent_at is not None
        assert job.locked_at is None


def test_worker_renders_real_templates_without_request_context(app, committed_welcome_job, monkeypatch):
    monkeypatch.setitem(app.config, 'SITE_URL', 'https://learn.example.com/')
    monkeypatch.setattr(queue.email_sender, 'email_host', 'smtp.example.com')
    monkeypatch.setattr(queue.email_sender, 'default_from_email', 'noreply@example.com')
    monkeypatch.setattr(queue.email_sender, 'email_user', None)
    monkeypatch.setattr(queue.email_sender, 'email_password', None)
    monkeypatch.setattr(queue.email_sender, 'use_tls', False)

    def accept_message(message):
        assert has_app_context()
        assert not has_request_context()
        assert not db.session().in_transaction()
        assert message['To'] == committed_welcome_job['email']
        parts = {part.get_content_type(): part for part in message.get_payload()}
        assert set(parts) == {'text/plain', 'text/html'}
        for part in parts.values():
            body = part.get_payload(decode=True).decode(part.get_content_charset())
            assert committed_welcome_job['username'] in body
            assert 'https://learn.example.com/onboarding' in body

    with patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        transport = smtp.return_value.__enter__.return_value
        transport.send_message.side_effect = accept_message
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(_run_worker_in_app_context, app).result(timeout=10) == 1
        smtp.assert_called_once_with('smtp.example.com', queue.email_sender.email_port,
                                     timeout=queue.SMTP_TIMEOUT_SECONDS)
        transport.send_message.assert_called_once()
    with Session(db.engine) as session:
        job = session.get(queue.WelcomeEmail, committed_welcome_job['id'])
        assert job.status == 'sent'
        assert job.sent_at is not None


def test_worker_uses_canonical_fallback(app, welcome_job, monkeypatch):
    monkeypatch.setitem(app.config, 'SITE_URL', '')
    with patch.object(queue.email_sender, 'send_email', return_value=True) as send:
        queue.run_welcome_email_job()
    assert send.call_args.kwargs['context']['dashboard_url'] == 'https://llt-english.com/onboarding'


@pytest.mark.parametrize('raises', [False, True])
def test_failures_retry_after_backoff(db_session, welcome_job, raises):
    now = queue._utcnow()
    with patch.object(queue, '_utcnow', return_value=now), \
            patch.object(queue.email_sender, 'send_email', return_value=False,
                         side_effect=RuntimeError('mail unavailable') if raises else None) as send:
        assert queue.run_welcome_email_job() == 0
        assert queue.run_welcome_email_job() == 0
        send.assert_called_once()
    db_session.refresh(welcome_job)
    assert welcome_job.status == 'pending'
    assert welcome_job.attempts == 1
    assert welcome_job.available_at == now + timedelta(seconds=30)
    assert welcome_job.locked_at is None

    with patch.object(queue, '_utcnow', return_value=now + timedelta(seconds=30)), \
            patch.object(queue.email_sender, 'send_email', return_value=True):
        assert queue.run_welcome_email_job() == 1
    db_session.refresh(welcome_job)
    assert welcome_job.attempts == 2
    assert welcome_job.status == 'sent'


def test_final_failure_is_not_retried(db_session, welcome_job):
    welcome_job.attempts = queue.MAX_ATTEMPTS - 1
    db_session.commit()
    with patch.object(queue.email_sender, 'send_email', return_value=False) as send:
        queue.run_welcome_email_job()
        queue.run_welcome_email_job()
        send.assert_called_once()
    db_session.refresh(welcome_job)
    assert welcome_job.status == 'failed'
    assert welcome_job.attempts == queue.MAX_ATTEMPTS


@pytest.mark.parametrize('attempts,expected_status,send_count', [
    (1, 'sent', 1), (queue.MAX_ATTEMPTS, 'failed', 0),
])
def test_stale_claim_is_recovered(db_session, welcome_job, attempts, expected_status, send_count):
    welcome_job.status = 'sending'
    welcome_job.attempts = attempts
    welcome_job.locked_at = queue._utcnow() - queue.CLAIM_TTL - timedelta(seconds=1)
    db_session.commit()
    with patch.object(queue.email_sender, 'send_email', return_value=True) as send:
        queue.run_welcome_email_job()
        assert send.call_count == send_count
    db_session.refresh(welcome_job)
    assert welcome_job.status == expected_status
    assert welcome_job.locked_at is None


def test_fresh_claim_is_not_reclaimed(db_session, welcome_job):
    welcome_job.status = 'sending'
    welcome_job.attempts = 1
    welcome_job.locked_at = queue._utcnow()
    db_session.commit()
    with patch.object(queue.email_sender, 'send_email') as send:
        assert queue.run_welcome_email_job() == 0
        send.assert_not_called()


def test_locked_job_is_skipped(app, committed_welcome_job):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Row locking requires PostgreSQL')
    with ThreadPoolExecutor(max_workers=1) as executor, \
            patch.object(queue.email_sender, 'send_email', return_value=True) as send:
        # A separate committed connection owns the lock while the worker uses
        # its own session. Release the lock before executor shutdown on failure.
        with db.engine.begin() as connection:
            assert connection.execute(
                select(queue.WelcomeEmail.id)
                .where(queue.WelcomeEmail.id == committed_welcome_job['id'])
                .with_for_update()
            ).scalar_one() == committed_welcome_job['id']
            assert executor.submit(_run_worker_in_app_context, app).result(timeout=5) == 0
            send.assert_not_called()
        # The same job becomes claimable immediately after the lock releases.
        assert executor.submit(_run_worker_in_app_context, app).result(timeout=5) == 1
        send.assert_called_once()


def test_old_worker_cannot_finish_replacement_claim(db_session, welcome_job):
    old_claim = queue._claim_next()
    welcome_job.locked_at = old_claim[2] - queue.CLAIM_TTL - timedelta(seconds=1)
    db_session.commit()
    new_claim = queue._claim_next()
    queue._finish_claim(old_claim[0], old_claim[2], old_claim[3], sent=True)
    db_session.refresh(welcome_job)
    assert welcome_job.status == 'sending'
    assert welcome_job.locked_at == new_claim[2]
    assert welcome_job.attempts == 2


def test_inactive_user_is_not_sent(db_session, test_user, welcome_job):
    test_user.active = False
    db_session.commit()
    with patch.object(queue.email_sender, 'send_email') as send:
        assert queue.run_welcome_email_job() == 0
        send.assert_not_called()
    db_session.refresh(welcome_job)
    assert welcome_job.status == 'failed'


def test_deleted_user_cascades_queue(db_session, test_user, welcome_job):
    job_id = welcome_job.id
    db_session.execute(delete(User).where(User.id == test_user.id))
    db_session.commit()
    assert queue.WelcomeEmail.query.filter_by(id=job_id).first() is None


def test_worker_batch_is_bounded(db_session, welcome_job, monkeypatch):
    second = User(username=f'{welcome_job.user_id}_second_welcome', email='second-welcome@example.com')
    second.set_password('test')
    db_session.add(second)
    db_session.flush()
    queue.enqueue_welcome_email(second)
    db_session.commit()
    monkeypatch.setattr(queue, 'BATCH_SIZE', 1)
    with patch.object(queue.email_sender, 'send_email', return_value=True) as send:
        assert queue.run_welcome_email_job(batch_size=1000) == 1
        send.assert_called_once()
    assert queue.WelcomeEmail.query.filter_by(status='pending').count() == 1


def test_scheduler_runs_welcome_job_with_context_and_cleanup(app, monkeypatch):
    from app import email_scheduler

    scheduler = MagicMock()
    monkeypatch.setattr(email_scheduler, '_scheduler', None)
    monkeypatch.setattr(email_scheduler, 'BackgroundScheduler', lambda: scheduler)
    email_scheduler.init_email_scheduler(app)
    calls = {call.kwargs['id']: call for call in scheduler.add_job.call_args_list}
    assert {'welcome_emails', 'reengagement_emails', 'lesson_progress_reconcile'} <= calls.keys()
    welcome = calls['welcome_emails']
    assert welcome.args[1] == 'interval'
    assert welcome.kwargs['seconds'] == 30
    assert welcome.kwargs['max_instances'] == 1
    assert welcome.kwargs['coalesce'] is True

    def fail_in_context():
        assert current_app._get_current_object() is app
        raise RuntimeError('temporary worker failure')

    with patch.object(queue, 'run_welcome_email_job', side_effect=fail_in_context), \
            patch.object(db.session, 'remove') as remove, \
            patch.object(db.session, 'rollback') as rollback:
        welcome.args[0]()
        rollback.assert_called_once()
        assert remove.call_count >= 1
    scheduler.start.assert_called_once()


def test_smtp_timeout_is_forwarded():
    from app.utils.email_utils import EmailSender

    sender = EmailSender()
    sender.email_host = 'smtp.example.com'
    sender.default_from_email = 'noreply@example.com'
    with patch('app.utils.email_utils.render_template', return_value='welcome'), \
            patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        assert sender.send_email('Welcome', 'new@example.com', 'welcome', timeout=15)
        smtp.assert_called_once_with('smtp.example.com', sender.email_port, timeout=15)
