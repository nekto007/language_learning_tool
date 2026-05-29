# app/admin/routes/telegram_channel_routes.py

"""Admin UI for the Telegram channel auto-publisher.

Shows the upcoming queue, recent published log, and failed posts that need
attention. Lets the admin skip an upcoming post (so the auto-picker can
choose another the next refill) and trigger an immediate queue refill.
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.admin.utils.decorators import admin_required
from app.telegram.channel_models import (
    ChannelPost, STATUS_FAILED, STATUS_PUBLISHED, STATUS_QUEUED, STATUS_SKIPPED,
)
from app.telegram.channel_publisher import (
    get_channel_config, publish_due, queue_upcoming, send_test_message,
)
from app.utils.db import db

telegram_channel_bp = Blueprint('telegram_channel_admin', __name__)

logger = logging.getLogger(__name__)


@telegram_channel_bp.route('/telegram-channel')
@admin_required
def telegram_channel_index():
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    upcoming = (
        ChannelPost.query
        .filter(ChannelPost.status == STATUS_QUEUED)
        .filter(ChannelPost.scheduled_for >= now)
        .order_by(ChannelPost.scheduled_for.asc())
        .limit(50)
        .all()
    )
    published = (
        ChannelPost.query
        .filter(ChannelPost.status == STATUS_PUBLISHED)
        .filter(ChannelPost.published_at >= now - timedelta(days=14))
        .order_by(ChannelPost.published_at.desc())
        .limit(50)
        .all()
    )
    failed = (
        ChannelPost.query
        .filter(ChannelPost.status == STATUS_FAILED)
        .filter(ChannelPost.updated_at >= now - timedelta(days=7))
        .order_by(ChannelPost.updated_at.desc())
        .limit(20)
        .all()
    )

    config = get_channel_config(db.session)
    return render_template(
        'admin/telegram_channel/index.html',
        upcoming=upcoming,
        published=published,
        failed=failed,
        config=config,
    )


@telegram_channel_bp.route('/telegram-channel/skip/<int:post_id>', methods=['POST'])
@admin_required
def telegram_channel_skip(post_id: int):
    """Mark a queued post as skipped; next refill may pick a replacement."""
    post = ChannelPost.query.get_or_404(post_id)
    if post.status != STATUS_QUEUED:
        flash(f'Пост #{post.id} нельзя пропустить — статус {post.status}.', 'warning')
        return redirect(url_for('telegram_channel_admin.telegram_channel_index'))
    post.status = STATUS_SKIPPED
    db.session.commit()
    flash(f'Пост #{post.id} помечен как пропущенный.', 'success')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))


@telegram_channel_bp.route('/telegram-channel/refill', methods=['POST'])
@admin_required
def telegram_channel_refill():
    """Force a queue refill for the next 7 days (otherwise runs daily at 02:00 UTC)."""
    days_ahead = request.form.get('days_ahead', 7, type=int)
    if days_ahead < 1 or days_ahead > 30:
        days_ahead = 7
    try:
        created = queue_upcoming(days_ahead=days_ahead)
    except Exception:
        logger.exception('Admin refill failed')
        flash('Ошибка при пополнении очереди. Смотрите логи.', 'danger')
        return redirect(url_for('telegram_channel_admin.telegram_channel_index'))
    flash(
        f'Добавлено постов: {len(created)} (на {days_ahead} дней вперёд).',
        'success' if created else 'info',
    )
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))


@telegram_channel_bp.route('/telegram-channel/test', methods=['POST'])
@admin_required
def telegram_channel_test():
    """Send a one-off test message to the configured channel."""
    ok, message = send_test_message(db.session)
    flash(message, 'success' if ok else 'danger')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))


@telegram_channel_bp.route('/telegram-channel/publish-now', methods=['POST'])
@admin_required
def telegram_channel_publish_now():
    """Run publish_due immediately — useful when the APScheduler is not running
    (e.g. dev without start-bot, or just after the admin set the channel id)."""
    try:
        result = publish_due()
    except Exception:
        logger.exception('Admin publish_now failed')
        flash('Ошибка при принудительной отправке. Смотрите логи.', 'danger')
        return redirect(url_for('telegram_channel_admin.telegram_channel_index'))
    if result['sent']:
        flash(
            f'Отправлено постов: {result["sent"]}. Провалов: {result["failed"]}.',
            'success' if not result['failed'] else 'warning',
        )
    elif result['failed']:
        flash(
            f'Не удалось отправить ни одного поста ({result["failed"]} провал). '
            f'Откройте раздел «Не отправлены».',
            'danger',
        )
    elif result['skipped_no_channel']:
        flash(
            f'channel_id не задан — {result["skipped_no_channel"]} постов помечено как skipped.',
            'warning',
        )
    else:
        flash('Постов, готовых к отправке, нет (scheduled_for в будущем).', 'info')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))


@telegram_channel_bp.route('/telegram-channel/resend/<int:post_id>', methods=['POST'])
@admin_required
def telegram_channel_resend(post_id: int):
    """Re-queue a failed post so the next publish cycle retries it."""
    from app.telegram.channel_models import ChannelPost, STATUS_QUEUED
    from datetime import datetime, timezone

    post = ChannelPost.query.get_or_404(post_id)
    post.status = STATUS_QUEUED
    post.error = None
    post.scheduled_for = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash(f'Пост #{post.id} возвращён в очередь.', 'success')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))
