"""
Система отправки напоминаний пользователям языкового приложения
"""
import html as html_module
import logging
import os
import re
import smtplib
import socket
from datetime import datetime, timedelta, timezone
from email import charset
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc, func

from app.admin.utils.decorators import admin_required
from app.auth.models import User
from app.curriculum.models import LessonProgress
from app.reminders.models import ReminderLog
from app.utils.db import db

reminders = Blueprint('reminders', __name__, url_prefix='/admin/reminders')

# Настройка логирования
logger = logging.getLogger(__name__)

# Конфигурация email
EMAIL_HOST = os.environ.get('EMAIL_HOST')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 25))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL')


def get_user_by_id(user_id):
    """
    Получает пользователя по ID.
    Используется в шаблонах как вспомогательная функция.
    """
    return User.query.get(user_id)


@reminders.app_template_filter()
def get_user_by_id_filter(user_id):
    return get_user_by_id(user_id)


@reminders.context_processor
def utility_processor():
    return dict(get_user_by_id=get_user_by_id)


def html_to_text(html_content):
    """
    Конвертирует HTML в простой текст для text/plain части письма.
    """
    # Удаляем style и script теги с содержимым
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Заменяем <br> и </p> на переносы строк
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    # Сохраняем ссылки в формате "текст (URL)"
    text = re.sub(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
    # Удаляем все оставшиеся HTML теги
    text = re.sub(r'<[^>]+>', '', text)
    # Декодируем HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    # Убираем множественные пустые строки
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    # Убираем пробелы в начале и конце
    text = text.strip()
    return text


def send_email(to_email, subject, html_content, from_email=DEFAULT_FROM_EMAIL):
    """
    Отправляет электронное письмо пользователю.

    Args:
        to_email (str): Email получателя
        subject (str): Тема письма
        html_content (str): HTML-содержимое письма
        from_email (str): От кого (по умолчанию берётся из настроек)

    Returns:
        bool: True если отправка успешна, иначе False
    """
    try:
        # Настраиваем quoted-printable вместо base64 для UTF-8
        cs = charset.Charset('utf-8')
        cs.body_encoding = charset.QP

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Date'] = formatdate(localtime=True)

        # Генерируем Message-ID на основе домена отправителя
        # Извлекаем домен из email (учитываем формат "Name <email@domain>")
        email_match = re.search(r'[\w\.-]+@([\w\.-]+)', from_email)
        from_domain = email_match.group(1) if email_match else socket.getfqdn()
        msg['Message-ID'] = make_msgid(domain=from_domain)

        # Генерируем text/plain версию из HTML
        text_content = html_to_text(html_content)

        # Используем quoted-printable кодирование вместо base64
        part_text = MIMEText(text_content, 'plain', _charset=cs)
        part_html = MIMEText(html_content, 'html', _charset=cs)
        msg.attach(part_text)
        msg.attach(part_html)

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            if EMAIL_USE_TLS:
                server.starttls()

            if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
            server.send_message(msg)

        logger.info(f"Письмо успешно отправлено на {to_email}")
        return True

    except Exception as e:
        logger.error(f"Ошибка при отправке письма на {to_email}: {str(e)}")
        return False


REMINDER_MIN_INTERVAL_HOURS = 24
MAX_REMINDER_TARGETS = 500


REMINDER_CAMPAIGNS = {
    'default': {
        'label': 'Стандартное',
        'subject': 'Пора вернуться к изучению английского!',
        'description': 'Базовый шаблон для совместимости со старыми формами.',
        'best_for': 'Любая ручная отправка',
        'cta': 'Вернуться к обучению',
        'template': 'default',
    },
    'friendly': {
        'label': 'Дружелюбное',
        'subject': 'Давайте продолжим английский с короткого шага',
        'description': 'Более мягкая версия стандартного возврата.',
        'best_for': 'Новые и малоактивные',
        'cta': 'Начать занятие',
        'template': 'friendly',
    },
    'comeback': {
        'label': 'Вернуться к занятиям',
        'subject': 'Вернитесь к английскому с короткого занятия',
        'description': 'Мягкое re-engagement письмо для пользователей, которые давно не заходили.',
        'best_for': 'Неактивны 7+ дней',
        'cta': 'Открыть план дня',
        'template': 'comeback',
    },
    'daily_plan': {
        'label': 'План дня',
        'subject': 'Ваш короткий план английского на сегодня',
        'description': 'Продает главный ежедневный сценарий: урок, карточки, грамматика, чтение.',
        'best_for': 'Заходили, но не закрывают день',
        'cta': 'Выполнить план',
        'template': 'daily_plan',
    },
    'achievement': {
        'label': 'Достижения и прогресс',
        'subject': 'Ваш прогресс в LLT English уже ждет продолжения',
        'description': 'Показывает уроки, streak, слова и ближайший маленький следующий шаг.',
        'best_for': 'Есть прогресс, но пропали',
        'cta': 'Продолжить прогресс',
        'template': 'achievement',
    },
    'features': {
        'label': 'Разделы сайта',
        'subject': 'Попробуйте книги, карточки и грамматику в LLT English',
        'description': 'Рекламирует разные разделы сайта: book courses, library, SRS, grammar lab.',
        'best_for': 'Новые или малоактивные',
        'cta': 'Выбрать формат',
        'template': 'features',
    },
    'books': {
        'label': 'Книги и курсы',
        'subject': 'Учите английский через книги и короткие уроки',
        'description': 'Фокус на библиотеке, book courses и чтении как альтернативе обычным урокам.',
        'best_for': 'Любят чтение или не идут в curriculum',
        'cta': 'Открыть книги',
        'template': 'books',
    },
    'grammar': {
        'label': 'Грамматика',
        'subject': 'Закройте один грамматический пробел сегодня',
        'description': 'Приглашает в Grammar Lab и предлагает короткую практику без большого урока.',
        'best_for': 'Низкая активность в grammar',
        'cta': 'Открыть Grammar Lab',
        'template': 'grammar',
    },
}


REMINDER_SEGMENTS = {
    'inactive_3': {
        'label': 'Неактивны 3+ дня',
        'description': 'Ранний мягкий возврат, пока привычка еще не потеряна.',
        'inactive_days': 3,
    },
    'inactive_7': {
        'label': 'Неактивны 7+ дней',
        'description': 'Основная re-engagement аудитория.',
        'inactive_days': 7,
    },
    'inactive_14': {
        'label': 'Неактивны 14+ дней',
        'description': 'Нужен сильный повод вернуться: достижения, книги, новый формат.',
        'inactive_days': 14,
    },
    'inactive_30': {
        'label': 'Неактивны 30+ дней',
        'description': 'Переоткрыть продукт и показать новые возможности.',
        'inactive_days': 30,
    },
    'never_started': {
        'label': 'Зарегистрировались, но не начали',
        'description': 'Нет входа после регистрации или нет завершенных уроков.',
    },
    'has_progress': {
        'label': 'Есть прогресс, но пропали',
        'description': 'Пользователи с завершенными уроками, которым есть что показать.',
    },
    'all_eligible': {
        'label': 'Все доступные для email',
        'description': 'Все active, не отписанные, с включенными email reminders.',
    },
}


def _eligible_users_query():
    return User.query.filter(
        User.active.is_(True),
        User.email.isnot(None),
        User.email != '',
        User.email_opted_out.is_(False),
        User.notify_email_reminders.is_(True),
    )


def _segment_query(segment_key: str):
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    query = _eligible_users_query()

    segment = REMINDER_SEGMENTS.get(segment_key) or REMINDER_SEGMENTS['inactive_7']
    if segment_key.startswith('inactive_') or segment.get('inactive_days') is not None:
        days = int(segment.get('inactive_days') or 7)
        cutoff = now_naive - timedelta(days=days)
        return query.filter(db.or_(User.last_login.is_(None), User.last_login < cutoff))

    if segment_key == 'never_started':
        completed_subq = db.session.query(LessonProgress.user_id).filter(
            LessonProgress.status == 'completed'
        )
        return query.filter(
            db.or_(User.last_login.is_(None), ~User.id.in_(completed_subq))
        )

    if segment_key == 'has_progress':
        cutoff = now_naive - timedelta(days=7)
        completed_subq = db.session.query(LessonProgress.user_id).filter(
            LessonProgress.status == 'completed'
        )
        return query.filter(
            User.id.in_(completed_subq),
            db.or_(User.last_login.is_(None), User.last_login < cutoff),
        )

    return query


def _get_segment_users(segment_key: str, limit: int = MAX_REMINDER_TARGETS):
    return _segment_query(segment_key).order_by(
        User.last_login.asc().nullsfirst(),
        User.created_at.desc(),
    ).limit(limit).all()


def _build_segment_cards():
    cards = []
    for key, meta in REMINDER_SEGMENTS.items():
        count = _segment_query(key).with_entities(func.count(User.id)).scalar() or 0
        cards.append({'key': key, 'count': count, **meta})
    return cards


def _safe_campaign(template_name: str) -> dict | None:
    if not re.match(r'^[a-zA-Z0-9_-]+$', template_name or ''):
        return None
    campaign = REMINDER_CAMPAIGNS.get(template_name)
    if campaign:
        return campaign
    return None


def _user_learning_snapshot(user: User) -> dict:
    try:
        from app.achievements.models import StreakCoins, UserStatistics
        from app.study.models import UserWord
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        coins = StreakCoins.query.filter_by(user_id=user.id).first()
        word_count = UserWord.query.filter_by(user_id=user.id).count()
        completed_lessons = LessonProgress.query.filter_by(
            user_id=user.id, status='completed'
        ).count()
    except Exception:
        logger.exception('Failed to build reminder snapshot for user %s', user.id)
        try:
            db.session.rollback()
        except Exception:
            logger.exception('Failed to rollback snapshot session for user %s', user.id)
        stats = None
        coins = None
        word_count = 0
        completed_lessons = 0

    return {
        'completed_lessons': completed_lessons,
        'words': word_count,
        'current_streak': stats.current_streak_days if stats else 0,
        'longest_streak': stats.longest_streak_days if stats else 0,
        'badges': stats.total_badges if stats else 0,
        'coins': coins.balance if coins else 0,
    }


def _reminder_links(template_name: str) -> dict:
    return {
        'dashboard': url_for('words.dashboard', _external=True),
        'study': url_for('study.index', _external=True),
        'book_courses': url_for('book_courses.list_book_courses', _external=True),
        'books': url_for('books.book_list', _external=True),
        'grammar': url_for('grammar_lab.practice', _external=True),
        'settings': url_for('study.settings', _external=True),
        'primary': {
            'daily_plan': url_for('words.dashboard', _external=True),
            'comeback': url_for('words.dashboard', _external=True),
            'achievement': url_for('study.index', _external=True),
            'features': url_for('book_courses.list_book_courses', _external=True),
            'books': url_for('books.book_list', _external=True),
            'grammar': url_for('grammar_lab.practice', _external=True),
        }.get(template_name, url_for('words.dashboard', _external=True)),
    }


_PLAN_KIND_LABELS = {
    'curriculum': 'Урок дня',
    'srs': 'Повторение слов',
    'reading': 'Чтение книги',
    'listening': 'Аудирование',
    'speaking': 'Произношение',
    'writing': 'Письмо',
    'error_review': 'Разбор ошибок',
    'grammar_review': 'Грамматика',
    'challenge': 'Челлендж дня',
    'setup_book': 'Выберите книгу',
    'setup_level': 'Уровень',
}

_PLAN_LESSON_TYPE_LABELS = {
    'vocabulary': 'Урок курса',
    'grammar': 'Грамматика',
    'quiz': 'Квиз',
    'reading': 'Чтение в уроке',
    'listening_immersion': 'Аудирование',
    'translation': 'Перевод',
    'sentence_completion': 'Завершение фраз',
    'sentence_correction': 'Исправление',
    'pronunciation': 'Произношение',
    'shadow_reading': 'Чтение вслух',
    'writing_prompt': 'Письмо',
    'audio_fill_blank': 'Аудиозапись',
    'dictation': 'Диктант',
    'idiom': 'Идиома',
    'collocation_matching': 'Сочетания',
    'final_test': 'Итоговый тест',
    'card': 'Закрепление',
    'flashcards': 'Закрепление',
    'matching': 'Соответствия',
}


def _user_daily_plan_preview(user: User, max_items: int = 5) -> dict:
    """Best-effort preview of pending plan items for email.

    Returns ``{'cards': [{eyebrow, title, subtitle}], 'day_secured': bool}``.
    Key is ``cards`` (not ``items``) so Jinja's ``plan_preview.cards`` resolves
    via getitem instead of hitting ``dict.items`` method.
    Errors are swallowed — email render must not fail if planning breaks.
    """
    try:
        from app.daily_plan.service import get_daily_plan_unified
        plan = get_daily_plan_unified(user.id)
    except Exception:
        logger.exception('reminder: plan preview failed for user %s', user.id)
        try:
            db.session.rollback()
        except Exception:
            logger.exception('reminder: rollback failed for user %s', user.id)
        return {'cards': [], 'day_secured': False}

    if plan.get('mode') == 'paused':
        return {'cards': [], 'day_secured': bool(plan.get('day_secured')), 'paused': True}

    pending: list[dict] = []
    seen_kinds: set[str] = set()
    for bucket in ('required', 'optional'):
        for raw in (plan.get(bucket) or []):
            if raw.get('completed') or raw.get('skipped') or raw.get('blocked'):
                continue
            kind = raw.get('kind') or 'curriculum'
            # Dedup repeated kinds (e.g. multiple curriculum items) — keep first only.
            if kind in seen_kinds and kind != 'curriculum':
                continue
            seen_kinds.add(kind)
            lesson_type = raw.get('lesson_type')
            eyebrow = (
                _PLAN_LESSON_TYPE_LABELS.get(lesson_type)
                if kind == 'curriculum' and lesson_type
                else None
            ) or _PLAN_KIND_LABELS.get(kind) or 'Задание'
            eta = raw.get('eta_minutes') or 0
            subtitle = raw.get('subtitle')
            meta_bits = []
            if subtitle:
                meta_bits.append(str(subtitle))
            if eta:
                meta_bits.append(f'~{eta} мин')
            pending.append({
                'eyebrow': eyebrow,
                'title': raw.get('title') or '',
                'subtitle': ' · '.join(meta_bits),
            })
            if len(pending) >= max_items:
                break
        if len(pending) >= max_items:
            break

    return {'cards': pending, 'day_secured': bool(plan.get('day_secured'))}


def _render_reminder_template(
    template_name: str,
    user: User,
    now,
    unsubscribe_token: str,
    tracking_token: str | None = None,
) -> str:
    campaign = REMINDER_CAMPAIGNS[template_name]
    # Plan preview first: builds via get_daily_plan_unified which touches many
    # tables. If it poisons the txn it self-rolls-back, so snapshot below
    # starts on a clean session.
    plan_preview = _user_daily_plan_preview(user)
    snapshot = _user_learning_snapshot(user)
    pixel_url = None
    tracked = None
    if tracking_token:
        from app.reminders.tracking import sign_click
        pixel_url = url_for(
            'reminder_tracking.track_open', token=tracking_token, _external=True,
        )

        def tracked(target_url: str) -> str:
            if not target_url:
                return target_url
            return url_for(
                'reminder_tracking.track_click',
                blob=sign_click(tracking_token, target_url),
                _external=True,
            )

    links = _reminder_links(template_name)
    if tracked:
        links = _wrap_links_with_tracking(links, tracked)

    return render_template(
        f'emails/reminders/{campaign["template"]}.html',
        user=user,
        now=now,
        unsubscribe_token=unsubscribe_token,
        campaign=campaign,
        snapshot=snapshot,
        links=links,
        plan_preview=plan_preview,
        tracking_pixel_url=pixel_url,
        tracked=tracked,
    )


def _wrap_links_with_tracking(links: dict, tracked) -> dict:
    """Return a copy of ``links`` with every URL routed through tracking.

    ``unsubscribe`` is intentionally NOT wrapped (we don't want unsubscribes
    to count as engagement clicks). ``settings`` is also kept raw — it's a
    system action, not a campaign CTA.
    """
    wrapped: dict = {}
    skip_keys = {'settings'}
    for key, value in links.items():
        if key in skip_keys:
            wrapped[key] = value
            continue
        if isinstance(value, str):
            wrapped[key] = tracked(value)
        elif isinstance(value, dict):
            wrapped[key] = {k: tracked(v) if isinstance(v, str) else v for k, v in value.items()}
        else:
            wrapped[key] = value
    return wrapped


def get_inactive_users(days=7):
    """
    Получает список пользователей, которые не входили в систему более указанного количества дней.
    Если days=0, возвращает всех активных пользователей.
    Фильтрует пользователей с email_opted_out=True или notify_email_reminders=False.

    Args:
        days (int): Количество дней неактивности (0 = все пользователи)

    Returns:
        list: Список пользователей
    """
    base_filter = _eligible_users_query()

    if days == 0:
        return base_filter.all()

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    inactive_users = base_filter.filter(
        (User.last_login < cutoff_date) | (User.last_login.is_(None))
    ).all()

    return inactive_users


def _was_recently_reminded(user_id: int, hours: int = REMINDER_MIN_INTERVAL_HOURS) -> bool:
    """Return True if user received a reminder within the last `hours` hours."""
    # sent_at is a naive UTC column; compare against naive UTC to avoid psycopg2
    # aware/naive mismatch that can silently return wrong results across server timezones.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    return ReminderLog.query.filter(
        ReminderLog.user_id == user_id,
        ReminderLog.sent_at >= cutoff,
    ).first() is not None


