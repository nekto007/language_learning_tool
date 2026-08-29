"""
Контракт JWT-ветки `api_auth_required` (`app/api/decorators.py`).

Фаза 2 ремедиации «План дня», кластер D:

- `DP-096`: тело эндпоинта исполнялось внутри `except Exception` JWT-ветки,
  поэтому настоящая 500 маскировалась под `401 Invalid or expired token`.
- `DP-098`: JWT-ветка звала `login_user()` и выдавала сессионную куку на
  чистый API-вызов.
"""
import logging

import pytest
from flask_login import current_user


def _access_token(app, user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return create_access_token(identity=str(user.id))


# ── DP-096: ошибка обработчика — это 500, а не «протухший токен» ──


def test_handler_exception_under_jwt_is_not_masked_as_401(app, test_user, caplog):
    """Сбой ВНУТРИ обработчика обязан пробиться наружу, а не стать 401."""
    from app.api.decorators import api_auth_required

    token = _access_token(app, test_user)

    @api_auth_required
    def _endpoint():
        raise RuntimeError('handler blew up')

    with app.test_request_context(
        '/api/test', headers={'Authorization': f'Bearer {token}'}
    ):
        with caplog.at_level(logging.WARNING, logger='app.api.decorators'):
            with pytest.raises(RuntimeError, match='handler blew up'):
                _endpoint()

    assert not any('JWT verification failed' in r.message for r in caplog.records), (
        "Ошибка обработчика не должна логироваться как провал проверки токена"
    )


def test_handler_exception_under_jwt_becomes_500_over_http(
    app, client, test_user, monkeypatch
):
    """End-to-end: падение эндпоинта под JWT отдаёт 500, а не 401."""
    from app.api import words as words_api

    def _boom(*args, **kwargs):
        raise RuntimeError('handler blew up')

    # Сериализация ответа — последний шаг ВНУТРИ обработчика; ветка ошибок
    # самого декоратора зовёт свой `jsonify` и этой подменой не задета.
    monkeypatch.setattr(words_api, 'jsonify', _boom)

    token = _access_token(app, test_user)
    try:
        response = client.get(
            '/api/words', headers={'Authorization': f'Bearer {token}'}
        )
    except RuntimeError:
        # TESTING=True пробрасывает исключение наружу — это тоже «не 401».
        return
    assert response.status_code == 500, (
        "Сбой обработчика не должен выглядеть как невалидный токен"
    )


def test_invalid_token_still_returns_401(app, client, test_user):
    """Сужение `try` не должно ослабить разбор самого токена."""
    response = client.get(
        '/api/words', headers={'Authorization': 'Bearer not-a-real-jwt'}
    )
    assert response.status_code == 401
    assert response.get_json()['error'] == 'Invalid or expired token'


def test_non_numeric_identity_returns_401_not_500(app, client):
    """Нечисловой `sub` — негодный токен (401), а не DataError на `filter_by`."""
    from flask_jwt_extended import create_access_token

    with app.app_context():
        token = create_access_token(identity='not-a-user-id')

    response = client.get(
        '/api/words', headers={'Authorization': f'Bearer {token}'}
    )
    assert response.status_code == 401
    assert response.get_json()['error'] == 'Invalid or expired token'


# ── DP-098: stateless-вызов не превращается в браузерную сессию ──


def test_successful_jwt_call_sets_no_session_cookie(app, client, test_user):
    token = _access_token(app, test_user)
    response = client.get(
        '/api/words', headers={'Authorization': f'Bearer {token}'}
    )
    assert response.status_code == 200

    cookies = response.headers.getlist('Set-Cookie')
    session_cookie = app.config.get('SESSION_COOKIE_NAME', 'session')
    assert not any(c.startswith(f'{session_cookie}=') for c in cookies), (
        f"JWT-вызов не должен выдавать сессионную куку, получено: {cookies}"
    )
    assert not any(c.startswith('remember_token=') for c in cookies)


def test_successful_jwt_call_leaves_no_session_for_next_request(
    app, client, test_user
):
    """Кука не выдана — следующий вызов без токена снова неаутентифицирован."""
    token = _access_token(app, test_user)
    assert client.get(
        '/api/words', headers={'Authorization': f'Bearer {token}'}
    ).status_code == 200

    followup = client.get('/api/words')
    assert followup.status_code == 401
    assert followup.get_json()['error'] == 'Authentication required'


def test_jwt_branch_still_populates_current_user(app, test_user):
    """`current_user` в теле обработчика остаётся тем же юзером."""
    from app.api.decorators import api_auth_required

    token = _access_token(app, test_user)
    seen = {}

    @api_auth_required
    def _endpoint():
        seen['id'] = current_user.id
        seen['authenticated'] = current_user.is_authenticated
        return 'ok'

    with app.test_request_context(
        '/api/test', headers={'Authorization': f'Bearer {token}'}
    ):
        assert _endpoint() == 'ok'

    assert seen == {'id': test_user.id, 'authenticated': True}


def test_session_cookie_path_is_untouched(authenticated_client):
    """Сессионная ветка декоратора не задета правкой."""
    assert authenticated_client.get('/api/words').status_code == 200
