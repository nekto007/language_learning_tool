"""Telegram bot command handlers."""
import logging
from typing import Any

import requests
from flask import current_app

from app.telegram.models import TelegramUser, TelegramLinkCode, PendingTelegramLink
from app.utils.db import db

logger = logging.getLogger(__name__)


def _progress_bar(pct: int, length: int = 10) -> str:
    """Build a text progress bar: ▓▓▓▓░░░░░░"""
    filled = round(pct / 100 * length)
    return '▓' * filled + '░' * (length - filled)


def _send_message(chat_id: int, text: str, parse_mode: str = 'HTML',
                  reply_markup: dict | None = None) -> None:
    """Send a message via Telegram Bot API."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error('TELEGRAM_BOT_TOKEN not configured')
        return

    payload: dict[str, Any] = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json=payload,
            timeout=10,
        )
        if not resp.ok:
            logger.warning('Telegram API error: %s', resp.text)
    except requests.RequestException:
        logger.exception('Failed to send Telegram message')


def send_message(chat_id: int, text: str, parse_mode: str = 'HTML',
                 reply_markup: dict | None = None) -> None:
    """Public wrapper — usable from scheduler outside request context."""
    _send_message(chat_id, text, parse_mode, reply_markup)


# ── Command handlers ────────────────────────────────────────────────

def _handle_start(chat_id: int, telegram_id: int, username: str | None) -> None:
    """Handle /start command."""
    existing = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if existing and existing.is_active:
        _send_message(chat_id, (
            'Привет! Твой аккаунт уже привязан.\n\n'
            'Доступные команды:\n'
            '/plan — план на сегодня\n'
            '/stats — быстрая статистика\n'
            '/settings — настройки уведомлений\n'
            '/unlink — отвязать аккаунт'
        ))
        return

    _send_message(chat_id, (
        'Привет! Я помогу тебе не забывать про учёбу.\n\n'
        'Чтобы начать, привяжи аккаунт:\n'
        '1. На сайте зайди в настройки Telegram\n'
        '2. Нажми «Привязать Telegram»\n'
        '3. Отправь мне полученный код:\n'
        '   /link XXXXXX'
    ))


def _handle_link(chat_id: int, telegram_id: int, username: str | None,
                 args: str) -> None:
    """Handle /link XXXXXX command (supports two-step flow)."""
    code = args.strip()
    if not code:
        PendingTelegramLink.create(telegram_id)
        _send_message(chat_id, 'Отправь код привязки — 6 цифр:')
        return
    if len(code) != 6 or not code.isdigit():
        _send_message(chat_id, 'Код должен содержать ровно 6 цифр.')
        return

    link_code = TelegramLinkCode.verify(code)
    if not link_code:
        _send_message(chat_id, 'Код неверный или истёк. Сгенерируй новый на сайте.')
        return

    # Check if this telegram_id is already linked to another account
    existing = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if existing:
        _send_message(chat_id, 'Этот Telegram уже привязан к другому аккаунту. Сначала /unlink.')
        return

    # Create link
    tg_user = TelegramUser(
        user_id=link_code.user_id,
        telegram_id=telegram_id,
        username=username,
    )
    db.session.add(tg_user)
    link_code.consume()

    _send_message(chat_id, (
        'Аккаунт привязан!\n\n'
        'Часовой пояс: Europe/Moscow\n'
        'Изменить: /settings\n\n'
        'Я буду присылать:\n'
        '• Утреннее напоминание (09:00)\n'
        '• Вечернюю сводку (21:00)\n'
        '• Напоминание, если забудешь позаниматься\n'
        '• Предупреждение о потере стрика\n\n'
        'Настроить: /settings'
    ))


def _handle_unlink(chat_id: int, telegram_id: int) -> None:
    """Handle /unlink command."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Аккаунт не привязан.')
        return

    db.session.delete(tg_user)
    db.session.commit()
    _send_message(chat_id, 'Аккаунт отвязан. Чтобы привязать снова: /link XXXXXX')


