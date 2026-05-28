"""Tests for Task 77: Admin SEO — GSC OAuth security and audit.

Covers:
- State parameter CSRF protection in the OAuth callback
- Refresh token stored encrypted (not plaintext)
- Disconnect clears both gsc_refresh_token and gsc_site_url
- Graceful handling of expired refresh tokens
"""
import pytest
from unittest.mock import MagicMock, patch

from app.admin.audit import AdminAuditLog
from app.admin.secret_store import decrypt_secret, encrypt_secret
from app.admin.site_settings import get_site_setting, set_site_setting
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_AUDIT = {
    'pages': [],
    'sitemap': {'url_count': 0, 'newest_lastmod': None},
    'fully_covered_count': 0,
    'reachable_count': 0,
    'total_pages': 0,
}


class TestGSCStateCsrfCheck:
    """OAuth callback must reject requests with missing or mismatched state."""

    @staticmethod
    def _google_config(app):
        """Context manager that temporarily injects dummy Google OAuth config."""
        import contextlib

        @contextlib.contextmanager
        def _cm():
            app.config['GOOGLE_CLIENT_ID'] = 'test-client-id'
            app.config['GOOGLE_CLIENT_SECRET'] = 'test-client-secret'
            try:
                yield
            finally:
                app.config.pop('GOOGLE_CLIENT_ID', None)
                app.config.pop('GOOGLE_CLIENT_SECRET', None)

        return _cm()

    @pytest.mark.smoke
    def test_no_state_in_session_redirects_with_error(self, app, client, admin_user):
        """Callback with no state in session redirects (state mismatch guard fires)."""
        with client.session_transaction() as sess:
            sess.pop('gsc_oauth_state', None)

        mock_flow = MagicMock()
        with self._google_config(app), \
             patch('app.admin.services.gsc_service.build_flow', return_value=mock_flow):
            resp = client.get(
                '/admin/seo/callback?code=fake_code&state=anything',
                follow_redirects=False,
            )

        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert 'seo' in location

    def test_mismatched_state_redirects_and_shows_message(self, app, client, admin_user):
        """Callback with wrong state redirects with 'Неверный state параметр' flash."""
        with client.session_transaction() as sess:
            sess['gsc_oauth_state'] = 'correct-state-value'

        mock_flow = MagicMock()
        with self._google_config(app), \
             patch('app.admin.services.gsc_service.build_flow', return_value=mock_flow), \
             patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_DUMMY_AUDIT):
            resp = client.get(
                '/admin/seo/callback?code=fake_code&state=wrong-state-value',
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert 'Неверный state параметр' in resp.data.decode()

    def test_correct_state_passes_csrf_check(self, app, client, admin_user):
        """Callback with matching state is not redirected for CSRF mismatch."""
        state = 'valid-state-abc123'
        with client.session_transaction() as sess:
            sess['gsc_oauth_state'] = state

        mock_flow = MagicMock()
        # Token exchange fails — that's OK, we only care the state check passes
        mock_flow.fetch_token.side_effect = Exception('token exchange failed in test')

        with self._google_config(app), \
             patch('app.admin.services.gsc_service.build_flow', return_value=mock_flow), \
             patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_DUMMY_AUDIT):
            resp = client.get(
                f'/admin/seo/callback?code=fake_code&state={state}',
                follow_redirects=True,
            )

        assert resp.status_code == 200
        # State mismatch message must NOT appear
        assert 'Неверный state параметр' not in resp.data.decode()

    def test_state_consumed_replay_is_rejected(self, app, client, admin_user):
        """State is popped from session on first use — second request with same state is rejected."""
        state = 'one-time-state-xyz'
        with client.session_transaction() as sess:
            sess['gsc_oauth_state'] = state

        mock_flow = MagicMock()

        with self._google_config(app), \
             patch('app.admin.services.gsc_service.build_flow', return_value=mock_flow):
            # First call — state is popped regardless of outcome
            client.get(f'/admin/seo/callback?code=x&state={state}')

        # Second call: session has no state → expected_state is None → CSRF fires
        with self._google_config(app), \
             patch('app.admin.services.gsc_service.build_flow', return_value=mock_flow), \
             patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_DUMMY_AUDIT):
            resp = client.get(
                f'/admin/seo/callback?code=x&state={state}',
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert 'Неверный state параметр' in resp.data.decode()

    def test_missing_config_blocks_before_state_check(self, app, client, admin_user):
        """Without GOOGLE_CLIENT_ID/SECRET, callback aborts before state check."""
        with client.session_transaction() as sess:
            sess['gsc_oauth_state'] = 'some-state'

        # Ensure config keys absent
        app.config.pop('GOOGLE_CLIENT_ID', None)
        app.config.pop('GOOGLE_CLIENT_SECRET', None)

        with patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_DUMMY_AUDIT):
            resp = client.get(
                '/admin/seo/callback?code=x&state=some-state',
                follow_redirects=True,
            )

        assert resp.status_code == 200
        # Config error message appears; state mismatch does not
        assert 'Неверный state параметр' not in resp.data.decode()


