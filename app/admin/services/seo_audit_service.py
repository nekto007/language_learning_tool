# app/admin/services/seo_audit_service.py

"""SEO audit service — crawls key public pages and reports meta-tag coverage."""

import logging
import re
from typing import Optional
from xml.etree import ElementTree

from app.admin.utils.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

SEO_AUDIT_CACHE_KEY = 'seo_audit_results'
SEO_AUDIT_CACHE_TIMEOUT = 3600  # 1 hour

# Key public URLs to audit — static HTML paths only.  Sitemap is audited
# separately via `_fetch_sitemap_stats` so meta-tag coverage stays consistent.
PUBLIC_URLS = [
    '/',
    '/register',
    '/login',
    '/grammar-lab/topics',
    '/grammar-lab/',
    '/courses',
    '/privacy',
    '/grammar-lab/topics/a1',
    '/grammar-lab/topics/a2',
    '/grammar-lab/topics/b1',
    '/grammar-lab/topics/b2',
    '/grammar-lab/topics/c1',
    '/onboarding',
    '/reset_password',
]


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
        response = client.get(path, follow_redirects=True)
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
    stats: dict = {'url_count': 0, 'newest_lastmod': None, 'error': None}
    try:
        response = client.get('/sitemap.xml')
        if response.status_code != 200:
            stats['error'] = f'HTTP {response.status_code}'
            return stats

        root = ElementTree.fromstring(response.data)
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = root.findall('sm:url', ns)
        stats['url_count'] = len(urls)

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


def run_seo_audit(app) -> dict:
    """Run SEO audit on key public pages. Result is cached for 1 hour."""
    cached = get_cache(SEO_AUDIT_CACHE_KEY, timeout=SEO_AUDIT_CACHE_TIMEOUT)
    if cached is not None:
        return cached

    with app.test_client() as client:
        pages = [_audit_page(client, path) for path in PUBLIC_URLS]
        sitemap_stats = _fetch_sitemap_stats(client)

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
    }

    set_cache(SEO_AUDIT_CACHE_KEY, report)
    return report
