"""Durable welcome-email outbox, consumed by the email scheduler.

SMTP delivery is at least once: a process can die after SMTP accepted a
message but before its database acknowledgement. Expired claims are retried.
"""
import logging
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import and_, or_

from app.auth.models import User
from app.utils.db import db
from app.utils.email_utils import email_sender

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BATCH_SIZE = 20
CLAIM_TTL = timedelta(minutes=10)
SMTP_TIMEOUT_SECONDS = 15


def _utcnow() -> datetime:
    """Match the application's naive-UTC database timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WelcomeEmail(db.Model):
    __tablename__ = 'welcome_email_queue'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )
    status = db.Column(db.String(16), nullable=False, default='pending', server_default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    available_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    locked_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_welcome_email_queue_due', 'status', 'available_at'),
    )


def enqueue_welcome_email(user: User) -> WelcomeEmail:
    """Add a welcome email to the caller's transaction; never commit or send.

    The registration transaction must flush the new user first. The unique
    user_id also prevents duplicate jobs across subsequent calls.
    """
    if user.id is None:
        raise ValueError('Flush the user before enqueueing a welcome email')
    for pending in db.session.new:
        if isinstance(pending, WelcomeEmail) and pending.user_id == user.id:
            return pending
    with db.session.no_autoflush:
        existing = WelcomeEmail.query.filter_by(user_id=user.id).first()
    if existing is not None:
        return existing
    job = WelcomeEmail(user_id=user.id)
    db.session.add(job)
    return job


def _claim_next() -> tuple[int, int, datetime, int] | None:
    """Commit a single claim so no row lock is held while SMTP runs."""
    now = _utcnow()
    job = (
        WelcomeEmail.query.filter(or_(
            and_(WelcomeEmail.status == 'pending', WelcomeEmail.available_at <= now),
            and_(WelcomeEmail.status == 'sending', WelcomeEmail.locked_at <= now - CLAIM_TTL),
        ))
        .order_by(WelcomeEmail.available_at, WelcomeEmail.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        db.session.commit()
        return None
    if job.attempts >= MAX_ATTEMPTS:
        exhausted = (job.id, job.user_id, now, 0)
        job.status = 'failed'
        job.locked_at = None
        db.session.commit()
        return exhausted
    job.status = 'sending'
    job.attempts += 1
    job.locked_at = now
    claim = (job.id, job.user_id, now, job.attempts)
    db.session.commit()
    return claim


def _finish_claim(job_id: int, locked_at: datetime, attempt: int, *, sent: bool,
                  permanent_failure: bool = False) -> None:
    """A stale worker cannot acknowledge a replacement worker's claim."""
    now = _utcnow()
    values = {'locked_at': None}
    if sent:
        values.update(status='sent', sent_at=now)
    elif permanent_failure or attempt >= MAX_ATTEMPTS:
        values.update(status='failed')
    else:
        values.update(status='pending', available_at=now + timedelta(seconds=30 * 2 ** (attempt - 1)))
    WelcomeEmail.query.filter_by(
        id=job_id, status='sending', locked_at=locked_at, attempts=attempt,
    ).update(values, synchronize_session=False)
    db.session.commit()


def run_welcome_email_job(*, batch_size: int = BATCH_SIZE) -> int:
    """Deliver a bounded batch in an app context, recovering expired claims.

    Claims are made immediately before each send so a slow SMTP server cannot
    expire jobs waiting behind other messages in a preclaimed batch.
    """
    sent_count = 0
    for _ in range(min(max(batch_size, 0), BATCH_SIZE)):
        claim = _claim_next()
        if claim is None:
            break
        job_id, user_id, locked_at, attempt = claim
        if attempt == 0:  # A crashed final attempt has exhausted its budget.
            continue
        try:
            user = db.session.get(User, user_id)
            deliverable = user is not None and user.active and bool(user.email)
            if deliverable:
                recipient, username = user.email, user.username
            # Release the read transaction before calling the network.
            db.session.commit()
            if not deliverable:
                _finish_claim(job_id, locked_at, attempt, sent=False, permanent_failure=True)
                continue
            site_url = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
            ok = email_sender.send_email(
                subject='Добро пожаловать в Language Learning Tool!',
                to_email=recipient,
                template_name='welcome',
                context={'username': username, 'dashboard_url': f'{site_url}/onboarding'},
                timeout=SMTP_TIMEOUT_SECONDS,
                standalone=True,
            )
        except Exception:
            db.session.rollback()
            logger.exception('Welcome email failed for queue job=%s', job_id)
            ok = False
        _finish_claim(job_id, locked_at, attempt, sent=bool(ok))
        sent_count += bool(ok)
    return sent_count