HELP_TEXT = (
    'Доступные команды:\n\n'
    '/plan — план на сегодня с чеклистом\n'
    '/stats — статистика: стрик, уроки, слова, книги\n'
    '/invite — пригласить друга и получить +100 XP\n'
    '/settings — настройки уведомлений и часовой пояс\n'
    '/link — привязать аккаунт\n'
    '/unlink — отвязать аккаунт\n'
    '/help — эта справка\n\n'
    'Бот присылает:\n'
    '• Утреннее напоминание с планом на день\n'
    '• Вечернюю сводку результатов\n'
    '• Напоминание, если забыл позаниматься\n'
    '• Предупреждение о потере стрика\n\n'
    'Все уведомления настраиваются в /settings'
)


TIMEZONE_OPTIONS = {
    'Europe/Kaliningrad': 'Калининград (UTC+2)',
    'Europe/Moscow': 'Москва (UTC+3)',
    'Europe/Samara': 'Самара (UTC+4)',
    'Asia/Yekaterinburg': 'Екатеринбург (UTC+5)',
    'Asia/Omsk': 'Омск (UTC+6)',
    'Asia/Krasnoyarsk': 'Красноярск (UTC+7)',
    'Asia/Irkutsk': 'Иркутск (UTC+8)',
    'Asia/Yakutsk': 'Якутск (UTC+9)',
    'Asia/Vladivostok': 'Владивосток (UTC+10)',
}


NOTIFICATION_LABELS = {
    'morning_reminder': ('Утро', 'morning_hour'),
    'evening_summary': ('Вечер', 'evening_hour'),
    'nudge_enabled': ('День', 'nudge_hour'),
    'streak_alert': ('Стрик', 'streak_hour'),
}


def _build_settings_keyboard(tg_user: TelegramUser) -> dict:
    """Build inline keyboard for settings."""
    def icon(enabled: bool) -> str:
        return '✅' if enabled else '❌'

    def time_btn(field: str, hour_field: str, label: str) -> list[dict]:
        enabled = getattr(tg_user, field)
        hour = getattr(tg_user, hour_field)
        return [
            {'text': f'{icon(enabled)} {label}',
             'callback_data': f'toggle_{field}'},
            {'text': f'{hour:02d}:00',
             'callback_data': f'time:{hour_field}'},
        ]

    tz_label = TIMEZONE_OPTIONS.get(tg_user.timezone, tg_user.timezone)

    return {
        'inline_keyboard': [
            time_btn('morning_reminder', 'morning_hour', 'Утро'),
            time_btn('evening_summary', 'evening_hour', 'Вечер'),
            time_btn('nudge_enabled', 'nudge_hour', 'Днём'),
            time_btn('streak_alert', 'streak_hour', 'Стрик'),
            [{'text': f'🕐 {tz_label}',
              'callback_data': 'change_timezone'}],
        ]
    }


def _build_timezone_keyboard() -> dict:
    """Build timezone selection keyboard."""
    rows = []
    for tz_id, label in TIMEZONE_OPTIONS.items():
        rows.append([{'text': label, 'callback_data': f'tz:{tz_id}'}])
    return {'inline_keyboard': rows}


def _build_time_picker(hour_field: str, current_hour: int) -> dict:
    """Build hour selection keyboard (6-23 range, 3 per row)."""
    hours = list(range(6, 24))
    rows = []
    for i in range(0, len(hours), 4):
        row = []
        for h in hours[i:i + 4]:
            label = f'• {h:02d}:00 •' if h == current_hour else f'{h:02d}:00'
            row.append({'text': label, 'callback_data': f'set_time:{hour_field}:{h}'})
        rows.append(row)
    rows.append([{'text': '← Назад', 'callback_data': 'back_to_settings'}])
    return {'inline_keyboard': rows}


