"""Real PostgreSQL locking and migration checks for the OTP worker."""

import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.auth import mobile_mail
from app.auth.mobile_models import MobileAuthChallenge, MobileAuthMail, utcnow
from app.utils.db import db
from app.utils.email_utils import MailSubmission


def submission_migration():
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261122_auth_mail_submission.py'
    spec = importlib.util.spec_from_file_location('pg_auth_mail_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.fixture(scope='module', autouse=True)
def current_test_outbox_schema(app):
    # The shared disposable PostgreSQL fixture uses create_all, which doesn't
    # alter tables left from previous test runs. Apply this revision if needed.
    if 'message_id' not in {c['name'] for c in sa.inspect(db.engine).get_columns('mobile_auth_mail')}:
        with db.engine.begin() as connection:
            migration = submission_migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()


@pytest.fixture
def committed_auth_mail(app):
    engine = db.engine
    identifier = uuid4().hex
    with Session(engine) as session:
        session.add(MobileAuthChallenge(id=identifier, kind='register',
                    email='disposable@example.invalid', payload={},
                    expires_at=utcnow() + timedelta(minutes=10)))
        session.flush()
        row = MobileAuthMail(challenge_id=identifier, email='disposable@example.invalid',
                             encrypted_code=mobile_mail.cipher().encrypt(b'123456').decode())
        session.add(row)
        session.flush()
        row_id = row.id
        session.commit()
    try:
        yield row_id
    finally:
        with Session(engine) as session:
            session.execute(sa.delete(MobileAuthChallenge).where(MobileAuthChallenge.id == identifier))
            session.commit()


def run_worker(app):
    with app.app_context():
        try:
            return mobile_mail.process_auth_mail(maintenance=False)
        finally:
            db.session.remove()


def test_postgres_locked_job_is_skipped(app, committed_auth_mail):
    with Session(db.engine) as owner:
        owner.query(MobileAuthMail).filter_by(id=committed_auth_mail).with_for_update().one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(run_worker, app).result(timeout=5) == 0
        owner.rollback()


def test_concurrent_workers_do_not_submit_same_active_claim(app, committed_auth_mail, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def smtp_submit(**kwargs):
        calls.append(kwargs['message_id'])
        started.set()
        assert release.wait(5)
        return MailSubmission(True, kwargs['message_id'])
    monkeypatch.setattr(mobile_mail.email_sender, 'submit_email', smtp_submit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_worker, app)
        try:
            assert started.wait(5)
            assert pool.submit(run_worker, app).result(timeout=5) == 0
        finally:
            release.set()
        assert first.result(timeout=5) == 1
    assert len(calls) == 1
    with Session(db.engine) as session:
        row = session.get(MobileAuthMail, committed_auth_mail)
        assert row.status == 'accepted' and row.attempts == 1 and row.encrypted_code is None


def test_submission_migration_on_postgresql(app):
    migration = submission_migration()
    schema = 'auth_mail_test_' + uuid4().hex
    # Transactional DDL leaves no schema/data behind, including on failure.
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(sa.text('CREATE TABLE mobile_auth_mail (id INTEGER PRIMARY KEY, status VARCHAR(16), available_at TIMESTAMP)'))
            connection.execute(sa.text("INSERT INTO mobile_auth_mail (id, status) VALUES (1, 'sent'), (2, 'pending')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            assert dict(connection.execute(sa.text('SELECT id, status FROM mobile_auth_mail')).all()) == {1: 'accepted', 2: 'pending'}
            assert connection.execute(sa.text('SELECT accepted_at FROM mobile_auth_mail WHERE id=1')).scalar() is None
            migration.downgrade()
            assert dict(connection.execute(sa.text('SELECT id, status FROM mobile_auth_mail')).all()) == {1: 'sent', 2: 'pending'}
        finally:
            transaction.rollback()
