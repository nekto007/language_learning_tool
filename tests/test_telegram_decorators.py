"""Tests for telegram authentication decorators"""
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock, patch
from flask import jsonify
from app.telegram.decorators import (
    telegram_auth_required,
    telegram_read_required,
    telegram_write_required,
    telegram_admin_required
)


@pytest.fixture
def telegram_token(db_session, test_user):
    """Create a valid telegram token"""
    from app.telegram.models import TelegramToken
    from datetime import timezone

    token = TelegramToken(
        user_id=test_user.id,
        token='test_valid_token_123',
        scope='admin',  # Has all permissions
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(token)
    db_session.commit()
    return token


@pytest.fixture
def expired_token(db_session, test_user):
    """Create an expired telegram token"""
    from app.telegram.models import TelegramToken
    from datetime import timezone

    token = TelegramToken(
        user_id=test_user.id,
        token='test_expired_token_456',
        scope='read',
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    db_session.add(token)
    db_session.commit()
    return token


@pytest.fixture
def read_only_token(db_session, test_user):
    """Create a read-only telegram token"""
    from app.telegram.models import TelegramToken
    from datetime import timezone

    token = TelegramToken(
        user_id=test_user.id,
        token='test_read_token_789',
        scope='read',
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(token)
    db_session.commit()
    return token


class TestTelegramAuthRequired:
    """Test telegram_auth_required decorator"""

    def test_missing_token(self, client):
        """Test request without token header"""
        @telegram_auth_required('read')
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            with client.application.test_request_context(headers={}):
                response, status_code = test_route()
                data = response.get_json()

                assert status_code == 401
                assert data['success'] is False
                assert 'Missing authentication token' in data['error']

    def test_invalid_token(self, client):
        """Test request with invalid token"""
        @telegram_auth_required('read')
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': 'invalid_token_xyz'}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                data = response.get_json()

                assert status_code == 401
                assert data['success'] is False
                assert 'Invalid or expired' in data['error']

    def test_expired_token(self, client, expired_token):
        """Test request with expired token"""
        @telegram_auth_required('read')
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': expired_token.token}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                data = response.get_json()

                assert status_code == 401
                assert data['success'] is False
                assert 'Invalid or expired' in data['error']

    def test_valid_token(self, client, telegram_token):
        """Test request with valid token"""
        @telegram_auth_required('read')
        def test_route(token, user):
            return jsonify({'success': True, 'user_id': user.id})

        with client.application.app_context():
            headers = {'X-Telegram-Token': telegram_token.token}
            with client.application.test_request_context(headers=headers):
                response = test_route()
                # When successful, only response is returned (no tuple)
                data = response.get_json()

                assert data['success'] is True
                assert data['user_id'] == telegram_token.user_id

    def test_insufficient_scope_read_requires_write(self, client, read_only_token):
        """Test read token trying to access write endpoint"""
        @telegram_auth_required('write')
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': read_only_token.token}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                data = response.get_json()

                assert status_code == 403
                assert data['success'] is False
                assert 'Insufficient permissions' in data['error']
                assert 'write' in data['error']

    def test_insufficient_scope_read_requires_admin(self, client, read_only_token):
        """Test read token trying to access admin endpoint"""
        @telegram_auth_required('admin')
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': read_only_token.token}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                data = response.get_json()

                assert status_code == 403
                assert data['success'] is False
                assert 'Insufficient permissions' in data['error']
                assert 'admin' in data['error']

    def test_admin_token_can_access_all(self, client, telegram_token):
        """Test admin token can access read, write, and admin endpoints"""
        @telegram_auth_required('admin')
        def admin_route(token, user):
            return jsonify({'success': True, 'scope': 'admin'})

        @telegram_auth_required('write')
        def write_route(token, user):
            return jsonify({'success': True, 'scope': 'write'})

        @telegram_auth_required('read')
        def read_route(token, user):
            return jsonify({'success': True, 'scope': 'read'})

        with client.application.app_context():
            headers = {'X-Telegram-Token': telegram_token.token}

            # Test admin endpoint
            with client.application.test_request_context(headers=headers):
                response = admin_route()
                assert response.get_json()['success'] is True

            # Test write endpoint
            with client.application.test_request_context(headers=headers):
                response = write_route()
                assert response.get_json()['success'] is True

            # Test read endpoint
            with client.application.test_request_context(headers=headers):
                response = read_route()
                assert response.get_json()['success'] is True


class TestConvenienceDecorators:
    """Test convenience decorator functions"""

    def test_telegram_read_required(self, client, telegram_token):
        """Test telegram_read_required decorator"""
        @telegram_read_required
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': telegram_token.token}
            with client.application.test_request_context(headers=headers):
                response = test_route()
                assert response.get_json()['success'] is True

    def test_telegram_write_required(self, client, telegram_token):
        """Test telegram_write_required decorator"""
        @telegram_write_required
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': telegram_token.token}
            with client.application.test_request_context(headers=headers):
                response = test_route()
                assert response.get_json()['success'] is True

    def test_telegram_admin_required(self, client, telegram_token):
        """Test telegram_admin_required decorator"""
        @telegram_admin_required
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': telegram_token.token}
            with client.application.test_request_context(headers=headers):
                response = test_route()
                assert response.get_json()['success'] is True

    def test_write_required_blocks_read_token(self, client, read_only_token):
        """Test write_required blocks read-only token"""
        @telegram_write_required
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': read_only_token.token}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                assert status_code == 403

    def test_admin_required_blocks_read_token(self, client, read_only_token):
        """Test admin_required blocks read-only token"""
        @telegram_admin_required
        def test_route(token, user):
            return jsonify({'success': True})

        with client.application.app_context():
            headers = {'X-Telegram-Token': read_only_token.token}
            with client.application.test_request_context(headers=headers):
                response, status_code = test_route()
                assert status_code == 403