"""Tests for Google Search Console service and admin routes (Task 4)."""
import pytest
from unittest.mock import MagicMock, patch

from app.admin.site_settings import set_site_setting


# ---------------------------------------------------------------------------
# gsc_service unit tests
# ---------------------------------------------------------------------------

class TestGSCService:
    """Unit tests for app.admin.services.gsc_service functions."""

    def test_fetch_gsc_data_returns_expected_shape(self, app):
        """fetch_gsc_data returns correct keys with mocked service."""
        mock_query_response = {
            'rows': [
                {
                    'keys': ['english grammar'],
                    'clicks': 100,
                    'impressions': 1000,
                    'ctr': 0.1,
                    'position': 3.5,
                },
                {
                    'keys': ['learn english'],
                    'clicks': 80,
                    'impressions': 900,
                    'ctr': 0.089,
                    'position': 4.2,
                },
            ]
        }
        mock_date_response = {
            'rows': [
                {'keys': ['2026-04-25'], 'clicks': 50, 'impressions': 500},
                {'keys': ['2026-04-26'], 'clicks': 60, 'impressions': 600},
            ]
        }

        with app.app_context():
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_creds_cls = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            # first call → query response, second call → date response
            mock_service.searchanalytics().query().execute.side_effect = [
                mock_query_response,
                mock_date_response,
            ]

            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', mock_creds_cls):
                result = gsc_module.fetch_gsc_data(
                    refresh_token='token',
                    site_url='https://example.com/',
                    client_id='client_id',
                    client_secret='client_secret',
                )

        assert 'queries' in result
        assert len(result['queries']) == 2
        assert result['queries'][0]['query'] == 'english grammar'
        assert result['queries'][0]['clicks'] == 100
        # Totals come from the per-date series (sums across ALL queries),
        # not from the top-10 query rows.
        assert result['total_clicks'] == 110
        assert result['total_impressions'] == 1100
        assert 'chart_dates' in result
        assert result['chart_dates'] == ['2026-04-25', '2026-04-26']
        assert result['chart_clicks'] == [50, 60]

    def test_fetch_gsc_data_empty_rows_no_error(self, app):
        """fetch_gsc_data handles empty rows without raising."""
        with app.app_context():
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.searchanalytics().query().execute.return_value = {'rows': []}

            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', MagicMock()):
                result = gsc_module.fetch_gsc_data(
                    refresh_token='token',
                    site_url='https://example.com/',
                    client_id='id',
                    client_secret='secret',
                )

        assert result['queries'] == []
        assert result['total_clicks'] == 0
        assert result['avg_ctr'] == 0.0
        assert result['avg_position'] == 0.0

    def test_get_verified_sites_returns_site_urls(self, app):
        """get_verified_sites extracts siteUrl values from API response."""
        with app.app_context():
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.sites().list().execute.return_value = {
                'siteEntry': [
                    {'siteUrl': 'https://example.com/', 'permissionLevel': 'siteOwner'},
                    {'siteUrl': 'https://m.example.com/', 'permissionLevel': 'siteFullUser'},
                ]
            }

            with patch.object(gsc_module, 'build', mock_build):
                result = gsc_module.get_verified_sites(MagicMock())

        assert result == ['https://example.com/', 'https://m.example.com/']

    def test_build_flow_calls_from_client_config(self, app):
        """build_flow delegates to Flow.from_client_config with correct redirect_uri."""
        with app.app_context():
            import app.admin.services.gsc_service as gsc_module
            mock_flow_cls = MagicMock()
            mock_flow = MagicMock()
            mock_flow_cls.from_client_config.return_value = mock_flow

            with patch.object(gsc_module, 'Flow', mock_flow_cls):
                result = gsc_module.build_flow(
                    redirect_uri='https://example.com/callback',
                    client_id='test_id',
                    client_secret='test_secret',
                )

            call_kwargs = mock_flow_cls.from_client_config.call_args
            client_config = call_kwargs[0][0]
            assert client_config['web']['client_id'] == 'test_id'
            assert client_config['web']['client_secret'] == 'test_secret'
            assert call_kwargs[1]['redirect_uri'] == 'https://example.com/callback'
        assert result is mock_flow


# ---------------------------------------------------------------------------
# GSC route tests
# ---------------------------------------------------------------------------