@reminders.route('/', methods=['GET'])
@admin_required
def reminder_dashboard():
    """
    Панель управления напоминаниями для администраторов.
    """
    segment_key = (request.args.get('segment') or '').strip()
    if segment_key not in REMINDER_SEGMENTS:
        inactive_days = request.args.get('inactive_days', 7, type=int)
        segment_key = {
            0: 'all_eligible',
            3: 'inactive_3',
            7: 'inactive_7',
            14: 'inactive_14',
            30: 'inactive_30',
        }.get(inactive_days, 'inactive_7')
    else:
        inactive_days = REMINDER_SEGMENTS[segment_key].get('inactive_days', 7)

    campaign_key = (request.args.get('campaign') or 'comeback').strip()
    if campaign_key not in REMINDER_CAMPAIGNS:
        campaign_key = 'comeback'

    inactive_users = _get_segment_users(segment_key)

    # Получаем статистику по отправленным напоминаниям
    reminders_sent = ReminderLog.query.order_by(desc(ReminderLog.sent_at)).limit(50).all()
    campaign_stats = _campaign_engagement_stats()

    now = datetime.now(timezone.utc)

    return render_template(
        'admin/reminders/dashboard.html',
        inactive_users=inactive_users,
        inactive_days=inactive_days,
        segment_key=segment_key,
        campaign_key=campaign_key,
        segment_cards=_build_segment_cards(),
        campaigns=REMINDER_CAMPAIGNS,
        selected_campaign=REMINDER_CAMPAIGNS[campaign_key],
        reminders_sent=reminders_sent,
        campaign_stats=campaign_stats,
        now=now
    )


