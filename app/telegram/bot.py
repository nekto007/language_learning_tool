"""Telegram bot command handlers."""
import logging
from typing import Any

import requests
from flask import current_app

from app.telegram.models import TelegramUser, TelegramLinkCode
from app.utils.db import db

logger = logging.getLogger(__name__)


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
    """Handle /link XXXXXX command."""
    code = args.strip()
    if not code or len(code) != 6 or not code.isdigit():
        _send_message(chat_id, 'Отправь 6-значный код: /link 123456')
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


TIMEZONE_OPTIONS = {
    'Europe/Kaliningrad': 'Калининград (UTC+2)',
    'Europe/Moscow': 'Москва (UTC+3)',
    'Europe/Samara': 'Самара (UTC+4)',
    'Asia/Yekaterinburg': 'Екатеринбург (UTC+5)',
    'Asia/Omsk': 'Омск (UTC+6)',
    'Asia/Krasnoyarsk': 'Красноярск (UTC+7)',
    'Asia/Irkutsk': 'Иркутск (UTC+8)',
    'Asia/Vladivostok': 'Владивосток (UTC+10)',
}


NOTIFICATION_LABELS = {
    'morning_reminder': ('Утро', 'morning_hour'),
    'evening_summary': ('Вечер', 'evening_hour'),
    'skip_nudge': ('День', 'nudge_hour'),
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
            time_btn('skip_nudge', 'nudge_hour', 'Днём'),
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
        'toggle_skip_nudge': 'skip_nudge',
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


def _handle_stats(chat_id: int, telegram_id: int) -> None:
    """Handle /stats command."""
    tg_user = TelegramUser.query.filter_by(telegram_id=telegram_id).first()
    if not tg_user:
        _send_message(chat_id, 'Сначала привяжи аккаунт: /link XXXXXX')
        return

    from app.telegram.queries import get_quick_stats
    stats = get_quick_stats(tg_user.user_id)

    lines = ['📊 Статистика\n']
    if stats.get('streak', 0) > 0:
        lines.append(f"🔥 Стрик: {stats['streak']} дн.")
    lines.append(f"📚 Уроков пройдено: {stats.get('lessons_completed', 0)}")
    lines.append(f"✏️ Упражнений решено: {stats.get('exercises_done', 0)}")
    lines.append(f"📖 Слов на повторении: {stats.get('words_in_srs', 0)}")

    site_url = current_app.config.get('SITE_URL', '')
    if site_url:
        lines.append(f'\n🔗 {site_url}/study')

    _send_message(chat_id, '\n'.join(lines))


# ── Main dispatcher ─────────────────────────────────────────────────

def handle_update(data: dict) -> None:
    """Dispatch an incoming Telegram update to the appropriate handler."""
    # Handle callback queries (inline button presses)
    callback_query = data.get('callback_query')
    if callback_query:
        chat_id = callback_query['message']['chat']['id']
        telegram_id = callback_query['from']['id']
        _handle_settings_callback(
            chat_id, telegram_id,
            callback_query['data'],
            callback_query['id'],
            message_id=callback_query['message'].get('message_id'),
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

    if text == '/start' or text.startswith('/start '):
        _handle_start(chat_id, telegram_id, username)
    elif text.startswith('/link'):
        args = text[5:].strip()  # after "/link"
        _handle_link(chat_id, telegram_id, username, args)
    elif text == '/unlink':
        _handle_unlink(chat_id, telegram_id)
    elif text == '/settings':
        _handle_settings(chat_id, telegram_id)
    elif text == '/stats':
        _handle_stats(chat_id, telegram_id)
    else:
        _send_message(chat_id, (
            'Доступные команды:\n'
            '/stats — статистика\n'
            '/settings — настройки уведомлений\n'
            '/unlink — отвязать аккаунт'
        ))
