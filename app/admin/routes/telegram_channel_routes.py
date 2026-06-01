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
    STATUS_FAILED,
    STATUS_PUBLISHED,
    STATUS_QUEUED,
    STATUS_SKIPPED,
    ChannelPost,
)
from app.telegram.channel_publisher import (
    get_channel_config,
    publish_due,
    queue_upcoming,
    send_test_message,
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
    scheduler_status = _build_scheduler_status(db.session)
    return render_template(
        'admin/telegram_channel/index.html',
        upcoming=upcoming,
        published=published,
        failed=failed,
        config=config,
        scheduler_status=scheduler_status,
    )


def _build_scheduler_status(db_session) -> dict:
    """Build the scheduler-liveness snapshot shown in the admin header.

    Returns a dict with:
    - ``last_tick_iso``: raw value from SiteSettings (or '' if never written).
    - ``last_tick_age_seconds``: seconds since last tick, or None if unknown.
    - ``healthy``: True if last_tick is within ~3× the publisher interval (5 min),
      i.e. <=15 minutes ago.
    - ``message``: human-readable diagnostic for the admin UI.
    """
    from app.admin.site_settings import get_site_setting

    raw = (get_site_setting('telegram_channel_last_tick_iso', '', db_session=db_session) or '').strip()
    if not raw:
        return {
            'last_tick_iso': '',
            'last_tick_age_seconds': None,
            'healthy': False,
            'message': (
                'APScheduler ни разу не отметился. '
                'Скорее всего процесс flask start-bot не запущен — '
                'без него автопубликация не работает (только ручные кнопки).'
            ),
        }
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return {
            'last_tick_iso': raw,
            'last_tick_age_seconds': None,
            'healthy': False,
            'message': f'Некорректное значение last_tick_iso: {raw}',
        }
    now = datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = int((now - last).total_seconds())
    healthy = 0 <= age <= 15 * 60  # 3× publisher interval
    if healthy:
        message = f'APScheduler жив, последний тик {age // 60} мин назад.'
    else:
        message = (
            f'Последний тик scheduler\'а {age // 60} мин назад — это слишком давно. '
            f'Проверьте, что процесс flask start-bot работает.'
        )
    return {
        'last_tick_iso': raw,
        'last_tick_age_seconds': age,
        'healthy': healthy,
        'message': message,
    }


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
    from datetime import datetime, timezone

    from app.telegram.channel_models import STATUS_QUEUED, ChannelPost

    post = ChannelPost.query.get_or_404(post_id)
    post.status = STATUS_QUEUED
    post.error = None
    post.scheduled_for = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash(f'Пост #{post.id} возвращён в очередь.', 'success')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))


@telegram_channel_bp.route('/telegram-channel/send-now/<int:post_id>', methods=['POST'])
@admin_required
def telegram_channel_send_now(post_id: int):
    """Pull a queued post's schedule into the past and publish immediately.

    Useful when the queue is full of future slots and the admin wants to
    test a specific row right now (rather than waiting until 15:00 UTC).
    """
    from datetime import datetime, timezone

    from app.telegram.channel_models import STATUS_QUEUED, ChannelPost

    post = ChannelPost.query.get_or_404(post_id)
    if post.status != STATUS_QUEUED:
        flash(f'Пост #{post.id} уже не в очереди (статус: {post.status}).', 'warning')
        return redirect(url_for('telegram_channel_admin.telegram_channel_index'))

    # Snap scheduled_for to "now minus one second" so publish_due picks it up.
    post.scheduled_for = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()

    try:
        result = publish_due()
    except Exception:
        logger.exception('Admin send-now failed for post=%s', post_id)
        flash('Ошибка при отправке. Смотрите логи приложения.', 'danger')
        return redirect(url_for('telegram_channel_admin.telegram_channel_index'))

    if result['sent']:
        flash(f'Пост #{post.id} отправлен в канал.', 'success')
    elif result['failed']:
        flash(
            f'Не удалось отправить пост #{post.id}. См. раздел «Не отправлены».',
            'danger',
        )
    else:
        flash('Неожиданный результат: пост не отправлен и не помечен как failed.', 'warning')
    return redirect(url_for('telegram_channel_admin.telegram_channel_index'))
