"""Long-polling mode for local development (no webhook needed)."""
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

_polling_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_polling(app) -> None:
    """Start polling in a background thread."""
    global _polling_thread

    token = app.config.get('TELEGRAM_BOT_TOKEN')
    if not token:
        return

    if _polling_thread is not None and _polling_thread.is_alive():
        return

    # Delete any existing webhook so polling works
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/deleteWebhook',
            timeout=10,
        )
    except requests.RequestException:
        pass

    # Register bot commands menu
    _set_bot_commands(token)

    _stop_event.clear()
    _polling_thread = threading.Thread(
        target=_poll_loop,
        args=(app, token),
        daemon=True,
        name='telegram-polling',
    )
    _polling_thread.start()
    logger.info('Telegram polling started')


def stop_polling() -> None:
    """Stop the polling thread."""
    _stop_event.set()


def _set_bot_commands(token: str) -> None:
    """Register bot menu commands with Telegram."""
    commands = [
        {'command': 'stats', 'description': 'Статистика'},
        {'command': 'settings', 'description': 'Настройки уведомлений'},
        {'command': 'link', 'description': 'Привязать аккаунт'},
        {'command': 'unlink', 'description': 'Отвязать аккаунт'},
    ]
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/setMyCommands',
            json={'commands': commands},
            timeout=10,
        )
        if resp.ok:
            logger.info('Bot commands registered')
    except requests.RequestException:
        pass


def _poll_loop(app, token: str) -> None:
    """Fetch updates from Telegram using getUpdates."""
    offset = 0

    while not _stop_event.is_set():
        try:
            resp = requests.get(
                f'https://api.telegram.org/bot{token}/getUpdates',
                params={'offset': offset, 'timeout': 30},
                timeout=35,
            )

            if not resp.ok:
                logger.warning('getUpdates error: %s', resp.text)
                time.sleep(5)
                continue

            data = resp.json()
            updates = data.get('result', [])

            for update in updates:
                offset = update['update_id'] + 1
                with app.app_context():
                    try:
                        from app.telegram.bot import handle_update
                        handle_update(update)
                    except Exception:
                        logger.exception('Error handling update %s', update.get('update_id'))

        except requests.Timeout:
            continue
        except requests.RequestException:
            logger.exception('Polling network error')
            time.sleep(5)
        except Exception:
            logger.exception('Unexpected polling error')
            time.sleep(5)
