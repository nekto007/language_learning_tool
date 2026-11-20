"""
Вспомогательные функции для rate limiting
"""
from flask import request
from flask_login import current_user


def get_remote_address_key():
    """
    Получает IP-адрес клиента для rate limiting

    Returns:
        str: IP адрес клиента
    """
    # ProxyFix resolves the configured trusted proxy hop into remote_addr.
    # Raw forwarding headers may contain an attacker-controlled prefix.
    return request.remote_addr or '127.0.0.1'


def _identity_key(value):
    value = value.strip()[:254]
    # JSON can contain an unpaired UTF-16 surrogate. Redis encodes keys before
    # the login handler validates credentials, so malformed input must use an
    # ordinary IP bucket rather than raise (or disable throttling on errors).
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return f"ip:{get_remote_address_key()}"
    # Native login compares email addresses case-insensitively.
    # Keep one throttle bucket for case variants of that identity.
    return f"username:{value.lower() if '@' in value else value}"


def get_username_key():
    """
    Получает ключ для rate limiting по username

    Используется для защиты конкретных аккаунтов от целевых атак
    При попытке входа с неправильным паролем - лимит на username

    Returns:
        str: username из запроса или IP если username отсутствует
    """
    # Пытаемся получить username из JSON
    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            username = data.get('username')
            if isinstance(username, str) and username.strip():
                return _identity_key(username)

    # Пытаемся получить из form data
    username = request.form.get('username') or request.form.get('username_or_email')
    if username:
        return _identity_key(username)

    # Если authenticated user - используем его username
    if current_user and current_user.is_authenticated:
        return f"username:{current_user.username}"

    # Fallback на IP
    return f"ip:{get_remote_address_key()}"


def get_authenticated_user_key():
    """
    Получает ключ для rate limiting аутентифицированного пользователя

    Returns:
        str: user_id если аутентифицирован, иначе IP
    """
    if current_user and current_user.is_authenticated:
        return f"user:{current_user.id}"
    return f"ip:{get_remote_address_key()}"


def get_composite_key():
    """
    Комбинированный ключ: IP + username (если есть)

    Полезно для двухуровневой защиты

    Returns:
        str: Комбинированный ключ
    """
    ip = get_remote_address_key()
    username_key = get_username_key()

    if username_key.startswith('username:'):
        return f"{ip}:{username_key}"
    return ip