def _campaign_engagement_stats() -> list[dict]:
    """Aggregate sent / opened / clicked per campaign template.

    Returns rows ordered by total sent desc — empty rows for campaigns
    that haven't been used yet are skipped. Open- and click-rate are
    percentages of ``sent`` (rounded to 1 decimal); guarded against
    div-by-zero.
    """
    rows = db.session.query(
        ReminderLog.template,
        func.count(ReminderLog.id).label('sent'),
        func.count(ReminderLog.opened_at).label('opened'),
        func.count(ReminderLog.clicked_at).label('clicked'),
    ).group_by(ReminderLog.template).order_by(func.count(ReminderLog.id).desc()).all()

    out: list[dict] = []
    for row in rows:
        sent = int(row.sent or 0)
        opened = int(row.opened or 0)
        clicked = int(row.clicked or 0)
        campaign = REMINDER_CAMPAIGNS.get(row.template) or {}
        out.append({
            'template': row.template,
            'label': campaign.get('label', row.template),
            'sent': sent,
            'opened': opened,
            'clicked': clicked,
            'open_rate': round(opened / sent * 100, 1) if sent else 0.0,
            'click_rate': round(clicked / sent * 100, 1) if sent else 0.0,
        })
    return out


@reminders.route('/send', methods=['POST'])
@admin_required
def send_reminders():
    """
    Отправляет напоминания выбранным пользователям.
    """
    user_ids = request.form.getlist('user_ids')
    reminder_template = request.form.get('reminder_template', 'comeback')
    campaign = _safe_campaign(reminder_template)
    if not campaign:
        flash('Недопустимый шаблон напоминания.', 'danger')
        return redirect(url_for('reminders.reminder_dashboard'))
    custom_subject = (request.form.get('custom_subject') or campaign['subject']).strip()[:255]

    # Защита от path traversal — только безопасные имена шаблонов
    if not re.match(r'^[a-zA-Z0-9_-]+$', reminder_template):
        flash('Недопустимое имя шаблона.', 'danger')
        return redirect(url_for('reminders.reminder_dashboard'))

    if not user_ids:
        flash('Не выбрано ни одного пользователя для отправки напоминаний.', 'warning')
        return redirect(url_for('reminders.reminder_dashboard'))

    users = User.query.filter(
        User.id.in_(user_ids),
        User.active.is_(True),
        User.email.isnot(None),
        User.email != '',
        User.email_opted_out.is_(False),
        User.notify_email_reminders.is_(True),
    ).all()
    success_count = 0
    skipped_recent = 0

    from sqlalchemy.exc import IntegrityError

    now = datetime.now(timezone.utc)
    today = now.date()

    for user in users:
        if _was_recently_reminded(user.id):
            logger.info(f"Skipping reminder for user {user.id}: sent within last {REMINDER_MIN_INTERVAL_HOURS}h")
            skipped_recent += 1
            continue

        from app.email_scheduler import ensure_unsubscribe_token
        unsubscribe_token = ensure_unsubscribe_token(user)

        import secrets
        tracking_token = secrets.token_hex(16)

        # Claim the per-(user, day) slot BEFORE sending so two concurrent
        # /send requests can't both pass the cooldown and double-email
        # (audit E-079). uq_reminder_logs_user_sent_on enforces it at the DB.
        log = ReminderLog(
            user_id=user.id,
            template=reminder_template,
            subject=custom_subject,
            sent_by=current_user.id,
            token=tracking_token,
            sent_on=today,
        )
        db.session.add(log)
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            logger.info(f"Skipping reminder for user {user.id}: already claimed for {today}")
            skipped_recent += 1
            continue

        html_content = _render_reminder_template(
            reminder_template, user, now, unsubscribe_token,
            tracking_token=tracking_token,
        )

        if send_email(user.email, custom_subject, html_content):
            success_count += 1
        else:
            # Release the claim so a later legitimate retry isn't blocked by a
            # transient SMTP failure.
            db.session.delete(log)
            db.session.flush()

    # Сохраняем изменения в базе данных
    db.session.commit()

    if success_count > 0:
        suffix = f' Пропущено по cooldown: {skipped_recent}.' if skipped_recent else ''
        flash(f'Успешно отправлено {success_count} напоминаний из {len(users)}.{suffix}', 'success')
    else:
        if skipped_recent:
            flash(f'Все выбранные пользователи уже получали напоминание за последние {REMINDER_MIN_INTERVAL_HOURS} ч.', 'warning')
        else:
            flash('Не удалось отправить напоминания. Проверьте настройки SMTP.', 'danger')

    # Возвращаемся на исходную страницу, если она указана (с проверкой безопасности)
    from app.auth.routes import get_safe_redirect_url
    next_url = get_safe_redirect_url(
        request.form.get('next') or request.referrer,
        fallback='reminders.reminder_dashboard'
    )
    return redirect(next_url)


@reminders.route('/templates', methods=['GET'])
@admin_required
def list_templates():
    """
    Отображает список доступных шаблонов напоминаний.
    """
    template_files = list(REMINDER_CAMPAIGNS.keys())

    return render_template('admin/reminders/templates.html', templates=template_files)


@reminders.route('/preview/<template_name>', methods=['GET'])
@admin_required
def preview_template(template_name):
    """
    Предварительный просмотр шаблона напоминания.
    """
    if not _safe_campaign(template_name):
        abort(400, 'Недопустимое имя шаблона')

    try:
        now = datetime.now(timezone.utc)
        unsubscribe_token = "sample_token"

        html = _render_reminder_template(template_name, current_user, now, unsubscribe_token)
        response = make_response(html)
        # Allow iframe embedding from same origin for preview
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
    except Exception as e:
        # Return error directly in iframe instead of redirect
        error_html = f'''
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; color: #721c24; background: #f8d7da;">
            <h3>Ошибка при загрузке шаблона</h3>
            <p>{html_module.escape(str(e))}</p>
        </body>
        </html>
        '''
        response = make_response(error_html, 500)
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
