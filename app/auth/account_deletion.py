"""Transactional erasure of an authenticated account and durable upload cleanup.

User-owned learning rows use database ON DELETE CASCADE. Shared catalog content
retains its data and loses creator references via SET NULL. Never use ORM user
deletion here: legacy backrefs can null non-nullable child keys before CASCADE.
"""
from datetime import timedelta
import os
import secrets
import requests
from flask import current_app
from sqlalchemy import delete, func, or_
from app.auth.mobile_models import MobileAuthChallenge, MobileAuthMail, SocialIdentity, utcnow
from app.auth.models import User
from app.utils.db import db


class AccountDeletionFile(db.Model):
    __tablename__ = "account_deletion_files"
    path = db.Column(db.String(512), primary_key=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)


class AccountDeletionRequest(db.Model):
    __tablename__ = "account_deletion_requests"
    id = db.Column(db.String(64), primary_key=True, default=lambda: secrets.token_urlsafe(32))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    requested_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    earliest_deletion_at = db.Column(db.DateTime, nullable=False)
    latest_deletion_at = db.Column(db.DateTime, nullable=False, index=True)
    admin_notice_after = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requires_reconfirmation = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    reconfirmation_reason = db.Column(db.String(1000), nullable=True)
    reconfirmation_requested_at = db.Column(db.DateTime, nullable=True)
    history = db.Column(db.JSON, nullable=False, default=list, server_default="[]")
    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")

    def response(self, tracking=False):
        from app.api.mobile_auth import digest
        def stamp(value):
            return value.isoformat(timespec="seconds") + "Z" if value else None
        value = dict(id=self.id, status=self.status, requested_at=stamp(self.requested_at),
            earliest_deletion_at=stamp(self.earliest_deletion_at), latest_deletion_at=stamp(self.latest_deletion_at),
            cancelled_at=stamp(self.cancelled_at), completed_at=stamp(self.completed_at))
        if tracking:
            value["tracking_token"] = digest("account-deletion-status|" + self.id)
            value.update(requires_reconfirmation=self.requires_reconfirmation,
                reconfirmation_reason=self.reconfirmation_reason,
                reconfirmation_requested_at=stamp(self.reconfirmation_requested_at))
        return value

    def record(self, action, *, administrator=None, reason=None):
        event = {"action": action, "at": utcnow().isoformat(timespec="seconds") + "Z"}
        if administrator is not None:
            event["admin_id"] = administrator.id
        if reason:
            event["reason"] = reason
        self.history = [*(self.history or []), event]