def _handle_settings(chat_id: int, telegram_id: int) -> None:
    """Handle /settings command — show inline keyboard."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Сначала привяжи аккаунт: /link XXXXXX')
        return

    _send_message(
        chat_id,
        _settings_text(tg_user),
        reply_markup=_build_settings_keyboard(tg_user),
    )


def _edit_message(chat_id: int, message_id: int, text: str,
                  reply_markup: dict | None = None) -> None:
    """Edit an existing message."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token or not message_id:
        return
    payload: dict[str, Any] = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML',
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/editMessageText',
            json=payload, timeout=10,
        )
    except requests.RequestException:
        logger.exception('Failed to edit message')


def _remove_reply_markup(chat_id: int, message_id: int) -> None:
    """Remove inline keyboard from a message without changing text."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token or not message_id:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/editMessageReplyMarkup',
            json={'chat_id': chat_id, 'message_id': message_id},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception('Failed to remove reply markup')


def _answer_callback(callback_query_id: str, text: str = 'Сохранено!') -> None:
    """Answer callback query to remove loading indicator."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/answerCallbackQuery',
            json={'callback_query_id': callback_query_id, 'text': text},
            timeout=5,
        )
    except requests.RequestException:
        pass


def _settings_text(tg_user: TelegramUser) -> str:
    """Build settings message text."""
    tz_label = TIMEZONE_OPTIONS.get(tg_user.timezone, tg_user.timezone)
    return (
        f'Настройки уведомлений\n'
        f'Часовой пояс: {tz_label}\n\n'
        f'Нажми на время, чтобы изменить.'
    )


REFLECTION_RESPONSES: dict[str, str] = {
    'easy': 'Супер! \U0001f680 Завтра можем добавить +1 короткий шаг (слова на 3 минуты).',
    'ok': 'Отлично \U0001f44d Держим темп. Завтра \u2014 один урок и немного повторения.',
    'hard': 'Понял \U0001f4aa Завтра разрешаем сделать меньше.',
}


def _handle_reflection_callback(chat_id: int, telegram_id: int,
                                 callback_data: str, callback_query_id: str,
                                 message_id: int | None = None) -> None:
    """Handle reflect:easy|ok|hard callback from evening summary."""
    from datetime import datetime, timezone

    value = callback_data.split(':')[1]  # easy, ok, hard
    if value not in REFLECTION_RESPONSES:
        return

    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if tg_user:
        tg_user.last_reflection = value
        tg_user.last_reflection_at = datetime.now(timezone.utc)
        db.session.commit()

    _answer_callback(callback_query_id, REFLECTION_RESPONSES[value])
    if message_id:
        _remove_reply_markup(chat_id, message_id)


def _handle_streak_repair_callback(chat_id: int, telegram_id: int,
                                    callback_query_id: str,
                                    message_id: int | None = None) -> None:
    """Handle streak_repair callback — apply paid repair."""
    from app.achievements.streak_service import (
        find_missed_date, apply_paid_repair,
    )

    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _answer_callback(callback_query_id, 'Аккаунт не найден')
        return

    user_id = tg_user.user_id
    user_tz = tg_user.timezone
    missed = find_missed_date(user_id, tz=user_tz)
    if not missed:
        _answer_callback(callback_query_id, 'Нечего восстанавливать')
        if message_id:
            _remove_reply_markup(chat_id, message_id)
        return

    result = apply_paid_repair(user_id, missed)
    db.session.commit()

    if result['success']:
        _answer_callback(callback_query_id,
                         f'\u2705 Серия восстановлена! -{result["cost"]} coins')
        if message_id:
            _edit_message(chat_id, message_id,
                          f'\u2705 Серия восстановлена!\n'
                          f'Потрачено: {result["cost"]} coins\n'
                          f'Баланс: {result["balance"]} coins')
    else:
        error_msg = {
            'already_repaired': 'Уже восстановлено',
            'expired': 'Срок восстановления истёк',
            'insufficient_coins': f'Не хватает coins (нужно: {result["cost"]}, баланс: {result["balance"]})',
        }.get(result.get('error', ''), 'Ошибка')
        _answer_callback(callback_query_id, error_msg)
        if message_id:
            _remove_reply_markup(chat_id, message_id)


