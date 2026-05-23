"""
Tests for admin SEO analytics — seo_audit_service and seo_routes.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.admin.utils.cache import clear_admin_cache


# ---------------------------------------------------------------------------
# seo_audit_service unit tests (no DB required)
# ---------------------------------------------------------------------------

class TestExtractHelpers:
    """Unit tests for HTML extraction helpers."""

    def test_extract_title(self):
        from app.admin.services.seo_audit_service import _extract_title
        html = '<html><head><title>Hello World Page</title></head></html>'
        assert _extract_title(html) == 'Hello World Page'

    def test_extract_title_missing(self):
        from app.admin.services.seo_audit_service import _extract_title
        assert _extract_title('<html></html>') is None

    def test_extract_meta_name_description(self):
        from app.admin.services.seo_audit_service import _extract_meta_name
        html = '<meta name="description" content="A great site">'
        assert _extract_meta_name(html, 'description') == 'A great site'

    def test_extract_meta_name_reversed_attrs(self):
        from app.admin.services.seo_audit_service import _extract_meta_name
        html = '<meta content="A great site" name="description">'
        assert _extract_meta_name(html, 'description') == 'A great site'

    def test_extract_meta_name_missing(self):
        from app.admin.services.seo_audit_service import _extract_meta_name
        assert _extract_meta_name('<html></html>', 'description') is None

    def test_extract_meta_property_og_title(self):
        from app.admin.services.seo_audit_service import _extract_meta_property
        html = '<meta property="og:title" content="My OG Title">'
        assert _extract_meta_property(html, 'og:title') == 'My OG Title'

    def test_extract_meta_property_reversed(self):
        from app.admin.services.seo_audit_service import _extract_meta_property
        html = '<meta content="My OG Title" property="og:title">'
        assert _extract_meta_property(html, 'og:title') == 'My OG Title'

    def test_extract_canonical(self):
        from app.admin.services.seo_audit_service import _extract_canonical
        html = '<link rel="canonical" href="https://example.com/page">'
        assert _extract_canonical(html) == 'https://example.com/page'

    def test_extract_canonical_reversed(self):
        from app.admin.services.seo_audit_service import _extract_canonical
        html = '<link href="https://example.com/page" rel="canonical">'
        assert _extract_canonical(html) == 'https://example.com/page'

    def test_extract_canonical_missing(self):
        from app.admin.services.seo_audit_service import _extract_canonical
        assert _extract_canonical('<html></html>') is None


class TestAuditPage:
    """Unit tests for _audit_page with mocked client."""

    def _make_response(self, status_code=200, data=b'', content_type='text/html; charset=utf-8'):
        resp = MagicMock()
        resp.status_code = status_code
        resp.data = data
        resp.content_type = content_type
        return resp

    def test_audit_page_200_fully_covered(self):
        from app.admin.services.seo_audit_service import _audit_page
        html = (
            '<html><head>'
            '<title>A Very Descriptive Page Title Here</title>'
            '<meta name="description" content="This is a long enough description for SEO purposes.">'
            '<meta property="og:title" content="OG Title">'
            '<meta property="og:description" content="OG description here">'
            '<meta property="og:image" content="https://example.com/image.jpg">'
            '<link rel="canonical" href="https://example.com/page">'
            '</head><body></body></html>'
        )
        client = MagicMock()
        client.get.return_value = self._make_response(data=html.encode())

        result = _audit_page(client, '/')

        assert result['status_code'] == 200
        assert result['title_ok'] is True
        assert result['description_ok'] is True
        assert result['og_ok'] is True
        assert result['canonical_ok'] is True
        assert result['issues'] == []
        assert result['error'] is None

    def test_audit_page_404(self):
        from app.admin.services.seo_audit_service import _audit_page
        client = MagicMock()
        client.get.return_value = self._make_response(status_code=404, data=b'Not found')

        result = _audit_page(client, '/nonexistent')

        assert result['status_code'] == 404
        assert result['title_ok'] is False
        assert result['error'] == 'HTTP 404'

    def test_audit_page_missing_title(self):
        from app.admin.services.seo_audit_service import _audit_page
        html = (
            '<html><head>'
            '<meta name="description" content="Good description here.">'
            '</head><body></body></html>'
        )
        client = MagicMock()
        client.get.return_value = self._make_response(data=html.encode())

        result = _audit_page(client, '/')
        assert result['title_ok'] is False
        assert 'Нет или короткий <title>' in result['issues']

    def test_audit_page_missing_og(self):
        from app.admin.services.seo_audit_service import _audit_page
        html = (
            '<html><head>'
            '<title>A Very Descriptive Page Title Here</title>'
            '<meta name="description" content="This is a long enough description.">'
            '<link rel="canonical" href="https://example.com/page">'
            '</head><body></body></html>'
        )
        client = MagicMock()
        client.get.return_value = self._make_response(data=html.encode())

        result = _audit_page(client, '/')
        assert result['og_ok'] is False
        assert 'Нет og:title' in result['issues']

    def test_audit_page_exception(self):
        from app.admin.services.seo_audit_service import _audit_page
        client = MagicMock()
        client.get.side_effect = RuntimeError('Connection refused')

        result = _audit_page(client, '/')
        assert result['status_code'] == 0
        assert result['error'] is not None
        assert len(result['issues']) > 0


class TestFetchSitemapStats:
    """Unit tests for _fetch_sitemap_stats."""

    def test_parses_valid_sitemap(self):
        from app.admin.services.seo_audit_service import _fetch_sitemap_stats
        sitemap_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b'<url><loc>https://example.com/</loc><lastmod>2026-05-01</lastmod></url>'
            b'<url><loc>https://example.com/about</loc><lastmod>2026-04-15</lastmod></url>'
            b'</urlset>'
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.data = sitemap_xml
        client = MagicMock()
        client.get.return_value = resp

        stats = _fetch_sitemap_stats(client)

        assert stats['url_count'] == 2
        assert stats['newest_lastmod'] == '2026-05-01'
        assert stats['error'] is None

    def test_handles_sitemap_404(self):
        from app.admin.services.seo_audit_service import _fetch_sitemap_stats
        resp = MagicMock()
        resp.status_code = 404
        client = MagicMock()
        client.get.return_value = resp

        stats = _fetch_sitemap_stats(client)
        assert stats['error'] == 'HTTP 404'
        assert stats['url_count'] == 0

    def test_sitemap_no_lastmod(self):
        from app.admin.services.seo_audit_service import _fetch_sitemap_stats
        sitemap_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b'<url><loc>https://example.com/</loc></url>'
            b'</urlset>'
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.data = sitemap_xml
        client = MagicMock()
        client.get.return_value = resp

        stats = _fetch_sitemap_stats(client)
        assert stats['url_count'] == 1
        assert stats['newest_lastmod'] is None


class TestRunSeoAudit:
    """Unit tests for run_seo_audit with caching."""

    def setup_method(self):
        clear_admin_cache()

    def teardown_method(self):
        clear_admin_cache()

    def _make_html_response(self, path):
        html = (
            f'<html><head>'
            f'<title>Page {path} Title Long Enough</title>'
            f'<meta name="description" content="Description for {path} which is long enough to pass.">'
            f'<meta property="og:title" content="OG {path}">'
            f'<meta property="og:description" content="OG description for {path} page here.">'
            f'<meta property="og:image" content="https://example.com/img.jpg">'
            f'<link rel="canonical" href="https://example.com{path}">'
            f'</head><body></body></html>'
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.data = html.encode()
        resp.content_type = 'text/html; charset=utf-8'
        return resp

    def _make_sitemap_response(self):
        sitemap_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b'<url><loc>https://example.com/</loc><lastmod>2026-05-01</lastmod></url>'
            b'</urlset>'
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.data = sitemap_xml
        resp.content_type = 'application/xml'
        return resp

    def test_run_seo_audit_returns_report_shape(self):
        from app.admin.services.seo_audit_service import run_seo_audit, PUBLIC_URLS

        def fake_get(path, **kwargs):
            if path == '/sitemap.xml':
                return self._make_sitemap_response()
            return self._make_html_response(path)

        mock_client = MagicMock()
        mock_client.get.side_effect = fake_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_client)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        mock_app = MagicMock()
        mock_app.test_client.return_value = mock_ctx

        report = run_seo_audit(mock_app)

        assert 'pages' in report
        assert 'sitemap' in report
        assert 'fully_covered_count' in report
        assert 'total_pages' in report
        assert report['total_pages'] == len(PUBLIC_URLS)

    def test_run_seo_audit_caches_result(self):
        from app.admin.services.seo_audit_service import run_seo_audit

        def fake_get(path, **kwargs):
            if path == '/sitemap.xml':
                return self._make_sitemap_response()
            return self._make_html_response(path)

        mock_client = MagicMock()
        mock_client.get.side_effect = fake_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_client)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_app = MagicMock()
        mock_app.test_client.return_value = mock_ctx

        report1 = run_seo_audit(mock_app)
        # Second call should hit cache — test_client not called again
        call_count_after_first = mock_app.test_client.call_count
        report2 = run_seo_audit(mock_app)

        assert mock_app.test_client.call_count == call_count_after_first
        assert report1 == report2


# ---------------------------------------------------------------------------
# seo_routes integration tests (require app + mock_admin_user)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_admin_user():
    """Patch current_user in Flask-Login and the admin decorator to bypass auth entirely."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.id = 999
    mock_user.username = 'mock_admin'
    with patch('app.admin.utils.decorators.current_user', mock_user), \
         patch('flask_login.utils.current_user', mock_user):
        yield mock_user