class AccountDeletionMail(db.Model):
    __tablename__ = "account_deletion_mail"
    request_id = db.Column(db.String(64), db.ForeignKey("account_deletion_requests.id", ondelete="CASCADE"), primary_key=True)
    encrypted_email = db.Column(db.Text, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    purpose = db.Column(db.String(24), nullable=False, default="completed", server_default="completed")


def queue_deletion_mail(row, address, purpose):
    from app.auth.mobile_mail import cipher
    if not address:
        return
    mail = db.session.get(AccountDeletionMail, row.id)
    if mail is None:
        mail = AccountDeletionMail(request_id=row.id)
        db.session.add(mail)
    mail.encrypted_email = cipher().encrypt(address.encode()).decode()
    mail.purpose = purpose
    mail.attempts = 0
    mail.available_at = utcnow()
    mail.sent_at = None


def request_deletion_reconfirmation(identifier, administrator, reason):
    """One bounded security check per request; never extend its original dates."""
    from app.api.mobile_auth import AuthProblem
    from app.notifications.services import create_notification
    if not administrator.is_admin or not administrator.active:
        raise AuthProblem("access_denied", "Требуется подтверждение администратора.", 403)
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
        raise AuthProblem("invalid_reason", "Укажи понятную пользователю причину: от 10 до 1000 символов.")
    candidate = db.session.get(AccountDeletionRequest, identifier)
    if candidate is None or candidate.status != "pending" or candidate.user_id is None:
        raise AuthProblem("request_not_pending", "Заявка закрыта или не найдена.", 409)
    user = User.query.filter_by(id=candidate.user_id).with_for_update().first()
    if user is None:
        raise AuthProblem("request_not_pending", "Заявка уже закрыта.", 409)
    row = AccountDeletionRequest.query.filter_by(id=identifier).with_for_update(of=AccountDeletionRequest).populate_existing().one()
    if row.status != "pending" or row.user_id != user.id:
        raise AuthProblem("request_not_pending", "Пользователь отменил заявку.", 409)
    if row.reconfirmation_requested_at is not None:
        raise AuthProblem("reconfirmation_already_requested", "Повторное подтверждение уже запрашивалось для этой заявки.", 409)
    row.requires_reconfirmation = True
    row.reconfirmation_reason = reason.strip()
    row.reconfirmation_requested_at = utcnow()
    row.admin_notice_after = utcnow() + timedelta(days=1)
    row.record("reconfirmation_requested", administrator=administrator, reason=row.reconfirmation_reason)
    # Previously issued codes cannot approve a later security check.
    MobileAuthChallenge.query.filter_by(user_id=user.id, kind="account_deletion").filter(
        MobileAuthChallenge.used_at.is_(None)
    ).update({"used_at": utcnow(), "payload": {}}, synchronize_session=False)
    create_notification(user_id=user.id, type="account_deletion",
        title="Подтверди удаление аккаунта повторно",
        message=row.reconfirmation_reason + " Открой заявку и подтверди намерение или отмени её. Сроки заявки сохраняются.",
        link="/account-deletion", icon="🔐")
    queue_deletion_mail(row, user.email, "reconfirmation")
    db.session.commit()
    return row


def _revoke_apple(identity):
    from app.api.mobile_auth import AuthProblem
    from app.api.mobile_social import _apple_secret
    from app.auth.mobile_mail import cipher
    if not identity.encrypted_refresh:
        raise AuthProblem("apple_reauthentication_required",
            "Сначала войди в этот аккаунт через Apple ещё раз, затем повтори удаление.", 409)
    try:
        token = cipher().decrypt(identity.encrypted_refresh.encode()).decode()
        response = requests.post("https://appleid.apple.com/auth/revoke", data={
            "client_id": current_app.config.get("MOBILE_APPLE_CLIENT_ID", "com.llt.english.ios"),
            "client_secret": _apple_secret(), "token": token, "token_type_hint": "refresh_token",
        }, timeout=(5, 5), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Apple revocation failed")
    except Exception:
        # No tokens, email addresses, upstream response bodies, or secrets in logs.
        raise AuthProblem("deletion_temporarily_unavailable",
            "Не получилось отключить вход Apple. Аккаунт сохранён. Попробуй чуть позже.", 503) from None


def erase_account(user, *, commit=True):
    from app.feedback.models import Feedback, FeedbackReply
    from app.reminders.models import ReminderLog
    from app.api.mobile_auth import AuthProblem
    user_id, address = user.id, user.email
    identities = SocialIdentity.query.filter_by(user_id=user_id).with_for_update().all()
    for identity in identities:
        if identity.provider == "apple":
            _revoke_apple(identity)
    try:
        # Anonymous registration/reset proofs can also contain this account's mail.
        clauses = [MobileAuthChallenge.user_id == user_id]
        if address:
            clauses.append(func.lower(MobileAuthChallenge.email) == address.lower())
        ids = [r.id for r in MobileAuthChallenge.query.filter(or_(*clauses)).all()]
        if ids:
            MobileAuthMail.query.filter(MobileAuthMail.challenge_id.in_(ids)).delete(synchronize_session=False)
            MobileAuthChallenge.query.filter(MobileAuthChallenge.id.in_(ids)).delete(synchronize_session=False)
        # Feedback uses SET NULL for administrative history, but customer content
        # and its screenshots must be erased when their author deletes the account.
        reports = Feedback.query.filter_by(user_id=user_id).all()
        report_ids = [r.id for r in reports]
        for path in {r.screenshot_path for r in reports if r.screenshot_path}:
            if db.session.get(AccountDeletionFile, path) is None:
                db.session.add(AccountDeletionFile(path=path))
        if report_ids:
            FeedbackReply.query.filter(FeedbackReply.feedback_id.in_(report_ids)).delete(synchronize_session=False)
        FeedbackReply.query.filter_by(author_user_id=user_id).delete(synchronize_session=False)
        Feedback.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        # These two legacy FKs have no ON DELETE action.
        ReminderLog.query.filter(or_(ReminderLog.user_id == user_id, ReminderLog.sent_by == user_id)).delete(synchronize_session=False)
        db.session.execute(delete(User.__table__).where(User.__table__.c.id == user_id))
        if commit:
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Account erasure transaction failed")
        raise AuthProblem("deletion_temporarily_unavailable",
            "Не получилось завершить удаление. Аккаунт сохранён. Попробуй чуть позже.", 503) from None
    # Replaceable cache invalidation cannot undo a completed database deletion.
    if not commit:
        return
    invalidate_deleted_account_cache(user_id)


def invalidate_deleted_account_cache(user_id):
    try:
        from app.curriculum.cache import CurriculumCache
        CurriculumCache.invalidate_user_cache(user_id)
    except Exception:
        current_app.logger.warning("Deleted account cache invalidation needs retry")


def complete_account_deletion(identifier, administrator):
    """Only called by an explicit, CSRF-protected admin POST; never by a timer."""
    from app.api.mobile_auth import AuthProblem
    if not administrator.is_admin or not administrator.active:
        raise AuthProblem("access_denied", "Требуется подтверждение администратора.", 403)
    candidate = db.session.get(AccountDeletionRequest, identifier)
    if candidate is None:
        raise AuthProblem("not_found", "Заявка не найдена.", 404)
    if candidate.status != "pending" or candidate.user_id is None:
        raise AuthProblem("request_not_pending", "Эта заявка уже закрыта.", 409)
    user = User.query.filter_by(id=candidate.user_id).with_for_update().first()
    if user is None:
        raise AuthProblem("request_not_pending", "Заявка уже закрыта.", 409)
    row = AccountDeletionRequest.query.filter_by(id=identifier).with_for_update(of=AccountDeletionRequest).populate_existing().one()
    if row.status != "pending" or row.user_id != user.id:
        raise AuthProblem("request_not_pending", "Пользователь отменил заявку.", 409)
    if row.requires_reconfirmation:
        raise AuthProblem("reconfirmation_required", "Сначала владелец должен повторно подтвердить удаление.", 409)
    if utcnow() < row.earliest_deletion_at:
        raise AuthProblem("cooling_off_period", "Семидневный срок на отмену ещё не истёк.", 409)
    uid = user.id
    queue_deletion_mail(row, user.email, "completed")
    row.record("completed", administrator=administrator)
    # Free-text security reasons can contain personal data. Erase them with the account.
    row.reconfirmation_reason = None
    row.history = [{k: v for k, v in event.items() if k != "reason"} for event in row.history]
    row.status = "completed"
    row.completed_at = utcnow()
    row.reviewed_by = administrator.id if administrator.id != uid else None
    row.user_id = None
    erase_account(user, commit=False)
    db.session.commit()
    invalidate_deleted_account_cache(uid)
    return row


def process_account_deletion_mail(batch_size=10):
    from app.auth.mobile_mail import cipher
    from app.utils.email_utils import email_sender
    completed = 0
    for _ in range(min(20, max(0, batch_size))):
        row = AccountDeletionMail.query.filter(AccountDeletionMail.encrypted_email.isnot(None),
            AccountDeletionMail.available_at <= utcnow()).with_for_update(skip_locked=True).first()
        if row is None:
            db.session.commit()
            break
        request_row = db.session.get(AccountDeletionRequest, row.request_id)
        verification = row.purpose == "reconfirmation"
        expected = request_row is not None and (
            request_row.status == "pending" and request_row.requires_reconfirmation if verification
            else request_row.status == "completed")
        if not expected:
            db.session.delete(row); db.session.commit(); continue
        origin = request_row.reconfirmation_requested_at if verification else request_row.completed_at
        if row.attempts >= 10 or origin is None or utcnow() - origin > timedelta(days=7):
            row.encrypted_email = None; db.session.commit(); continue
        # Persist the attempt before SMTP. No account identifier enters the email.
        row.attempts += 1
        row.available_at = utcnow() + timedelta(seconds=min(86400, 60 * 2 ** row.attempts))
        identifier, encrypted, purpose = row.request_id, row.encrypted_email, row.purpose
        context = {}
        if verification:
            context = {"reason": request_row.reconfirmation_reason,
                "url": (current_app.config.get("SITE_URL") or "https://llt-english.com").rstrip("/") + "/account-deletion"}
        db.session.commit()
        try:
            ok = email_sender.send_email(to_email=cipher().decrypt(encrypted.encode()).decode(),
                subject="LLT English — подтверди удаление аккаунта" if verification else "LLT English — аккаунт удалён",
                template_name="account_deletion_reconfirmation" if verification else "account_deleted",
                context=context, timeout=8, standalone=True)
        except Exception:
            ok = False
        row = db.session.get(AccountDeletionMail, identifier)
        if row and ok and row.purpose == purpose and row.encrypted_email == encrypted:
            row.encrypted_email = None
            row.sent_at = utcnow()
            completed += 1
        db.session.commit()
    # Tracking receipts contain no account/email after completion and expire.
    AccountDeletionRequest.query.filter(AccountDeletionRequest.status.in_(["completed", "cancelled"]),
        AccountDeletionRequest.requested_at < utcnow() - timedelta(days=45)).delete(synchronize_session=False)
    db.session.commit()
    return completed


def process_account_deletion_files(batch_size=20):
    """Retried by the existing auth-mail worker; never follows arbitrary paths."""
    from app.feedback.models import Feedback
    from app.feedback.storage import feedback_screenshot_abs_path
    completed = 0
    for _ in range(min(100, max(0, batch_size))):
        row = AccountDeletionFile.query.filter(AccountDeletionFile.available_at <= utcnow()).with_for_update(skip_locked=True).first()
        if row is None:
            db.session.commit()
            break
        try:
            if not Feedback.query.filter_by(screenshot_path=row.path).first():
                path = feedback_screenshot_abs_path(row.path)
                if path is not None:
                    os.unlink(path)
            db.session.delete(row)
            db.session.commit()
            completed += 1
        except OSError:
            row.attempts += 1
            row.available_at = utcnow() + timedelta(seconds=min(86400, 60 * 2 ** min(row.attempts, 10)))
            db.session.commit()
            current_app.logger.warning("Deleted account upload cleanup will retry")
    return completed
