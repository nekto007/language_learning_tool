from flask import Response, current_app
from xml.etree.ElementTree import Element, SubElement, tostring
from . import seo_bp


def _site_urls() -> list[str]:
    configured = (current_app.config.get('SITE_URL') or '').rstrip('/')
    canonical = 'https://llt-english.com'
    urls: list[str] = []
    if configured:
        urls.append(configured)
    if canonical not in urls:
        urls.append(canonical)
    return urls


def _add(urlset: Element, loc: str, priority: str = '0.5', changefreq: str = 'weekly') -> None:
    url_el = SubElement(urlset, 'url')
    SubElement(url_el, 'loc').text = loc
    SubElement(url_el, 'priority').text = priority
    SubElement(url_el, 'changefreq').text = changefreq


@seo_bp.route('/sitemap.xml')
def sitemap() -> Response:
    """Generate sitemap.xml with all public pages."""
    from app.grammar_lab.models import GrammarTopic

    site_urls = _site_urls()
    site_url = site_urls[0]

    urlset = Element('urlset')
    urlset.set('xmlns', 'http://www.sitemaps.org/schemas/sitemap/0.9')

    # Static pages
    static_pages = [
        ('/', '1.0', 'weekly'),
        ('/register', '0.8', 'monthly'),
        ('/grammar-lab/topics', '0.9', 'weekly'),
        ('/privacy', '0.3', 'yearly'),
    ]
    for base_url in site_urls:
        for path, priority, changefreq in static_pages:
            url_el = SubElement(urlset, 'url')
            SubElement(url_el, 'loc').text = base_url + path
            SubElement(url_el, 'priority').text = priority
            SubElement(url_el, 'changefreq').text = changefreq

    # Course catalog
    from app.curriculum.models import CEFRLevel
    for base_url in site_urls:
        _add(urlset, base_url + '/courses', '0.8', 'weekly')
        for level in CEFRLevel.query.order_by(CEFRLevel.order).all():
            _add(urlset, f'{base_url}/courses/{level.code}', '0.7', 'weekly')

    # Grammar level listing pages
    from app.utils.db import db as _db
    grammar_levels = _db.session.query(GrammarTopic.level).distinct().all()
    for base_url in site_urls:
        for (lvl,) in grammar_levels:
            _add(urlset, f'{base_url}/grammar-lab/topics/{lvl.lower()}', '0.7', 'weekly')

    # Grammar topics
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()
    for base_url in site_urls:
        for topic in topics:
            url_el = SubElement(urlset, 'url')
            SubElement(url_el, 'loc').text = f'{base_url}/grammar-lab/topic/{topic.id}'
            SubElement(url_el, 'priority').text = '0.7'
            SubElement(url_el, 'changefreq').text = 'monthly'
            if topic.updated_at:
                SubElement(url_el, 'lastmod').text = topic.updated_at.strftime('%Y-%m-%d')

    # Dictionary pages (top 500 words)
    from app.words.models import CollectionWords
    top_words = (
        CollectionWords.query
        .filter(CollectionWords.item_type == 'word')
        .order_by(
            CollectionWords.frequency_rank.asc().nullslast(),
            CollectionWords.id.asc(),
        )
        .limit(500)
        .all()
    )
    for base_url in site_urls:
        for word in top_words:
            slug = word.english_word.lower().replace(' ', '-')
            _add(urlset, f'{base_url}/dictionary/{slug}', '0.6', 'monthly')

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding='unicode').encode('utf-8')
    return Response(xml_bytes, mimetype='application/xml')


@seo_bp.route('/robots.txt')
def robots() -> Response:
    """Serve robots.txt."""
    site_urls = _site_urls()
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /admin/\n'
    )
    content += ''.join(f'\nSitemap: {site_url}/sitemap.xml' for site_url in site_urls) + '\n'
    return Response(content, mimetype='text/plain')
