"""Durable, admin-only reminders. This worker never approves or erases accounts.

The locked request's next notice and all in-app notifications commit together.
Telegram mirrors them best-effort after commit; an outage cannot lose the inbox
notice or cause a fresh duplicate on every scheduler tick.
"""
from datetime import timedelta
from html import escape

from flask import current_app

from app.auth.account_deletion import AccountDeletionRequest
from app.auth.mobile_models import utcnow
from app.auth.models import User
from app.notifications.services import create_notification
from app.utils.db import db


def _notice(row, now):
    deadline = row.latest_deletion_at.strftime("%d.%m.%Y %H:%M UTC")
    earliest = row.earliest_deletion_at.strftime("%d.%m.%Y %H:%M UTC")
    if row.requires_reconfirmation:
        title = "Ожидается повторное подтверждение удаления"
        body = f"Удаление заблокировано до ответа владельца. Исходный крайний срок — {deadline}. Проверь статус заявки."
        next_notice = now + timedelta(days=1)
    elif now >= row.latest_deletion_at:
        title = "Просрочена заявка на удаление аккаунта"
        body = f"Крайний срок {deadline} прошёл. Проверь заявку и обработай её вручную."
        next_notice = now + timedelta(days=1)
    elif now >= row.latest_deletion_at - timedelta(days=2):
        title = "Приближается срок удаления аккаунта"
        body = f"До крайнего срока осталось не больше двух суток: {deadline}. Требуется ручная обработка."
        next_notice = row.latest_deletion_at
    elif now >= row.earliest_deletion_at:
        title = "Заявка на удаление готова к обработке"
        body = f"Семидневный срок на отмену истёк. Обработай заявку вручную до {deadline}."
        next_notice = row.latest_deletion_at - timedelta(days=2)
    else:
        title = "Новая заявка на удаление аккаунта"
        body = f"Удаление доступно с {earliest}. Крайний срок — {deadline}. До обработки пользователь может отменить заявку."
        next_notice = row.earliest_deletion_at
    # No username, email, verification code or tracking token enters the notice.
    return title, body, next_notice


def _telegram(admin_ids, title, body, link):
    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        return
    from app.telegram.bot import send_message
    from app.telegram.models import TelegramUser

    # Recheck current roles and linking after committing/releasing the request.
    links = TelegramUser.query.join(User, User.id == TelegramUser.user_id).filter(
        User.id.in_(admin_ids), User.is_admin.is_(True), User.active.is_(True),
        TelegramUser.is_active.is_(True),
    ).all()
    origin = (current_app.config.get("SITE_URL") or "https://llt-english.com").rstrip("/")
    text = f"<b>{escape(title)}</b>\n\n{escape(body)}\n\n<a href=\"{escape(origin + link, quote=True)}\">Открыть заявку в админке →</a>"
    for account in links:
        try:
            send_message(int(account.telegram_id), text, parse_mode="HTML")
        except Exception:
            current_app.logger.warning("Account deletion Telegram delivery failed; in-app notice saved")


def process_admin_deletion_notices(batch_size=20):
    """At most one notice per request/milestone; overdue notices every 24h."""
    processed = 0
    for _ in range(min(100, max(0, batch_size))):
        now = utcnow()
        row = AccountDeletionRequest.query.filter(
            AccountDeletionRequest.status == "pending",
            AccountDeletionRequest.user_id.isnot(None),
            AccountDeletionRequest.admin_notice_after <= now,
        ).order_by(AccountDeletionRequest.admin_notice_after, AccountDeletionRequest.id).with_for_update(
            of=AccountDeletionRequest, skip_locked=True
        ).first()
        if row is None:
            db.session.commit()
            break
        admins = User.query.filter(User.is_admin.is_(True), User.active.is_(True)).all()
        if not admins:
            # Keep it due: the next tick can notify a newly configured admin.
            db.session.commit()
            break
        title, body, next_notice = _notice(row, now)
        link = "/admin/account-deletions?request_id=" + row.id
        for admin in admins:
            create_notification(user_id=admin.id, type="account_deletion", title=title,
                message=body, link=link, icon="🔔")
        row.admin_notice_after = next_notice
        admin_ids = [admin.id for admin in admins]
        db.session.commit()
        processed += 1
        try:
            _telegram(admin_ids, title, body, link)
        except Exception:
            db.session.rollback()
            current_app.logger.warning("Account deletion Telegram notice unavailable; in-app notice saved")
    return processed
