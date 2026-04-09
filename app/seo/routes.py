from flask import Response, current_app
from xml.etree.ElementTree import Element, SubElement, tostring

from . import seo_bp


@seo_bp.route('/sitemap.xml')
def sitemap() -> Response:
    """Generate sitemap.xml with all public pages."""
    from app.grammar_lab.models import GrammarTopic

    site_url = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')

    urlset = Element('urlset')
    urlset.set('xmlns', 'http://www.sitemaps.org/schemas/sitemap/0.9')

    # Static pages
    static_pages = [
        ('/', '1.0', 'weekly'),
        ('/register', '0.8', 'monthly'),
        ('/grammar-lab/topics', '0.9', 'weekly'),
        ('/privacy', '0.3', 'yearly'),
    ]
    for path, priority, changefreq in static_pages:
        url_el = SubElement(urlset, 'url')
        SubElement(url_el, 'loc').text = site_url + path
        SubElement(url_el, 'priority').text = priority
        SubElement(url_el, 'changefreq').text = changefreq

    # Grammar topics
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()
    for topic in topics:
        url_el = SubElement(urlset, 'url')
        SubElement(url_el, 'loc').text = f'{site_url}/grammar-lab/topic/{topic.id}'
        SubElement(url_el, 'priority').text = '0.7'
        SubElement(url_el, 'changefreq').text = 'monthly'
        if topic.updated_at:
            SubElement(url_el, 'lastmod').text = topic.updated_at.strftime('%Y-%m-%d')

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding='unicode').encode('utf-8')
    return Response(xml_bytes, mimetype='application/xml')


@seo_bp.route('/robots.txt')
def robots() -> Response:
    """Serve robots.txt."""
    site_url = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /admin/\n'
        f'\nSitemap: {site_url}/sitemap.xml\n'
    )
    return Response(content, mimetype='text/plain')