def _handle_wotd_callback(chat_id: int, telegram_id: int,
                          callback_data: str, callback_query_id: str,
                          message_id: int | None = None) -> None:
    """Handle wotd_know / wotd_dont_know callback from Word of the Day."""
    if callback_data == 'wotd_know':
        _answer_callback(callback_query_id, '\u2705 \u041e\u0442\u043b\u0438\u0447\u043d\u043e! +2 XP')
    else:
        _answer_callback(callback_query_id, '\u0417\u0430\u043f\u043e\u043c\u043d\u0438 \u044d\u0442\u043e \u0441\u043b\u043e\u0432\u043e! \U0001f4dd')

    if message_id:
        _remove_reply_markup(chat_id, message_id)


def _handle_settings_callback(chat_id: int, telegram_id: int,
                               callback_data: str, callback_query_id: str,
                               message_id: int | None = None) -> None:
    """Handle inline button press for settings — edit existing message."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        return

    # Timezone selection screen
    if callback_data == 'change_timezone':
        _answer_callback(callback_query_id, '')
        _edit_message(
            chat_id, message_id,
            'Выбери часовой пояс:',
            reply_markup=_build_timezone_keyboard(),
        )
        return

    # Timezone chosen
    if callback_data.startswith('tz:'):
        tz_id = callback_data[3:]
        if tz_id in TIMEZONE_OPTIONS:
            tg_user.timezone = tz_id
            db.session.commit()
        _answer_callback(callback_query_id, 'Часовой пояс обновлён!')
        _edit_message(
            chat_id, message_id,
            _settings_text(tg_user),
            reply_markup=_build_settings_keyboard(tg_user),
        )
        return

    # Time picker screen
    if callback_data.startswith('time:'):
        hour_field = callback_data[5:]
        valid_fields = ('morning_hour', 'nudge_hour', 'evening_hour', 'streak_hour')
        if hour_field in valid_fields:
            current_hour = getattr(tg_user, hour_field)
            label = dict(
                morning_hour='утреннего напоминания',
                nudge_hour='дневного напоминания',
                evening_hour='вечерней сводки',
                streak_hour='защиты стрика',
            ).get(hour_field, '')
            _answer_callback(callback_query_id, '')
            _edit_message(
                chat_id, message_id,
                f'Выбери время для {label}:',
                reply_markup=_build_time_picker(hour_field, current_hour),
            )
        return

    # Time chosen
    if callback_data.startswith('set_time:'):
        parts = callback_data.split(':')
        if len(parts) == 3:
            hour_field, hour_str = parts[1], parts[2]
            valid_fields = ('morning_hour', 'nudge_hour', 'evening_hour', 'streak_hour')
            if hour_field in valid_fields and hour_str.isdigit():
                hour = int(hour_str)
                if 0 <= hour <= 23:
                    setattr(tg_user, hour_field, hour)
                    db.session.commit()
        _answer_callback(callback_query_id, f'Установлено: {hour:02d}:00')
        _edit_message(
            chat_id, message_id,
            _settings_text(tg_user),
            reply_markup=_build_settings_keyboard(tg_user),
        )
        return

    # Back to settings from sub-screen
    if callback_data == 'back_to_settings':
        _answer_callback(callback_query_id, '')
        _edit_message(
            chat_id, message_id,
            _settings_text(tg_user),
            reply_markup=_build_settings_keyboard(tg_user),
        )
        return

    # Toggle notification settings
    field_map = {
        'toggle_morning_reminder': 'morning_reminder',
        'toggle_evening_summary': 'evening_summary',
        'toggle_nudge_enabled': 'nudge_enabled',
        'toggle_streak_alert': 'streak_alert',
    }

    field = field_map.get(callback_data)
    if not field:
        return

    current_value = getattr(tg_user, field)
    setattr(tg_user, field, not current_value)
    db.session.commit()

    _answer_callback(callback_query_id)
    _edit_message(
        chat_id, message_id,
        _settings_text(tg_user),
        reply_markup=_build_settings_keyboard(tg_user),
    )


def _handle_plan(chat_id: int, telegram_id: int) -> None:
    """Handle /plan command — show today's checklist with progress."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Сначала привяжи аккаунт: /link XXXXXX')
        return

    from app.telegram.queries import (
        get_daily_summary, get_current_streak, get_cards_url,
        get_daily_plan_for_telegram,
    )
    from app.achievements.streak_service import get_or_create_coins

    user_id = tg_user.user_id
    user_tz = tg_user.timezone
    site_url = current_app.config.get('SITE_URL', '')
    cards_url = get_cards_url(user_id, site_url) if site_url else ''

    plan = get_daily_plan_for_telegram(user_id, tz=user_tz)
    summary = get_daily_summary(user_id, tz=user_tz)
    streak = get_current_streak(user_id, tz=user_tz)
    coins = get_or_create_coins(user_id)

    if plan.get('mission'):
        from app.achievements.streak_service import _compute_phase_completion
        from app.telegram.notifications import format_mission_plan_text
        completion = _compute_phase_completion(plan['phases'], summary)
        for p in plan['phases']:
            p['completed'] = completion.get(p['id'], False)
        text = format_mission_plan_text(plan)
        text += f'\n\n\U0001f525 {streak} дней подряд  \U0001f4b0 {coins.balance}'
        buttons: list[list[dict]] = []
        if site_url:
            buttons.append([{
                'text': '\U0001f3af Начать занятие',
                'url': f'{site_url}/study?from=telegram',
            }])
        reply_markup = {'inline_keyboard': buttons} if buttons else None
        _send_message(chat_id, text, reply_markup=reply_markup)
        return

    if plan.get('mode') == 'linear':
        from app.achievements.streak_service import _compute_linear_slot_completion
        from app.telegram.notifications import format_linear_plan_text

        completion = _compute_linear_slot_completion(plan.get('baseline_slots') or [], summary)
        for slot in plan.get('baseline_slots') or []:
            kind = slot.get('kind', '')
            slot['completed'] = completion.get(kind, False)

        text = format_linear_plan_text(plan)
        text += f'\n\n\U0001f525 {streak} дней подряд  \U0001f4b0 {coins.balance}'
        buttons: list[list[dict]] = []
        next_slot = next(
            (slot for slot in plan.get('baseline_slots') or [] if not slot.get('completed') and slot.get('url')),
            None,
        )
        if site_url and next_slot:
            buttons.append([{
                'text': '\U0001f3af Продолжить',
                'url': site_url.rstrip('/') + next_slot['url'],
            }])
        reply_markup = {'inline_keyboard': buttons} if buttons else None
        _send_message(chat_id, text, reply_markup=reply_markup)
        return

    # Build checklist items: (done, label, url_or_none)
    steps: list[tuple[bool, str, str | None]] = []

    # 1. Lesson
    if plan.get('next_lesson'):
        nl = plan['next_lesson']
        done = summary.get('lessons_count', 0) > 0
        label = f'Урок — Модуль {nl.get("module_number", "")}, {nl["title"]}'
        url = f'{site_url}/learn/{nl["lesson_id"]}/?from=telegram' if site_url and nl.get('lesson_id') else None
        steps.append((done, label, url))

    # 2. Grammar
    if plan.get('grammar_topic'):
        gt = plan['grammar_topic']
        done = summary.get('grammar_exercises', 0) > 0
        gt_detail = ''
        if summary.get('grammar_exercises', 0) > 0:
            gt_detail = f' ({summary["grammar_correct"]}/{summary["grammar_exercises"]})'
        label = f'Грамматика — {gt["title"]}{gt_detail}'
        url = f'{site_url}/grammar-lab/practice/topic/{gt["topic_id"]}?from=telegram' if site_url and gt.get('topic_id') else None
        steps.append((done, label, url))

    # 3. Words
    words_due = plan.get('words_due', 0)
    words_new = plan.get('words_new', 0)
    words_review = plan.get('words_review', 0)
    words_done = summary.get('words_reviewed', 0) > 0
    parts = []
    if words_new > 0:
        parts.append(f'{words_new} новых')
    if words_review > 0:
        parts.append(f'{words_review} на повтор')
    words_label = f'Слова — {", ".join(parts)}' if parts else 'Слова — все повторены'
    words_url = f'{cards_url}?from=telegram' if cards_url else None
    steps.append((words_done, words_label, words_url))

    # 4. Book reading
    book = plan.get('book_to_read')
    bc = plan.get('book_course_lesson')
    if book or bc:
        books_done = len(summary.get('books_read', [])) > 0 or summary.get('book_course_lessons_today', 0) > 0
        if bc:
            course_title = bc.get('course_title', 'Книжный курс')
            day_num = bc.get('day_number', '')
            label = f'Чтение — {course_title}, день {day_num}'
            url = (f'{site_url}/book-courses/{bc["course_id"]}/modules/{bc["module_id"]}'
                   f'/lessons/{bc["lesson_id"]}') if site_url and bc.get('course_id') and bc.get('module_id') and bc.get('lesson_id') else None
        elif book:
            label = f'Чтение — {book["title"]}'
            url = f'{site_url}/books/{book["id"]}' if site_url and book.get('id') else None
        else:
            label = 'Чтение'
            url = None
        steps.append((books_done, label, url))

    # Count completed steps
    done_count = sum(1 for done, _, _ in steps if done)
    total_count = len(steps)

    lines = [f'\U0001f4cb План на сегодня ({done_count} из {total_count}):', '']
    for done, label, _ in steps:
        icon = '\u2705' if done else '\u2b1c'
        lines.append(f'{icon} {label}')

    lines.append('')
    lines.append(f'\U0001f525 {streak} дней подряд  \U0001f4b0 {coins.balance}')

    # Inline buttons for incomplete steps
    buttons: list[list[dict]] = []
    for done, label, url in steps:
        if not done and url:
            # Short button text from label
            short = label.split(' — ')[0] if ' — ' in label else label
            buttons.append([{'text': f'\u25b6 {short}', 'url': url}])

    reply_markup = {'inline_keyboard': buttons} if buttons else None
    _send_message(chat_id, '\n'.join(lines), reply_markup=reply_markup)


