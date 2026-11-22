"""Durable transactional auth mail, nudged after requests and retried by scheduler."""

import base64
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from cryptography.fernet import Fernet
from flask import current_app
from sqlalchemy import and_, or_
from app.auth.mobile_models import MobileAuthChallenge, MobileAuthMail, utcnow
from app.utils.db import db
from app.utils.email_utils import auth_email_sender as email_sender

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llt-auth-mail")
_running = threading.Lock()


def cipher():
    secret = current_app.config["SECRET_KEY"]
    key = hashlib.sha256(("llt-mobile-auth-v1|" + str(secret)).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


MAX_MAIL_ATTEMPTS = 5


def cleanup_auth_mail():
    """Bounded housekeeping; kept off the request-triggered OTP path."""
    now = utcnow()
    stale = [
        r.id
        for r in MobileAuthChallenge.query.filter(
            MobileAuthChallenge.expires_at < now - timedelta(days=1)
        )
        .limit(200)
        .all()
    ]
    if stale:
        MobileAuthMail.query.filter(MobileAuthMail.challenge_id.in_(stale)).delete(
            synchronize_session=False
        )
        MobileAuthChallenge.query.filter(MobileAuthChallenge.id.in_(stale)).delete(
            synchronize_session=False
        )
    from app.auth.mobile_models import MobileAuthThrottle

    old_keys = [
        r.key
        for r in MobileAuthThrottle.query.filter(
            MobileAuthThrottle.last_at < now - timedelta(days=2)
        )
        .limit(500)
        .all()
    ]
    if old_keys:
        MobileAuthThrottle.query.filter(MobileAuthThrottle.key.in_(old_keys)).delete(
            synchronize_session=False
        )
    db.session.commit()


def process_auth_mail(batch_size=20, *, maintenance=True):
    """Claim with SKIP LOCKED; release DB locks before bounded SMTP I/O."""
    sent = 0
    for _ in range(min(100, max(0, batch_size))):
        now = utcnow()
        row = (
            MobileAuthMail.query.filter(
                or_(
                    and_(
                        MobileAuthMail.status == "pending",
                        MobileAuthMail.available_at <= now,
                    ),
                    and_(
                        MobileAuthMail.status == "sending",
                        MobileAuthMail.locked_at <= now - timedelta(seconds=60),
                    ),
                )
            )
            .order_by(MobileAuthMail.available_at, MobileAuthMail.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            db.session.commit()
            break
        proof = db.session.get(MobileAuthChallenge, row.challenge_id)
        if (
            proof is None
            or proof.used_at
            or proof.expires_at <= now
        ):
            row.status = "expired"
            row.encrypted_code = None
            db.session.commit()
            continue
        if row.attempts >= MAX_MAIL_ATTEMPTS:
            row.status = "failed"
            row.encrypted_code = None
            db.session.commit()
            continue
        row.status = "sending"
        if not row.message_id:
            row.message_id = email_sender.message_id()
        row.locked_at = now
        row.attempts += 1
        identifier, attempt, address, encrypted, purpose, message_id = (
            row.id,
            row.attempts,
            row.email,
            row.encrypted_code,
            proof.kind,
            row.message_id,
        )
        db.session.commit()
        try:
            code = cipher().decrypt(encrypted.encode()).decode()
            outcome = email_sender.submit_email(
                subject="Код для LLT English",
                to_email=address,
                template_name="mobile_auth_code",
                context={
                    "code": code,
                    "purpose": (
                        "смены пароля" if purpose == "reset" else
                        "подтверждения заявки на удаление аккаунта" if purpose == "account_deletion" else "подтверждения почты"
                    ),
                },
                timeout=8,
                standalone=True,
                message_id=message_id,
            )
        except Exception:
            from app.utils.email_utils import MailSubmission
            outcome = MailSubmission(False, message_id, error="internal")
            current_app.logger.warning("Native auth email submission failed")
        row = db.session.get(MobileAuthMail, identifier, with_for_update=True, populate_existing=True)
        if (
            row
            and row.status == "sending"
            and row.attempts == attempt
            and row.locked_at == now
        ):
            finished_at = utcnow()
            retry_at = finished_at + timedelta(seconds=30 * (2 ** (attempt - 1)))
            row.last_error = outcome.error
            row.last_smtp_code = outcome.smtp_code
            row.locked_at = None
            if outcome.accepted:
                row.status = "accepted"
                row.accepted_at = finished_at
                row.encrypted_code = None
                sent += 1
            elif not outcome.retryable or attempt >= MAX_MAIL_ATTEMPTS:
                row.status = "failed"
                row.encrypted_code = None
            elif proof.expires_at <= retry_at or proof.used_at:
                row.status = "expired"
                row.encrypted_code = None
            else:
                row.status = "pending"
                row.available_at = retry_at
            current_app.logger.info(
                "Auth mail outcome id=%s status=%s attempt=%s category=%s smtp_code=%s message_id=%s",
                row.id, row.status, attempt, row.last_error, row.last_smtp_code, row.message_id,
            )
            db.session.commit()
        else:
            # A newer lease owns the row. Release the read lock immediately.
            db.session.rollback()
    if maintenance:
        cleanup_auth_mail()
        from app.auth.account_deletion import process_account_deletion_files, process_account_deletion_mail
        process_account_deletion_files()
        process_account_deletion_mail()
    return sent


def nudge_auth_mail():
    if current_app.testing or not current_app.config.get(
        "MOBILE_AUTH_BACKGROUND_MAIL", True
    ):
        return
    if not _running.acquire(blocking=False):
        return
    app = current_app._get_current_object()

    def work():
        try:
            with app.app_context():
                process_auth_mail(maintenance=False)
        except Exception:
            app.logger.warning("Native auth mail worker deferred to scheduler")
        finally:
            _running.release()

    try:
        _pool.submit(work)
    except Exception:
        _running.release()
