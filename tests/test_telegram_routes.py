"""Tests for Telegram routes: generate-code, unlink, status, webhook."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from app.telegram.models import TelegramUser, TelegramLinkCode


class TestGenerateCode:
    """POST /telegram/generate-code"""

    @pytest.mark.smoke
    def test_generate_code_success(self, authenticated_client, db_session, test_user):
        resp = authenticated_client.post('/telegram/generate-code')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['code']) == 6
        assert data['code'].isdigit()
        assert data['expires_in_minutes'] == TelegramLinkCode.CODE_TTL_MINUTES

    def test_generate_code_already_linked(self, authenticated_client, db_session, test_user):
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=123456789,
            username='testbot',
            is_active=True,
        )
        db_session.add(tg_user)
        db_session.commit()

        resp = authenticated_client.post('/telegram/generate-code')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'уже привязан' in data['error']

    def test_generate_code_inactive_link_allowed(self, authenticated_client, db_session, test_user):
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=123456789,
            username='testbot',
            is_active=False,
        )
        db_session.add(tg_user)
        db_session.commit()

        resp = authenticated_client.post('/telegram/generate-code')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_generate_code_unauthenticated(self, client):
        resp = client.post('/telegram/generate-code')
        assert resp.status_code in (302, 401)


class TestUnlink:
    """POST /telegram/unlink"""

    @pytest.mark.smoke
    def test_unlink_success(self, authenticated_client, db_session, test_user):
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=987654321,
            username='linked_user',
            is_active=True,
        )
        db_session.add(tg_user)
        db_session.commit()

        resp = authenticated_client.post('/telegram/unlink')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        assert TelegramUser.query.filter_by(user_id=test_user.id).first() is None

    def test_unlink_not_linked(self, authenticated_client, db_session, test_user):
        resp = authenticated_client.post('/telegram/unlink')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'не привязан' in data['error']

    def test_unlink_unauthenticated(self, client):
        resp = client.post('/telegram/unlink')
        assert resp.status_code in (302, 401)


class TestLinkStatus:
    """GET /telegram/status"""

    @pytest.mark.smoke
    def test_status_linked(self, authenticated_client, db_session, test_user):
        now = datetime.now(timezone.utc)
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=111222333,
            username='status_user',
            is_active=True,
            linked_at=now,
        )
        db_session.add(tg_user)
        db_session.commit()

        resp = authenticated_client.get('/telegram/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['linked'] is True
        assert data['username'] == 'status_user'
        assert data['linked_at'] is not None

    def test_status_not_linked(self, authenticated_client, db_session, test_user):
        resp = authenticated_client.get('/telegram/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['linked'] is False

    def test_status_inactive_link(self, authenticated_client, db_session, test_user):
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=444555666,
            username='inactive_user',
            is_active=False,
        )
        db_session.add(tg_user)
        db_session.commit()

        resp = authenticated_client.get('/telegram/status')
        assert resp.status_code == 200
        assert resp.get_json()['linked'] is False

    def test_status_unauthenticated(self, client):
        resp = client.get('/telegram/status')
        assert resp.status_code in (302, 401)


class TestWebhook:
    """POST /telegram/webhook"""

    @pytest.mark.smoke
    @patch('app.telegram.bot.handle_update')
    def test_webhook_valid_request(self, mock_handle, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'test-secret-123'
        payload = {'update_id': 1, 'message': {'text': '/start'}}

        resp = client.post(
            '/telegram/webhook',
            json=payload,
            headers={'X-Telegram-Bot-Api-Secret-Token': 'test-secret-123'},
        )
        assert resp.status_code == 200
        mock_handle.assert_called_once_with(payload)

    def test_webhook_missing_secret_config(self, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = None
        resp = client.post(
            '/telegram/webhook',
            json={'update_id': 1},
            headers={'X-Telegram-Bot-Api-Secret-Token': 'anything'},
        )
        assert resp.status_code == 500

    def test_webhook_invalid_token(self, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'correct-secret'
        resp = client.post(
            '/telegram/webhook',
            json={'update_id': 1},
            headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong-secret'},
        )
        assert resp.status_code == 403

    def test_webhook_missing_token(self, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'correct-secret'
        resp = client.post(
            '/telegram/webhook',
            json={'update_id': 1},
        )
        assert resp.status_code == 403

    def test_webhook_invalid_json(self, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'test-secret'
        resp = client.post(
            '/telegram/webhook',
            data='not json',
            content_type='application/json',
            headers={'X-Telegram-Bot-Api-Secret-Token': 'test-secret'},
        )
        assert resp.status_code == 400

    @patch('app.telegram.bot.handle_update', side_effect=Exception('bot error'))
    def test_webhook_handler_exception_still_returns_200(self, mock_handle, app, client):
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'test-secret'
        resp = client.post(
            '/telegram/webhook',
            json={'update_id': 1},
            headers={'X-Telegram-Bot-Api-Secret-Token': 'test-secret'},
        )
        assert resp.status_code == 200