def _handle_stats(chat_id: int, telegram_id: int) -> None:
    """Handle /stats command."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Сначала привяжи аккаунт: /link XXXXXX')
        return

    from app.telegram.queries import get_quick_stats, get_cards_url
    stats = get_quick_stats(tg_user.user_id, tz=tg_user.timezone)

    lines = ['📊 Статистика\n']
    if stats.get('streak', 0) > 0:
        lines.append(f"🔥 Стрик: {stats['streak']} дн.")
    lines.append(f"📚 Уроков пройдено: {stats.get('lessons_completed', 0)}")
    lines.append(f"✏️ Упражнений решено: {stats.get('exercises_done', 0)}")
    lines.append(f"📖 Слов на повторении: {stats.get('words_in_srs', 0)}")

    if stats.get('books'):
        lines.append('')
        for book in stats['books']:
            pct = book['progress_pct']
            bar = _progress_bar(pct)
            lines.append(f"📕 {book['title']}")
            lines.append(f"   {bar} {pct}% · гл. {book['chapters_read']}/{book['chapters_total']}")

    site_url = current_app.config.get('SITE_URL', '')
    if site_url:
        cards = get_cards_url(tg_user.user_id, site_url)
        lines.append('')
        lines.append(f'📚 {site_url}/curriculum/levels')
        lines.append(f'📖 {cards}')
        lines.append(f'📕 {site_url}/curriculum/book-courses')

    # Referral stats
    from app.auth.models import User
    referral_count = User.query.filter_by(referred_by_id=tg_user.user_id).count()
    if referral_count > 0:
        lines.append(f'\n👥 Приглашено друзей: {referral_count}')

    _send_message(chat_id, '\n'.join(lines))


def _handle_invite(chat_id: int, telegram_id: int) -> None:
    """Handle /invite command — generate shareable invite message."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Сначала привяжи аккаунт: /link XXXXXX')
        return

    from app.auth.models import User
    user = User.query.get(tg_user.user_id)
    if not user:
        _send_message(chat_id, 'Ошибка: пользователь не найден.')
        return

    ref_code = user.ensure_referral_code()
    invite_link = f'https://llt-english.com/register?ref={ref_code}'

    referral_count = User.query.filter_by(referred_by_id=user.id).count()
    stats_line = f'\n👥 Ты уже пригласил: {referral_count}' if referral_count > 0 else ''

    message = (
        '📨 Поделись этим сообщением с друзьями:\n\n'
        '---\n'
        'Привет! Я учу английский на LLT English — '
        'бесплатная платформа с уроками, карточками и книгами.\n\n'
        f'Присоединяйся: {invite_link}\n'
        '---\n'
        f'{stats_line}\n'
        '💡 За каждого друга ты получишь +100 XP!'
    )

    _send_message(chat_id, message)


