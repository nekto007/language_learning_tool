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
from app.utils.email_utils import email_sender

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llt-auth-mail")
_running = threading.Lock()


def cipher():
    secret = current_app.config["SECRET_KEY"]
    key = hashlib.sha256(("llt-mobile-auth-v1|" + str(secret)).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def process_auth_mail(batch_size=10):
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
    sent = 0
    for _ in range(min(20, batch_size)):
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
            .order_by(MobileAuthMail.id)
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
            or row.attempts >= 3
        ):
            row.status = "expired"
            row.encrypted_code = None
            db.session.commit()
            continue
        row.status = "sending"
        row.locked_at = now
        row.attempts += 1
        identifier, attempt, address, encrypted, purpose = (
            row.id,
            row.attempts,
            row.email,
            row.encrypted_code,
            proof.kind,
        )
        db.session.commit()
        try:
            code = cipher().decrypt(encrypted.encode()).decode()
            ok = email_sender.send_email(
                subject="Код для LLT English",
                to_email=address,
                template_name="mobile_auth_code",
                context={
                    "code": code,
                    "purpose": (
                        "смены пароля" if purpose == "reset" else "подтверждения почты"
                    ),
                },
                timeout=8,
                standalone=True,
            )
        except Exception:
            ok = False
            current_app.logger.warning("Native auth email delivery failed")
        row = db.session.get(MobileAuthMail, identifier)
        if (
            row
            and row.status == "sending"
            and row.attempts == attempt
            and row.locked_at == now
        ):
            row.status = "sent" if ok else "pending"
            row.available_at = utcnow() + timedelta(seconds=30)
            row.locked_at = None
            if ok:
                row.encrypted_code = None
                sent += 1
            db.session.commit()
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
                process_auth_mail()
        except Exception:
            app.logger.warning("Native auth mail worker deferred to scheduler")
        finally:
            _running.release()

    try:
        _pool.submit(work)
    except Exception:
        _running.release()
