from flask import Response, url_for
from xml.etree.ElementTree import Element, SubElement, tostring

from app.seo import seo_bp
from app.utils.db import db
from app.words.models import CollectionWords

SITE_URL = 'https://llt-english.com'


def _add_url(urlset: Element, loc: str, changefreq: str = 'weekly',
             priority: str = '0.5', lastmod: str | None = None) -> None:
    """Add a <url> entry to the sitemap."""
    url_el = SubElement(urlset, 'url')
    SubElement(url_el, 'loc').text = loc
    if lastmod:
        SubElement(url_el, 'lastmod').text = lastmod
    SubElement(url_el, 'changefreq').text = changefreq
    SubElement(url_el, 'priority').text = priority


@seo_bp.route('/sitemap.xml')
def sitemap() -> Response:
    """Generate XML sitemap with all public pages."""
    urlset = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')

    # Static pages
    _add_url(urlset, SITE_URL + '/', changefreq='daily', priority='1.0')

    # Grammar Lab level listing pages
    from app.grammar_lab.models import GrammarTopic
    _add_url(urlset, SITE_URL + '/grammar-lab/', changefreq='weekly', priority='0.8')
    grammar_levels = db.session.query(GrammarTopic.level).distinct().all()
    for (lvl,) in grammar_levels:
        _add_url(
            urlset,
            SITE_URL + f'/grammar-lab/topics/{lvl.lower()}',
            changefreq='weekly',
            priority='0.7',
        )

    # Grammar Lab topic pages
    for topic in GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all():
        lm = topic.updated_at.strftime('%Y-%m-%d') if getattr(topic, 'updated_at', None) else None
        _add_url(
            urlset,
            SITE_URL + f'/grammar-lab/topic/{topic.id}',
            changefreq='monthly',
            priority='0.7',
            lastmod=lm,
        )

    # Course catalog
    _add_url(urlset, SITE_URL + '/courses', changefreq='weekly', priority='0.8')

    from app.curriculum.models import CEFRLevel
    for level in CEFRLevel.query.order_by(CEFRLevel.order).all():
        _add_url(
            urlset,
            SITE_URL + f'/courses/{level.code}',
            changefreq='weekly',
            priority='0.7',
        )

    # Dictionary pages (top 500 by frequency_rank)
    top_words = (
        CollectionWords.query
        .filter(CollectionWords.frequency_rank > 0)
        .order_by(CollectionWords.frequency_rank.asc())
        .limit(500)
        .all()
    )
    for word in top_words:
        slug = word.english_word.lower().replace(' ', '-')
        _add_url(
            urlset,
            SITE_URL + f'/dictionary/{slug}',
            changefreq='monthly',
            priority='0.6',
        )

    xml_bytes = tostring(urlset, encoding='unicode', xml_declaration=False)
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    return Response(xml_output, mimetype='application/xml')


@seo_bp.route('/robots.txt')
def robots() -> Response:
    """Serve robots.txt."""
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        f'Sitemap: {SITE_URL}/sitemap.xml\n'
    )
    return Response(content, mimetype='text/plain')
