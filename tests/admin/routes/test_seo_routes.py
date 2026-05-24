"""Task 15: SEO + GSC admin OAuth, cache invalidation, and disconnect cleanup."""
from unittest.mock import MagicMock, patch

import pytest

from app.admin.services.seo_audit_service import (
    SEO_AUDIT_CACHE_KEY,
    SEO_AUDIT_CACHE_VERSION_KEY,
    bump_seo_audit_cache_version,
    get_seo_audit_cache_key,
)
from app.admin.site_settings import get_site_setting, set_site_setting
from app.admin.utils.cache import clear_admin_cache, get_cache, set_cache


class TestSeoAuditCacheVersioning:
    """Cache invalidation must work across gunicorn workers via SiteSettings."""

    def setup_method(self):
        clear_admin_cache()

    def teardown_method(self):
        clear_admin_cache()

    @pytest.mark.smoke
    def test_cache_key_is_versioned(self, app, db_session):
        set_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, '7', db_session=db_session)
        db_session.commit()
        with app.app_context():
            assert get_seo_audit_cache_key() == f'{SEO_AUDIT_CACHE_KEY}:v7'

    def test_cache_key_falls_back_when_site_settings_unreachable(self):
        # Defensive fallback: any failure (no app context, DB down) → base key.
        with patch(
            'app.admin.site_settings.get_site_setting',
            side_effect=RuntimeError('no app context'),
        ):
            assert get_seo_audit_cache_key() == SEO_AUDIT_CACHE_KEY

    def test_bump_version_increments(self, app, db_session):
        set_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, '3', db_session=db_session)
        db_session.commit()
        with app.app_context():
            new_value = bump_seo_audit_cache_version()
            assert new_value == '4'
            assert (
                get_site_setting(SEO_AUDIT_CACHE_VERSION_KEY) == '4'
            )

    def test_bump_version_handles_nonnumeric(self, app, db_session):
        set_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, 'corrupt', db_session=db_session)
        db_session.commit()
        with app.app_context():
            assert bump_seo_audit_cache_version() == '1'

    def test_refresh_route_bumps_version_and_clears_local_cache(
        self, app, admin_client, db_session
    ):
        set_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, '5', db_session=db_session)
        db_session.commit()
        with app.app_context():
            current_key = get_seo_audit_cache_key()
        # Seed worker-local cache so we can assert it was cleared.
        set_cache(current_key, {'placeholder': True})
        assert get_cache(current_key) is not None

        response = admin_client.post('/admin/seo/refresh', follow_redirects=False)
        assert response.status_code == 302

        # Local cache entry (under old key) is purged.
        assert get_cache(current_key) is None
        # Version is bumped → new requests on any worker form a new key.
        with app.app_context():
            assert get_site_setting(SEO_AUDIT_CACHE_VERSION_KEY) == '6'


class TestGSCOAuthHardening:
    """OAuth state validation and disconnect cleanup."""

    def test_callback_rejects_missing_state(self, app, admin_client, caplog):
        """No session state and no query state → flash danger, no token exchange."""
        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            with caplog.at_level('WARNING', logger='app.admin.routes.seo_routes'):
                response = admin_client.get(
                    '/admin/seo/callback?code=abc',
                    follow_redirects=False,
                )
            assert response.status_code == 302
            assert any(
                'state mismatch' in record.getMessage().lower()
                for record in caplog.records
            )
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_callback_rejects_mismatched_state(self, app, admin_client, caplog):
        """Session state present, query state different → reject."""
        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            with admin_client.session_transaction() as sess:
                sess['gsc_oauth_state'] = 'expected'

            import app.admin.services.gsc_service as gsc_module

            mock_flow = MagicMock()
            mock_flow_cls = MagicMock(
                from_client_config=MagicMock(return_value=mock_flow)
            )
            with patch.object(gsc_module, 'Flow', mock_flow_cls), \
                 caplog.at_level('WARNING', logger='app.admin.routes.seo_routes'):
                response = admin_client.get(
                    '/admin/seo/callback?code=abc&state=tampered',
                    follow_redirects=False,
                )
            assert response.status_code == 302
            # fetch_token must NOT be called for a mismatched state.
            mock_flow.fetch_token.assert_not_called()
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_disconnect_clears_pending_oauth_state_in_session(
        self, app, admin_client, db_session
    ):
        """POST /admin/seo/disconnect drops any leftover session OAuth state."""
        set_site_setting('gsc_refresh_token', 'stored', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        with admin_client.session_transaction() as sess:
            sess['gsc_oauth_state'] = 'pending-handshake'

        response = admin_client.post('/admin/seo/disconnect', follow_redirects=False)
        assert response.status_code == 302

        with admin_client.session_transaction() as sess:
            assert 'gsc_oauth_state' not in sess

    def test_disconnect_writes_audit_log(self, app, admin_client, db_session):
        """Disconnect must record an audit log entry."""
        from app.admin.audit import AdminAuditLog

        set_site_setting('gsc_refresh_token', 'stored', db_session=db_session)
        db_session.commit()

        response = admin_client.post('/admin/seo/disconnect', follow_redirects=False)
        assert response.status_code == 302

        audit_entry = (
            db_session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == 'gsc.disconnect')
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert audit_entry is not None
        assert audit_entry.target_type == 'site_settings'

    def test_connect_stores_state_in_session(self, app, admin_client):
        """/admin/seo/connect must persist OAuth state in the user session."""
        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module

            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/auth?state=fresh-state',
                'fresh-state',
            )
            with patch.object(
                gsc_module,
                'Flow',
                MagicMock(from_client_config=MagicMock(return_value=mock_flow)),
            ):
                response = admin_client.get('/admin/seo/connect')

            assert response.status_code == 302
            with admin_client.session_transaction() as sess:
                assert sess.get('gsc_oauth_state') == 'fresh-state'
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)


class TestRefreshTokenEncryption:
    """Stored GSC refresh tokens must be encrypted at rest in SiteSettings."""

    def test_connect_callback_writes_encrypted_refresh_token(
        self, app, admin_client, db_session
    ):
        from app.admin.secret_store import decrypt_secret

        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module

            mock_flow = MagicMock()
            mock_flow.credentials.refresh_token = 'super-secret-refresh-token'
            mock_flow_cls = MagicMock(
                from_client_config=MagicMock(return_value=mock_flow)
            )
            with admin_client.session_transaction() as sess:
                sess['gsc_oauth_state'] = 'state-xyz'

            with patch.object(gsc_module, 'Flow', mock_flow_cls), \
                 patch.object(
                     gsc_module,
                     'get_verified_sites',
                     return_value=['https://example.com/'],
                 ):
                response = admin_client.get(
                    '/admin/seo/callback?code=abc&state=state-xyz',
                    follow_redirects=False,
                )
            assert response.status_code == 302

            stored = get_site_setting('gsc_refresh_token', db_session=db_session)
            assert stored
            # Must not be plaintext; must round-trip through decrypt.
            assert stored != 'super-secret-refresh-token'
            assert stored.startswith('enc:v1:')
            assert decrypt_secret(stored) == 'super-secret-refresh-token'
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)
