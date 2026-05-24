# app/admin/services/seo_audit_service.py

"""SEO audit service — crawls key public pages and reports meta-tag coverage."""

import logging
import re
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

from app.admin.utils.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

SEO_AUDIT_CACHE_KEY = 'seo_audit_results'
SEO_AUDIT_CACHE_TIMEOUT = 3600  # 1 hour
SITEMAP_AUDIT_SAMPLE_LIMIT = 50

# Cache strategy: in-memory per gunicorn worker (see app/admin/utils/cache.py).
# Cross-worker invalidation: the `seo_audit_cache_version` SiteSettings row is
# bumped by `seo_refresh` and read on every audit call; every worker forms a
# versioned cache key, so a refresh forces all workers to recompute once.
SEO_AUDIT_CACHE_VERSION_KEY = 'seo_audit_cache_version'


def get_seo_audit_cache_key(db_session=None) -> str:
    """Return the versioned cache key, honouring cross-worker invalidation.

    Falls back to the unversioned base key when SiteSettings is unreachable
    (e.g. unit tests without an app context); the audit still works, only the
    cross-worker invalidation degrades to per-worker timeout behaviour.
    """
    try:
        from app.admin.site_settings import get_site_setting

        version = (
            get_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, '1', db_session=db_session)
            or '1'
        )
    except Exception:
        return SEO_AUDIT_CACHE_KEY
    return f'{SEO_AUDIT_CACHE_KEY}:v{version}'


def bump_seo_audit_cache_version(db_session=None) -> str:
    """Increment the SiteSettings-backed cache version (caller commits)."""
    from app.admin.site_settings import get_site_setting, set_site_setting

    current = get_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, '1', db_session=db_session) or '1'
    try:
        new_version = str(int(current) + 1)
    except (TypeError, ValueError):
        new_version = '1'
    set_site_setting(SEO_AUDIT_CACHE_VERSION_KEY, new_version, db_session=db_session)
    return new_version

# Key public URLs to audit — static HTML paths only.  Sitemap is audited
# separately via `_fetch_sitemap_stats` so meta-tag coverage stays consistent.
# Auth-gated pages (e.g. /onboarding) are excluded since the test client would
# follow a redirect to /login and report meta-tags from the wrong page.
PUBLIC_URLS = [
    '/',
    '/register',
    '/login',
    '/grammar-lab/topics',
    '/grammar-lab/',
    '/dictionary',
    '/courses/',
    '/courses/A1',
    '/courses/A2',
    '/courses/B1',
    '/courses/B2',
    '/courses/C1',
    '/privacy',
    '/grammar-lab/topics/a1',
    '/grammar-lab/topics/a2',
    '/grammar-lab/topics/b1',
    '/grammar-lab/topics/b2',
    '/grammar-lab/topics/c1',
    # POSTing /reset_password is rate-limited to 3/hour; the audit only
    # issues GET requests, which always render the form.
    '/reset_password',
]


def _cached_urls_match_current(report: dict) -> bool:
    """Return true only when cached report was built for the current URL list."""
    if not isinstance(report, dict):
        return False
    return (
        report.get('public_urls') == PUBLIC_URLS
        and report.get('sitemap_audit_limit') == SITEMAP_AUDIT_SAMPLE_LIMIT
    )


def _path_from_sitemap_loc(loc: str) -> str:
    parsed = urlparse(loc)
    path = parsed.path or '/'
    if parsed.query:
        return f'{path}?{parsed.query}'
    return path