class TestGSCRoutes:
    """Tests for /admin/seo/connect, /seo/callback, and /seo/disconnect."""

    @pytest.mark.smoke
    def test_seo_index_returns_200(self, app, client, admin_user):
        """GET /admin/seo renders successfully."""
        response = client.get('/admin/seo')
        assert response.status_code == 200

    def test_seo_index_shows_gsc_section(self, app, client, admin_user):
        """GET /admin/seo always includes the GSC card."""
        response = client.get('/admin/seo')
        assert b'Google Search Console' in response.data

    def test_connect_without_google_config_flashes_danger(self, app, client, admin_user):
        """GET /admin/seo/connect without GOOGLE_CLIENT_ID flashes danger and redirects."""
        # Ensure config keys are absent
        app.config.pop('GOOGLE_CLIENT_ID', None)
        app.config.pop('GOOGLE_CLIENT_SECRET', None)

        response = client.get('/admin/seo/connect', follow_redirects=True)
        assert response.status_code == 200
        html = response.data.decode()
        # Either the flash message text or config key names appear
        assert 'GOOGLE_CLIENT_ID' in html or 'не настроен' in html.lower()

    def test_connect_with_google_config_redirects_to_google(self, app, client, admin_user):
        """GET /admin/seo/connect with config redirects to accounts.google.com."""
        app.config['GOOGLE_CLIENT_ID'] = 'test_client_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_client_secret'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/auth?state=xyz',
                'xyz',
            )
            with patch.object(gsc_module, 'Flow', MagicMock(from_client_config=MagicMock(return_value=mock_flow))):
                response = client.get('/admin/seo/connect')
            assert response.status_code == 302
            assert 'accounts.google.com' in response.headers['Location']
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_connect_uses_public_site_url_for_redirect_uri(self, app, client, admin_user):
        """OAuth redirect_uri uses SITE_URL instead of proxy-local request scheme."""
        app.config['GOOGLE_CLIENT_ID'] = 'test_client_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_client_secret'
        app.config['SITE_URL'] = 'https://llt-english.com'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                'https://accounts.google.com/auth?state=xyz',
                'xyz',
            )
            mock_flow_cls = MagicMock(
                from_client_config=MagicMock(return_value=mock_flow)
            )
            with patch.object(gsc_module, 'Flow', mock_flow_cls):
                response = client.get('/admin/seo/connect')

            assert response.status_code == 302
            assert (
                mock_flow_cls.from_client_config.call_args.kwargs['redirect_uri']
                == 'https://llt-english.com/admin/seo/callback'
            )
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)
            app.config['SITE_URL'] = ''

    def test_callback_with_error_param_flashes_danger(self, app, client, admin_user):
        """GET /admin/seo/callback?error=access_denied flashes danger message."""
        response = client.get('/admin/seo/callback?error=access_denied', follow_redirects=True)
        assert response.status_code == 200
        assert b'access_denied' in response.data

    def test_disconnect_clears_gsc_settings(self, app, client, admin_user, db_session):
        """POST /admin/seo/disconnect clears gsc_refresh_token and gsc_site_url."""
        set_site_setting('gsc_refresh_token', 'some_token', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        response = client.post('/admin/seo/disconnect', follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            from app.admin.site_settings import get_site_setting
            assert get_site_setting('gsc_refresh_token') == ''
            assert get_site_setting('gsc_site_url') == ''

    def test_seo_index_shows_gsc_error_when_fetch_fails(self, app, client, admin_user, db_session):
        """GET /admin/seo shows error banner when connected but fetch fails."""
        set_site_setting('gsc_refresh_token', 'bad_token', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_build.side_effect = Exception('API error')
            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', MagicMock()):
                response = client.get('/admin/seo')
            assert response.status_code == 200
            html = response.data.decode()
            assert 'Не удалось получить данные' in html
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_select_site_persists_choice_when_verified(self, app, client, admin_user, db_session):
        """POST /admin/seo/select-site updates gsc_site_url when target is verified."""
        set_site_setting('gsc_refresh_token', 'valid_token', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://first.example.com/', db_session=db_session)
        db_session.commit()

        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.sites().list().execute.return_value = {
                'siteEntry': [
                    {'siteUrl': 'https://first.example.com/'},
                    {'siteUrl': 'https://second.example.com/'},
                ]
            }
            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', MagicMock()):
                response = client.post(
                    '/admin/seo/select-site',
                    data={'site_url': 'https://second.example.com/'},
                    follow_redirects=False,
                )
            assert response.status_code == 302
            with app.app_context():
                from app.admin.site_settings import get_site_setting
                assert get_site_setting('gsc_site_url') == 'https://second.example.com/'
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_select_site_rejects_unverified_target(self, app, client, admin_user, db_session):
        """POST /admin/seo/select-site does NOT change gsc_site_url for unverified target."""
        set_site_setting('gsc_refresh_token', 'valid_token', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://first.example.com/', db_session=db_session)
        db_session.commit()

        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.sites().list().execute.return_value = {
                'siteEntry': [{'siteUrl': 'https://first.example.com/'}]
            }
            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', MagicMock()):
                client.post(
                    '/admin/seo/select-site',
                    data={'site_url': 'https://attacker.example.com/'},
                    follow_redirects=False,
                )
            with app.app_context():
                from app.admin.site_settings import get_site_setting
                assert get_site_setting('gsc_site_url') == 'https://first.example.com/'
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)

    def test_seo_index_shows_queries_table_when_connected(self, app, client, admin_user, db_session):
        """GET /admin/seo shows top-10 queries table when GSC data available."""
        set_site_setting('gsc_refresh_token', 'valid_token', db_session=db_session)
        set_site_setting('gsc_site_url', 'https://example.com/', db_session=db_session)
        db_session.commit()

        app.config['GOOGLE_CLIENT_ID'] = 'test_id'
        app.config['GOOGLE_CLIENT_SECRET'] = 'test_secret'
        try:
            import app.admin.services.gsc_service as gsc_module
            mock_build = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.searchanalytics().query().execute.side_effect = [
                {
                    'rows': [
                        {'keys': ['english verbs'], 'clicks': 42, 'impressions': 500,
                         'ctr': 0.084, 'position': 5.1},
                    ]
                },
                {'rows': []},
            ]
            with patch.object(gsc_module, 'build', mock_build), \
                 patch.object(gsc_module, 'Credentials', MagicMock()):
                response = client.get('/admin/seo')
            assert response.status_code == 200
            html = response.data.decode()
            assert 'english verbs' in html
            assert '42' in html
        finally:
            app.config.pop('GOOGLE_CLIENT_ID', None)
            app.config.pop('GOOGLE_CLIENT_SECRET', None)