class TestGSCRefreshTokenEncryption:
    """gsc_refresh_token must be stored encrypted, not as plaintext."""

    @pytest.mark.smoke
    def test_encrypt_secret_produces_enc_v1_prefix(self, app):
        """encrypt_secret output starts with 'enc:v1:' prefix."""
        with app.app_context():
            result = encrypt_secret('my-secret-token')
        assert result.startswith('enc:v1:'), (
            f'Expected enc:v1: prefix, got: {result[:20]!r}'
        )

    def test_encrypt_secret_does_not_expose_plaintext(self, app):
        """Encrypted value does not contain the original plaintext substring."""
        token = 'super-secret-oauth-token'
        with app.app_context():
            result = encrypt_secret(token)
        assert token not in result, 'Plaintext visible in encrypted output'

    def test_decrypt_secret_roundtrip(self, app):
        """decrypt_secret(encrypt_secret(x)) == x."""
        token = 'roundtrip-token-abc123'
        with app.app_context():
            encrypted = encrypt_secret(token)
            decrypted = decrypt_secret(encrypted)
        assert decrypted == token

    def test_decrypt_empty_string_returns_empty(self, app):
        """decrypt_secret('') returns ''."""
        with app.app_context():
            assert decrypt_secret('') == ''

    def test_decrypt_none_returns_empty(self, app):
        """decrypt_secret(None) returns ''."""
        with app.app_context():
            assert decrypt_secret(None) == ''

    def test_token_stored_with_enc_prefix_in_site_settings(self, app, db_session):
        """Value set via encrypt_secret retains enc:v1: prefix in DB."""
        with app.app_context():
            encrypted = encrypt_secret('raw-refresh-token-xyz')

        set_site_setting('gsc_refresh_token', encrypted, db_session=db_session)
        db_session.flush()

        raw_value = get_site_setting('gsc_refresh_token', db_session=db_session)
        assert raw_value.startswith('enc:v1:'), (
            f'Token stored without encryption prefix: {raw_value[:40]!r}'
        )

    def test_legacy_plaintext_returned_as_is(self, app):
        """decrypt_secret returns plaintext unchanged when no enc:v1: prefix (backward compat)."""
        with app.app_context():
            result = decrypt_secret('legacy-plaintext-token')
        assert result == 'legacy-plaintext-token'

    def test_corrupt_ciphertext_returns_empty_not_raise(self, app):
        """Corrupted ciphertext returns '' without raising."""
        with app.app_context():
            result = decrypt_secret('enc:v1:!!notvalidbase64!!')
        assert result == ''