def _extract_title(html: str) -> Optional[str]:
    m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_meta_name(html: str, name: str) -> Optional[str]:
    escaped = re.escape(name)
    m = re.search(
        rf'<meta\s+name=["\']({escaped})["\'][^>]*content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(
            rf'<meta\s+content=["\'](.*?)["\'][^>]*name=["\']({escaped})["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else None
    return m.group(2).strip()


def _extract_meta_property(html: str, prop: str) -> Optional[str]:
    escaped = re.escape(prop)
    m = re.search(
        rf'<meta\s+property=["\']({escaped})["\'][^>]*content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(
            rf'<meta\s+content=["\'](.*?)["\'][^>]*property=["\']({escaped})["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else None
    return m.group(2).strip()


def _extract_canonical(html: str) -> Optional[str]:
    m = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(
            r'<link[^>]+href=["\'](.*?)["\'][^>]+rel=["\']canonical["\']',
            html, re.IGNORECASE | re.DOTALL,
        )
    return m.group(1).strip() if m else None


def _audit_page(client, path: str) -> dict:
    result: dict = {
        'url': path,
        'status_code': 0,
        'title': None,
        'description': None,
        'og_title': None,
        'og_description': None,
        'og_image': None,
        'canonical': None,
        'title_ok': False,
        'description_ok': False,
        'og_ok': False,
        'canonical_ok': False,
        'issues': [],
        'error': None,
    }

    try:
        response = client.get(path, follow_redirects=False)
        result['status_code'] = response.status_code

        if response.status_code != 200:
            result['error'] = f'HTTP {response.status_code}'
            result['issues'].append(f'Страница вернула {response.status_code}')
            return result

        content_type = response.content_type or ''
        if 'html' not in content_type:
            result['error'] = f'Non-HTML response: {content_type}'
            return result

        html = response.data.decode('utf-8', errors='replace')

        result['title'] = _extract_title(html)
        result['description'] = _extract_meta_name(html, 'description')
        result['og_title'] = _extract_meta_property(html, 'og:title')
        result['og_description'] = _extract_meta_property(html, 'og:description')
        result['og_image'] = _extract_meta_property(html, 'og:image')
        result['canonical'] = _extract_canonical(html)

        result['title_ok'] = bool(result['title'] and len(result['title']) >= 10)
        result['description_ok'] = bool(
            result['description'] and len(result['description']) >= 30
        )
        result['og_ok'] = bool(result['og_title'] and result['og_description'])
        result['canonical_ok'] = bool(result['canonical'])

        if not result['title_ok']:
            result['issues'].append('Нет или короткий <title>')
        if not result['description_ok']:
            result['issues'].append('Нет meta description')
        if not result['og_title']:
            result['issues'].append('Нет og:title')
        if not result['og_description']:
            result['issues'].append('Нет og:description')
        if not result['og_image']:
            result['issues'].append('Нет og:image')
        if not result['canonical_ok']:
            result['issues'].append('Нет canonical link')

    except Exception as exc:
        result['error'] = str(exc)
        result['issues'].append(f'Ошибка запроса: {exc}')
        logger.exception('SEO audit failed for %s', path)

    return result


def _fetch_sitemap_stats(client) -> dict:
    stats: dict = {'url_count': 0, 'newest_lastmod': None, 'error': None, 'paths': []}
    try:
        response = client.get('/sitemap.xml')
        if response.status_code != 200:
            stats['error'] = f'HTTP {response.status_code}'
            return stats

        root = ElementTree.fromstring(response.data)
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = root.findall('sm:url', ns)
        stats['url_count'] = len(urls)
        locs = [
            url_el.findtext('sm:loc', namespaces=ns)
            for url_el in urls
        ]
        seen_paths = set()
        for loc in locs:
            if not loc:
                continue
            path = _path_from_sitemap_loc(loc.strip())
            if path in seen_paths:
                continue
            seen_paths.add(path)
            stats['paths'].append(path)

        lastmods = [
            url_el.findtext('sm:lastmod', namespaces=ns)
            for url_el in urls
        ]
        lastmods = [d.strip() for d in lastmods if d]
        if lastmods:
            stats['newest_lastmod'] = max(lastmods)
    except Exception as exc:
        stats['error'] = str(exc)
        logger.exception('Error fetching sitemap stats')
    return stats


def _build_audit_paths(sitemap_stats: dict) -> list[str]:
    """Audit curated public pages plus a bounded sample from sitemap.xml."""
    audit_paths = list(PUBLIC_URLS)
    seen = set(audit_paths)
    sitemap_added = 0
    for path in sitemap_stats.get('paths') or []:
        if path in seen:
            continue
        audit_paths.append(path)
        seen.add(path)
        sitemap_added += 1
        if sitemap_added >= SITEMAP_AUDIT_SAMPLE_LIMIT:
            break
    return audit_paths


def run_seo_audit(app) -> dict:
    """Run SEO audit on key public pages. Result is cached for 1 hour."""
    cache_key = get_seo_audit_cache_key()
    cached = get_cache(cache_key, timeout=SEO_AUDIT_CACHE_TIMEOUT)
    if cached is not None and _cached_urls_match_current(cached):
        return cached

    # Push an isolated app context so nested test_client requests don't share
    # `flask.g` with the outer request. Without this, the nested requests'
    # `csrf_token()` calls populate `g.csrf_token` for the outer request,
    # causing the outer template to emit a token bound to the nested session
    # — and subsequent POSTs from /admin/seo fail with "CSRF session token is
    # missing" because the outer session never received the matching value.
    with app.app_context():
        with app.test_client() as client:
            sitemap_stats = _fetch_sitemap_stats(client)
            audit_paths = _build_audit_paths(sitemap_stats)
            pages = [_audit_page(client, path) for path in audit_paths]

    fully_covered = sum(
        1 for p in pages
        if p['status_code'] == 200
        and p['title_ok']
        and p['description_ok']
        and p['og_ok']
        and p['canonical_ok']
    )
    reachable = [p for p in pages if p['status_code'] == 200]

    report = {
        'pages': pages,
        'sitemap': sitemap_stats,
        'fully_covered_count': fully_covered,
        'reachable_count': len(reachable),
        'total_pages': len(pages),
        'public_urls': PUBLIC_URLS,
        'sitemap_audited_count': max(0, len(pages) - len(PUBLIC_URLS)),
        'sitemap_audit_limit': SITEMAP_AUDIT_SAMPLE_LIMIT,
    }

    set_cache(cache_key, report)
    return report