# ── Main dispatcher ─────────────────────────────────────────────────

def handle_update(data: dict) -> None:
    """Dispatch an incoming Telegram update to the appropriate handler."""
    PendingTelegramLink.cleanup_expired()

    # Handle callback queries (inline button presses)
    callback_query = data.get('callback_query')
    if callback_query:
        chat_id = callback_query['message']['chat']['id']
        telegram_id = callback_query['from']['id']
        cb_data = callback_query['data']
        cb_id = callback_query['id']
        message_id = callback_query['message'].get('message_id')

        if cb_data.startswith('reflect:'):
            _handle_reflection_callback(
                chat_id, telegram_id, cb_data, cb_id,
                message_id=message_id,
            )
        elif cb_data == 'streak_repair':
            _handle_streak_repair_callback(
                chat_id, telegram_id, cb_id,
                message_id=message_id,
            )
        elif cb_data in ('wotd_know', 'wotd_dont_know'):
            _handle_wotd_callback(
                chat_id, telegram_id, cb_data, cb_id,
                message_id=message_id,
            )
        else:
            _handle_settings_callback(
                chat_id, telegram_id, cb_data, cb_id,
                message_id=message_id,
            )
        return

    message = data.get('message')
    if not message:
        return

    chat_id = message['chat']['id']
    telegram_id = message['from']['id']
    username = message['from'].get('username')
    text = (message.get('text') or '').strip()

    if not text:
        return

    if text.startswith('/'):
        # Any command clears pending /link state
        PendingTelegramLink.remove(telegram_id)

    if text == '/start' or text.startswith('/start '):
        _handle_start(chat_id, telegram_id, username)
    elif text.startswith('/link'):
        args = text[5:].strip()  # after "/link"
        _handle_link(chat_id, telegram_id, username, args)
    elif text == '/unlink':
        _handle_unlink(chat_id, telegram_id)
    elif text == '/settings':
        _handle_settings(chat_id, telegram_id)
    elif text == '/plan':
        _handle_plan(chat_id, telegram_id)
    elif text == '/stats':
        _handle_stats(chat_id, telegram_id)
    elif text == '/invite':
        _handle_invite(chat_id, telegram_id)
    elif text == '/help':
        _send_message(chat_id, HELP_TEXT)
    elif (PendingTelegramLink.is_pending(telegram_id)
          and text.isdigit() and len(text) == 6):
        # Two-step /link flow: user sent code after /link
        PendingTelegramLink.remove(telegram_id)
        _handle_link(chat_id, telegram_id, username, text)
    else:
        PendingTelegramLink.remove(telegram_id)
        _send_message(chat_id, (
            'Доступные команды:\n'
            '/plan — план на сегодня\n'
            '/stats — статистика\n'
            '/settings — настройки уведомлений\n'
            '/unlink — отвязать аккаунт\n'
            '/help — справка'
        ))
