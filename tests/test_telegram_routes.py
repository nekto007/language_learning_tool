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

    @patch('app.telegram.bot.handle_update')
    def test_webhook_duplicate_update_id_skips_handler(self, mock_handle, app, client):
        """Same update_id processed twice — handler called only once (idempotency)."""
        from app.telegram.routes import _update_tracker
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'idem-secret'
        # Reset tracker state for isolation (use a unique update_id unlikely to collide)
        update_id = 999888777
        # Ensure it's not in tracker
        _update_tracker._seen.discard(update_id)

        payload = {'update_id': update_id, 'message': {'text': '/start'}}
        headers = {'X-Telegram-Bot-Api-Secret-Token': 'idem-secret'}

        resp1 = client.post('/telegram/webhook', json=payload, headers=headers)
        resp2 = client.post('/telegram/webhook', json=payload, headers=headers)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert mock_handle.call_count == 1

    @patch('app.telegram.bot.handle_update')
    def test_webhook_different_update_ids_both_processed(self, mock_handle, app, client):
        """Different update_ids are both delivered to handler."""
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'idem-secret2'
        headers = {'X-Telegram-Bot-Api-Secret-Token': 'idem-secret2'}

        client.post('/telegram/webhook', json={'update_id': 111000001}, headers=headers)
        client.post('/telegram/webhook', json={'update_id': 111000002}, headers=headers)

        assert mock_handle.call_count == 2

    @patch('app.telegram.bot.handle_update')
    def test_webhook_no_update_id_always_processed(self, mock_handle, app, client):
        """Updates without update_id field are never deduplicated."""
        app.config['TELEGRAM_WEBHOOK_SECRET'] = 'idem-secret3'
        headers = {'X-Telegram-Bot-Api-Secret-Token': 'idem-secret3'}
        payload = {'message': {'text': '/start'}}  # no update_id

        client.post('/telegram/webhook', json=payload, headers=headers)
        client.post('/telegram/webhook', json=payload, headers=headers)

        assert mock_handle.call_count == 2


class TestLinkingHijackPrevention:
    """Account linking cannot be used to hijack another user's account."""

    def test_telegram_id_already_linked_blocks_relink(self, db_session, test_user):
        """telegram_id already linked to an account — /link with new code rejected."""
        from app.telegram.bot import _handle_link

        # test_user already has a TelegramUser
        tg_user = TelegramUser(
            user_id=test_user.id,
            telegram_id=500000001,
            username='hijack_test',
            is_active=True,
        )
        db_session.add(tg_user)
        db_session.commit()

        sent = []
        with patch('app.telegram.bot._send_message', side_effect=lambda c, t, **kw: sent.append(t)):
            with patch('app.telegram.models.TelegramLinkCode.verify') as mock_verify:
                mock_code = MagicMock()
                mock_code.user_id = test_user.id + 999  # different user's code
                mock_verify.return_value = mock_code

                _handle_link(
                    chat_id=500000001,
                    telegram_id=500000001,
                    username='hijack_test',
                    args='123456',
                )

        assert len(sent) == 1
        assert 'уже привязан' in sent[0].lower() or 'unlink' in sent[0].lower()

    def test_link_code_must_be_valid_to_link(self, db_session, test_user):
        """Invalid / expired code returns error without linking."""
        from app.telegram.bot import _handle_link

        sent = []
        with patch('app.telegram.bot._send_message', side_effect=lambda c, t, **kw: sent.append(t)):
            with patch('app.telegram.models.TelegramLinkCode.verify', return_value=None):
                _handle_link(
                    chat_id=600000001,
                    telegram_id=600000001,
                    username='nocode',
                    args='000000',
                )

        assert len(sent) == 1
        assert 'неверный' in sent[0].lower() or 'истёк' in sent[0].lower()
        # Verify no TelegramUser was created
        assert TelegramUser.query.filter_by(telegram_id=600000001).first() is None

    def test_link_code_consumed_after_use(self, app, db_session, test_user):
        """Link code is consumed (one-time use) after successful linking."""
        from app.telegram.models import TelegramLinkCode

        link_code = TelegramLinkCode.generate(test_user.id)
        code_value = link_code.code

        # Verify code exists
        assert TelegramLinkCode.verify(code_value) is not None

        # Use the code via the bot handler
        from app.telegram.bot import _handle_link
        with patch('app.telegram.bot._send_message'):
            _handle_link(
                chat_id=700000001,
                telegram_id=700000001,
                username='codeuser',
                args=code_value,
            )

        # Code should be consumed
        assert TelegramLinkCode.verify(code_value) is None

    def test_bot_exception_log_does_not_include_token(self, app):
        """RequestException logging uses type name only, not full exception (which includes URL with token)."""
        import logging as _logging
        from unittest.mock import patch
        import requests as _requests

        app.config['TELEGRAM_BOT_TOKEN'] = 'SECRET_BOT_TOKEN_12345'

        log_records = []

        class CapturingHandler(_logging.Handler):
            def emit(self, record):
                log_records.append(self.format(record))

        handler = CapturingHandler()
        tg_logger = _logging.getLogger('app.telegram.bot')
        tg_logger.addHandler(handler)
        tg_logger.setLevel(_logging.ERROR)

        try:
            with app.app_context():
                from app.telegram.bot import _send_message
                with patch('requests.post', side_effect=_requests.ConnectionError(
                    'HTTPSConnectionPool: Max retries exceeded with url: /botSECRET_BOT_TOKEN_12345/sendMessage'
                )):
                    _send_message(chat_id=1, text='test')
        finally:
            tg_logger.removeHandler(handler)

        for record in log_records:
            assert 'SECRET_BOT_TOKEN_12345' not in record, (
                f'Bot token leaked in log: {record}'
            )