class TestGSCDisconnectClearsKeys:
    """POST /admin/seo/disconnect must clear both gsc_refresh_token and gsc_site_url."""

    @pytest.mark.smoke
    def test_disconnect_clears_both_gsc_settings(self, app, client, admin_user, db_session):
        """After disconnect, both gsc settings are empty strings."""
        with app.app_context():
            encrypted = encrypt_secret('some-refresh-token-123')
        set_site_setting('gsc_refresh_token', encrypted, db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        resp = client.post('/admin/seo/disconnect', follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            token_val = get_site_setting('gsc_refresh_token')
            site_val = get_site_setting('gsc_site_url')

        assert token_val == '', f'Expected empty refresh_token, got: {token_val!r}'
        assert site_val == '', f'Expected empty site_url, got: {site_val!r}'

    def test_disconnect_clears_refresh_token(self, app, client, admin_user, db_session):
        """gsc_refresh_token is set to '' after disconnect."""
        with app.app_context():
            encrypted = encrypt_secret('token-to-clear')
        set_site_setting('gsc_refresh_token', encrypted, db_session=db_session)
        db_session.commit()

        client.post('/admin/seo/disconnect')

        with app.app_context():
            assert get_site_setting('gsc_refresh_token') == ''

    def test_disconnect_clears_site_url(self, app, client, admin_user, db_session):
        """gsc_site_url is set to '' after disconnect."""
        set_site_setting('gsc_site_url', 'https://mysite.com/', db_session=db_session)
        db_session.commit()

        client.post('/admin/seo/disconnect')

        with app.app_context():
            assert get_site_setting('gsc_site_url') == ''

    def test_disconnect_clears_pending_oauth_session_state(self, app, client, admin_user):
        """Disconnect removes gsc_oauth_state from session to prevent replay."""
        with client.session_transaction() as sess:
            sess['gsc_oauth_state'] = 'pending-state-xyz'

        client.post('/admin/seo/disconnect', follow_redirects=False)

        with client.session_transaction() as sess:
            assert 'gsc_oauth_state' not in sess

    def test_disconnect_logs_gsc_disconnect_audit(self, app, client, admin_user, db_session):
        """POST /admin/seo/disconnect creates a gsc.disconnect AdminAuditLog entry."""
        before_count = db_session.query(AdminAuditLog).filter_by(
            action='gsc.disconnect'
        ).count()

        client.post('/admin/seo/disconnect', follow_redirects=False)

        after_count = db_session.query(AdminAuditLog).filter_by(
            action='gsc.disconnect'
        ).count()
        assert after_count > before_count

    def test_disconnect_requires_admin(self, client):
        """Anonymous POST /admin/seo/disconnect is rejected (not 200 success)."""
        resp = client.post('/admin/seo/disconnect', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)


class TestFetchGscDataExpiredToken:
    """fetch_gsc_data raises on expired token; SEO admin page handles it gracefully."""

    def test_fetch_gsc_data_raises_on_expired_token(self, app):
        """fetch_gsc_data propagates exception for expired/revoked refresh tokens."""
        from app.admin.services.gsc_service import fetch_gsc_data

        mock_service = MagicMock()
        mock_service.searchanalytics.return_value.query.return_value.execute.side_effect = (
            Exception('Token has been expired or revoked')
        )

        with app.app_context(), \
             patch('app.admin.services.gsc_service.build', return_value=mock_service):
            with pytest.raises(Exception, match='expired or revoked'):
                fetch_gsc_data(
                    refresh_token='expired-token',
                    site_url='https://example.com/',
                    client_id='cid',
                    client_secret='csecret',
                )

    @pytest.mark.smoke
    def test_seo_index_shows_error_message_not_500_on_expired_token(
        self, app, client, admin_user, db_session
    ):
        """When token is expired, SEO index returns 200 with an error message."""
        with app.app_context():
            encrypted = encrypt_secret('expired-token-abc')
        set_site_setting('gsc_refresh_token', encrypted, db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        mock_service = MagicMock()
        mock_service.searchanalytics.return_value.query.return_value.execute.side_effect = (
            Exception('Token has been expired or revoked')
        )
        mock_service.sites.return_value.list.return_value.execute.side_effect = (
            Exception('Token has been expired or revoked')
        )

        with patch('app.admin.services.gsc_service.build', return_value=mock_service), \
             patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_DUMMY_AUDIT):
            resp = client.get('/admin/seo', follow_redirects=True)

        assert resp.status_code == 200
        assert b'Internal Server Error' not in resp.data
        text = resp.data.decode()
        # Route sets gsc_error = 'Не удалось получить данные...'
        assert 'Не удалось' in text or 'переподключите' in text.lower()

    def test_fetch_gsc_data_empty_result_on_zero_rows(self, app):
        """fetch_gsc_data returns correct structure with empty rows."""
        from app.admin.services.gsc_service import fetch_gsc_data

        mock_service = MagicMock()
        mock_service.searchanalytics.return_value.query.return_value.execute.return_value = (
            {'rows': []}
        )

        with app.app_context(), \
             patch('app.admin.services.gsc_service.build', return_value=mock_service):
            result = fetch_gsc_data(
                refresh_token='valid-token',
                site_url='https://example.com/',
                client_id='cid',
                client_secret='csecret',
            )

        assert result['queries'] == []
        assert result['total_clicks'] == 0
        assert result['total_impressions'] == 0
        assert result['avg_ctr'] == 0.0
        assert result['avg_position'] == 0.0
        assert result['chart_dates'] == []