_FAKE_REPORT = {
    'pages': [
        {
            'url': '/',
            'status_code': 200,
            'title': 'Home Page Title',
            'description': 'A long enough description',
            'og_title': 'OG Title',
            'og_description': 'OG Desc',
            'og_image': None,
            'canonical': 'https://example.com/',
            'title_ok': True,
            'description_ok': True,
            'og_ok': True,
            'canonical_ok': True,
            'issues': [],
            'error': None,
        }
    ],
    'sitemap': {'url_count': 10, 'newest_lastmod': '2026-05-01', 'error': None},
    'fully_covered_count': 1,
    'reachable_count': 1,
    'total_pages': 1,
}


class TestSeoRoutes:
    """Integration tests for /admin/seo routes."""

    def setup_method(self):
        clear_admin_cache()

    def teardown_method(self):
        clear_admin_cache()

    def test_seo_index_requires_admin(self, client):
        response = client.get('/admin/seo', follow_redirects=False)
        assert response.status_code in (302, 401)

    def test_seo_index_renders_for_admin(self, client, mock_admin_user):
        """GET /admin/seo returns 200 with audit table."""
        with patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_FAKE_REPORT):
            response = client.get('/admin/seo')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'SEO' in body
        assert 'Sitemap' in body or 'sitemap' in body.lower()

    def test_seo_index_shows_page_count(self, client, mock_admin_user):
        """Stat card shows total pages count."""
        with patch('app.admin.routes.seo_routes.run_seo_audit', return_value=_FAKE_REPORT):
            response = client.get('/admin/seo')

        assert response.status_code == 200
        body = response.data.decode()
        assert '1' in body  # total_pages == 1

    def test_seo_refresh_clears_cache_and_redirects(self, client, mock_admin_user):
        """POST /admin/seo/refresh clears cache and redirects."""
        response = client.post(
            '/admin/seo/refresh',
            data={'csrf_token': 'dummy'},
            follow_redirects=False,
        )
        assert response.status_code == 302
