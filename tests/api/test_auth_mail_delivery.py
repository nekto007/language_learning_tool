"""Submission metadata, retry/expiry boundaries and operational safety."""

import importlib.util
import json
import smtplib
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.api.test_native_full_integration import native_app as native_app
from tests.api.test_mobile_auth import start
from app.utils.email_utils import EmailSender, MailSubmission


@pytest.fixture(autouse=True)
def clear_throttle(native_app):
    from app.auth.mobile_models import MobileAuthThrottle
    from app.utils.db import db
    MobileAuthThrottle.query.delete()
    db.session.commit()


@pytest.fixture
def sender(monkeypatch):
    for key in ('AUTH_EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('EMAIL_HOST', 'smtp.example.invalid')
    monkeypatch.setenv('DEFAULT_FROM_EMAIL', 'LLT English <no-reply@example.invalid>')
    monkeypatch.setenv('EMAIL_USE_TLS', 'true')
    monkeypatch.setenv('EMAIL_USE_SSL', 'false')
    return EmailSender()


def submit(sender):
    return sender.submit_email('Code', 'owner@example.invalid', 'mobile_auth_code',
                               {'purpose': 'test', 'code': '123456'}, standalone=True)


def test_real_mime_has_date_unique_message_ids_and_both_body_parts(native_app, sender):
    with patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        server = smtp.return_value.__enter__.return_value
        server.send_message.return_value = {}
        first, second = submit(sender), submit(sender)
    assert first.accepted and second.accepted and first.message_id != second.message_id
    assert first.message_id.endswith('@example.invalid>')
    msg = server.send_message.call_args_list[0].args[0]
    assert parsedate_to_datetime(msg['Date']).utcoffset() == timedelta(0)
    assert msg['Message-ID'] == first.message_id
    assert [part.get_content_type() for part in msg.get_payload()] == ['text/plain', 'text/html']
    context = server.starttls.call_args.kwargs['context']
    assert context.check_hostname


def test_auth_transport_does_not_inherit_other_provider_credentials(monkeypatch):
    monkeypatch.setenv('EMAIL_HOST', 'reminders.invalid')
    monkeypatch.setenv('EMAIL_HOST_USER', 'reminder-user')
    monkeypatch.setenv('EMAIL_HOST_PASSWORD', 'reminder-secret')
    monkeypatch.setenv('AUTH_EMAIL_HOST', 'codes.invalid')
    monkeypatch.delenv('AUTH_EMAIL_HOST_USER', raising=False)
    monkeypatch.delenv('AUTH_EMAIL_HOST_PASSWORD', raising=False)
    sender = EmailSender(auth=True)
    assert sender.email_host == 'codes.invalid' and sender.use_tls
    assert sender.email_user is None and sender.email_password is None
    assert EmailSender().email_host == 'reminders.invalid'


def test_empty_auth_host_uses_complete_legacy_transport(monkeypatch):
    monkeypatch.setenv('AUTH_EMAIL_HOST', '')
    monkeypatch.setenv('EMAIL_HOST', 'legacy.invalid')
    monkeypatch.setenv('EMAIL_PORT', '25')
    monkeypatch.setenv('EMAIL_USE_TLS', 'false')
    sender = EmailSender(auth=True)
    assert sender.email_host == 'legacy.invalid' and sender.email_port == 25 and not sender.use_tls


def test_implicit_tls_and_plain_auth_transport_rejection(native_app, monkeypatch):
    monkeypatch.setenv('AUTH_EMAIL_HOST', 'provider.invalid')
    monkeypatch.setenv('AUTH_DEFAULT_FROM_EMAIL', 'no-reply@example.invalid')
    monkeypatch.setenv('AUTH_EMAIL_PORT', '465')
    monkeypatch.setenv('AUTH_EMAIL_USE_TLS', 'false')
    monkeypatch.setenv('AUTH_EMAIL_USE_SSL', 'true')
    with patch('app.utils.email_utils.smtplib.SMTP_SSL') as smtp:
        smtp.return_value.__enter__.return_value.send_message.return_value = {}
        assert submit(EmailSender(auth=True)).accepted
        assert smtp.call_args.args == ('provider.invalid', 465)
        assert smtp.call_args.kwargs['context'].check_hostname
    monkeypatch.setenv('AUTH_EMAIL_USE_SSL', 'false')
    with patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        assert submit(EmailSender(auth=True)).error == 'tls_required'
        smtp.assert_not_called()


@pytest.mark.parametrize(('code', 'retryable'), [(421, True), (450, True), (550, False), (554, False)])
def test_smtp_replies_are_classified_and_never_logged(native_app, sender, caplog, code, retryable):
    with patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        server = smtp.return_value.__enter__.return_value
        server.send_message.side_effect = smtplib.SMTPDataError(code, b'private reply 123456 owner@example.invalid')
        result = submit(sender)
    assert not result.accepted and result.smtp_code == code and result.retryable == retryable
    assert '123456' not in caplog.text and 'owner@example.invalid' not in caplog.text


def test_auth_smtp_debug_is_always_off(native_app, monkeypatch):
    monkeypatch.setenv('EMAIL_HOST', 'legacy.invalid')
    monkeypatch.setenv('DEFAULT_FROM_EMAIL', 'no-reply@example.invalid')
    monkeypatch.setenv('SMTP_DEBUG_LEVEL', '2')
    with patch('app.utils.email_utils.smtplib.SMTP') as smtp:
        submit(EmailSender(auth=True))
        smtp.return_value.__enter__.return_value.set_debuglevel.assert_called_once_with(0)


def queued(native_app):
    from app.auth.mobile_models import MobileAuthMail
    proof, _ = start(native_app.test_client())
    return MobileAuthMail.query.filter_by(challenge_id=proof['challenge_id']).one()


def test_transient_retry_backoff_and_stable_message_id(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.auth.mobile_models import utcnow
    from app.utils.db import db
    row = queued(native_app)
    observed = []
    def temporary(**kwargs):
        observed.append(kwargs['message_id'])
        return MailSubmission(False, kwargs['message_id'], 'smtp', 421)
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email', temporary)
    for attempt, delay in [(1, 30), (2, 60), (3, 120)]:
        row.available_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
        before = utcnow()
        mobile_mail.process_auth_mail(maintenance=False)
        db.session.refresh(row)
        assert row.status == 'pending' and row.attempts == attempt
        assert row.available_at >= before + timedelta(seconds=delay)
        assert row.last_error == 'smtp' and row.last_smtp_code == 421
        mobile_mail.process_auth_mail(maintenance=False)
        assert row.attempts == attempt
    assert len(set(observed)) == 1


def test_permanent_refusal_is_terminal_and_not_retried(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.utils.db import db
    row = queued(native_app)
    calls = []
    def refuse(**kwargs):
        calls.append(kwargs)
        return MailSubmission(False, kwargs['message_id'], 'recipient', 550, False)
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email', refuse)
    mobile_mail.process_auth_mail(maintenance=False)
    mobile_mail.process_auth_mail(maintenance=False)
    db.session.refresh(row)
    assert row.status == 'failed' and row.encrypted_code is None and row.last_smtp_code == 550
    assert len(calls) == 1


@pytest.mark.parametrize('reason', ['expired', 'superseded'])
def test_expired_and_superseded_codes_are_never_submitted(native_app, monkeypatch, reason):
    from app.auth import mobile_mail
    from app.auth.mobile_models import MobileAuthChallenge, utcnow
    from app.utils.db import db
    row = queued(native_app)
    proof = db.session.get(MobileAuthChallenge, row.challenge_id)
    if reason == 'expired':
        proof.expires_at = utcnow() - timedelta(seconds=1)
    else:
        proof.used_at = utcnow()
    db.session.commit()
    with patch.object(mobile_mail.email_sender, 'submit_email') as send:
        mobile_mail.process_auth_mail(maintenance=False)
        send.assert_not_called()
    db.session.refresh(row)
    assert row.status == 'expired' and row.encrypted_code is None


def test_retry_does_not_schedule_beyond_code_expiry(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.auth.mobile_models import MobileAuthChallenge, utcnow
    from app.utils.db import db
    row = queued(native_app)
    db.session.get(MobileAuthChallenge, row.challenge_id).expires_at = utcnow() + timedelta(seconds=15)
    db.session.commit()
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email',
                        lambda **kw: MailSubmission(False, kw['message_id'], 'network'))
    mobile_mail.process_auth_mail(maintenance=False)
    db.session.refresh(row)
    assert row.status == 'expired' and row.encrypted_code is None


def test_operational_status_has_no_personal_data_and_worker_once(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.utils.db import db
    row = queued(native_app)
    identifier, address = row.id, row.email
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email',
                        lambda **kw: MailSubmission(True, kw['message_id']))
    runner = native_app.test_cli_runner()
    result = runner.invoke(args=['auth-mail-worker', '--once'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['accepted'] >= 1
    result = runner.invoke(args=['auth-mail-status'])
    assert result.exit_code == 0
    value = json.loads(result.output)
    assert value['counts']['accepted'] >= 1
    assert address not in result.output and 'encrypted_code' not in result.output
    from app.auth.mobile_models import MobileAuthMail
    row = db.session.get(MobileAuthMail, identifier)
    assert row.accepted_at is not None and row.message_id and row.encrypted_code is None


def test_submission_migration_roundtrip_preserves_pending_and_relabels_legacy_sent():
    path = Path(__file__).resolve().parents[2] / 'migrations/versions/20261122_auth_mail_submission.py'
    spec = importlib.util.spec_from_file_location('auth_mail_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE mobile_auth_mail (id INTEGER PRIMARY KEY, status VARCHAR(16), available_at TIMESTAMP)'))
        connection.execute(sa.text("INSERT INTO mobile_auth_mail (id, status) VALUES (1, 'sent'), (2, 'pending')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert dict(connection.execute(sa.text('SELECT id, status FROM mobile_auth_mail')).all()) == {1: 'accepted', 2: 'pending'}
        assert 'message_id' in {c['name'] for c in sa.inspect(connection).get_columns('mobile_auth_mail')}
        migration.downgrade()
        assert dict(connection.execute(sa.text('SELECT id, status FROM mobile_auth_mail')).all()) == {1: 'sent', 2: 'pending'}
        assert len(sa.inspect(connection).get_columns('mobile_auth_mail')) == 3


def test_stale_claim_recovery_keeps_message_identity(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.auth.mobile_models import utcnow
    from app.utils.db import db
    row = queued(native_app)
    row.status = 'sending'
    row.locked_at = utcnow() - timedelta(seconds=61)
    row.attempts = 1
    row.message_id = '<prior-claim@example.invalid>'
    db.session.commit()
    seen = []
    def accept(**kw):
        seen.append(kw['message_id'])
        return MailSubmission(True, kw['message_id'])
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email', accept)
    mobile_mail.process_auth_mail(maintenance=False)
    db.session.refresh(row)
    assert row.status == 'accepted' and row.attempts == 2
    assert seen == ['<prior-claim@example.invalid>']


def test_old_worker_result_cannot_overwrite_new_claim(native_app, monkeypatch):
    from app.auth import mobile_mail
    from app.auth.mobile_models import MobileAuthMail, utcnow
    from app.utils.db import db
    row = queued(native_app)
    identifier = row.id
    def lease_taken_over(**kw):
        # Simulate a different worker having reclaimed an expired lease.
        MobileAuthMail.query.filter_by(id=identifier).update({
            'attempts': 2, 'locked_at': utcnow() + timedelta(seconds=1),
        }, synchronize_session=False)
        db.session.commit()
        return MailSubmission(True, kw['message_id'])
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email', lease_taken_over)
    mobile_mail.process_auth_mail(maintenance=False)
    db.session.refresh(row)
    assert row.status == 'sending' and row.attempts == 2 and row.encrypted_code is not None
