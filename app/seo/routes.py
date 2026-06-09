from datetime import date as _date
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Response, abort, current_app
from sqlalchemy import func

from . import seo_bp


def _site_urls() -> list[str]:
    configured = (current_app.config.get('SITE_URL') or '').rstrip('/')
    canonical = 'https://llt-english.com'
    return [configured or canonical]


def _add(urlset: Element, loc: str, priority: str = '0.5', changefreq: str = 'weekly',
         lastmod: str | None = None) -> None:
    url_el = SubElement(urlset, 'url')
    SubElement(url_el, 'loc').text = loc
    SubElement(url_el, 'priority').text = priority
    SubElement(url_el, 'changefreq').text = changefreq
    if lastmod:
        SubElement(url_el, 'lastmod').text = lastmod


@seo_bp.route('/sitemap.xml')
def sitemap() -> Response:
    """Generate sitemap.xml with all public pages."""
    from app.grammar_lab.models import GrammarTopic

    site_urls = _site_urls()
    today = _date.today()

    def _lastmod(dt) -> str | None:
        return min(dt.date(), today).strftime('%Y-%m-%d') if dt else None

    urlset = Element('urlset')
    urlset.set('xmlns', 'http://www.sitemaps.org/schemas/sitemap/0.9')

    # Static pages
    static_pages = [
        ('/', '1.0', 'weekly'),
        ('/grammar-lab/topics', '0.9', 'weekly'),
        ('/dictionary', '0.8', 'weekly'),
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
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    for base_url in site_urls:
        _add(urlset, base_url + '/courses/', '0.8', 'weekly')
        levels = (
            CEFRLevel.query
            .filter(CEFRLevel.code.in_(PUBLIC_CEFR_CODES))
            .order_by(CEFRLevel.order)
            .all()
        )
        for level in levels:
            _add(urlset, f'{base_url}/courses/{level.code}', '0.7', 'weekly',
                 lastmod=_lastmod(level.updated_at))

    # Grammar level listing pages — lastmod = newest topic edit at that level.
    from app.utils.db import db as _db
    grammar_levels = (
        _db.session.query(GrammarTopic.level, func.max(GrammarTopic.updated_at))
        .filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .group_by(GrammarTopic.level)
        .all()
    )
    for base_url in site_urls:
        for lvl, lvl_updated in grammar_levels:
            _add(urlset, f'{base_url}/grammar-lab/topics/{lvl.lower()}', '0.7', 'weekly',
                 lastmod=_lastmod(lvl_updated))

    # Grammar topics
    topics = (
        GrammarTopic.query
        .filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .order_by(GrammarTopic.level, GrammarTopic.order)
        .all()
    )
    for base_url in site_urls:
        for topic in topics:
            _add(urlset, f'{base_url}/grammar-lab/topic/{topic.slug}', '0.7', 'monthly',
                 lastmod=_lastmod(topic.updated_at))

    # Dictionary pages — all public words, capped at Google's per-sitemap limit (50k).
    # Words ordered by frequency_rank so the most valuable URLs are indexed first
    # if the cap is ever hit.
    from app.words.models import CollectionWords
    top_words = (
        CollectionWords.query
        .filter(CollectionWords.item_type == 'word')
        .filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
        .order_by(
            CollectionWords.frequency_rank.asc().nullslast(),
            CollectionWords.id.asc(),
        )
        .limit(45000)
        .all()
    )
    letters = (
        _db.session.query(func.lower(func.substr(CollectionWords.english_word, 1, 1)))
        .filter(CollectionWords.item_type == 'word')
        .filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
        .distinct()
        .all()
    )
    dict_levels = (
        _db.session.query(CollectionWords.level)
        .filter(CollectionWords.item_type == 'word')
        .filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
        .distinct()
        .all()
    )
    from app.words.routes import PUBLIC_DICTIONARY_ALPHABET, encode_word_slug
    for base_url in site_urls:
        for (letter,) in letters:
            if letter and len(letter) == 1 and letter in PUBLIC_DICTIONARY_ALPHABET:
                _add(urlset, f'{base_url}/dictionary/letter/{letter}', '0.5', 'weekly')
        for (lvl,) in dict_levels:
            if lvl:
                _add(urlset, f'{base_url}/dictionary/level/{lvl.lower()}', '0.6', 'weekly')
        for word in top_words:
            _add(urlset, f'{base_url}/dictionary/{encode_word_slug(word.english_word)}', '0.6', 'monthly')

    # Word contrast pages — one URL per curated pair. Each one targets a
    # distinct «X vs Y / разница между X и Y» search intent, so they earn
    # their own sitemap entries with a slightly higher priority than
    # individual dictionary pages.
    from app.words.models import WordContrast
    from app.words.routes import encode_word_slug
    contrasts = (
        WordContrast.query
        .join(CollectionWords, CollectionWords.id == WordContrast.word_a_id)
        .filter(CollectionWords.item_type == 'word')
        .filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
        .all()
    )
    public_levels = set(PUBLIC_CEFR_CODES)
    for base_url in site_urls:
        for c in contrasts:
            a, b = c.word_a, c.word_b
            if not a or not b:
                continue
            if (a.level and a.level not in public_levels) or (
                b.level and b.level not in public_levels
            ):
                continue
            _add(
                urlset,
                f'{base_url}/contrast/{encode_word_slug(a.english_word)}/'
                f'{encode_word_slug(b.english_word)}',
                '0.7', 'monthly',
            )

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding='unicode').encode('utf-8')
    return Response(xml_bytes, mimetype='application/xml')


@seo_bp.route('/llms.txt')
def llms_txt() -> Response:
    """Serve llms.txt — emerging standard declaring site structure for LLM crawlers."""
    site_url = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
    content = (
        '# LLT English — Language Learning Tool\n\n'
        '> Бесплатная платформа для изучения английского языка: '
        'грамматика с правилами и примерами, англо-русский словарь с уровнями CEFR, '
        'аудио, упражнения и интервальное повторение.\n\n'
        '## Основные разделы\n\n'
        f'- [Главная]({site_url}/): курсы по уровням, словарь, грамматика\n'
        f'- [Каталог курсов]({site_url}/courses/): курсы английского по уровням A1–C1\n'
        f'- [Грамматика английского]({site_url}/grammar-lab/topics): темы с правилами, '
        'примерами и таблицами\n'
        f'- [Англо-русский словарь]({site_url}/dictionary): переводы, IPA, '
        'примеры, частотность\n\n'
        '## Структурированные данные\n\n'
        '- WebSite / FAQPage на главной\n'
        '- LearningResource + BreadcrumbList + FAQPage на страницах грамматических тем\n'
        '- DefinedTerm на страницах словаря\n'
        '- Course / CourseInstance в каталоге курсов\n'
        '- ItemList на листингах\n\n'
        '## Машинные ресурсы\n\n'
        f'- [Sitemap]({site_url}/sitemap.xml)\n'
        f'- [Robots]({site_url}/robots.txt)\n'
    )
    return Response(content, mimetype='text/plain; charset=utf-8')


@seo_bp.route('/og/word/<word_slug>.png')
def og_word(word_slug: str) -> Response:
    """Branded OG image for a public word page."""
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.seo.og_image import render_og_image
    from app.words.models import CollectionWords
    from app.words.routes import decode_word_slug

    name = decode_word_slug(word_slug)
    word = (
        CollectionWords.query
        .filter(func.lower(CollectionWords.english_word) == name.lower())
        .first()
    )
    if not word:
        abort(404)
    if word.level and word.level not in PUBLIC_CEFR_CODES:
        abort(404)

    data = render_og_image(
        kind='word',
        title=word.english_word,
        subtitle=word.russian_word or '',
        level=word.level or '',
    )
    return Response(
        data,
        mimetype='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@seo_bp.route('/og/contrast/<a_slug>/<b_slug>.png')
def og_contrast(a_slug: str, b_slug: str) -> Response:
    """Branded OG image for a contrast pair page."""
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.seo.og_image import render_og_image
    from app.words.models import CollectionWords, WordContrast
    from app.words.routes import decode_word_slug

    a_name = decode_word_slug(a_slug)
    b_name = decode_word_slug(b_slug)
    a = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == a_name.lower()
    ).first()
    b = CollectionWords.query.filter(
        func.lower(CollectionWords.english_word) == b_name.lower()
    ).first()
    if not a or not b or a.id == b.id:
        abort(404)
    for w in (a, b):
        if w.level and w.level not in PUBLIC_CEFR_CODES:
            abort(404)

    low_id, high_id = sorted((a.id, b.id))
    if not WordContrast.query.filter_by(word_a_id=low_id, word_b_id=high_id).first():
        abort(404)

    # Show ``a vs b`` in canonical order. Same level for both is shown when
    # they match; otherwise drop the level pill to avoid a misleading badge.
    title = f'{a.english_word if a.id == low_id else b.english_word} vs ' \
            f'{b.english_word if a.id == low_id else a.english_word}'
    level = a.level if a.level == b.level else ''

    data = render_og_image(
        kind='contrast', title=title, subtitle='в чём разница',
        level=level or '',
    )
    return Response(
        data, mimetype='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@seo_bp.route('/og/grammar/<slug>.png')
def og_grammar(slug: str) -> Response:
    """Branded OG image for a grammar topic page."""
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.models import GrammarTopic
    from app.seo.og_image import render_og_image

    topic = GrammarTopic.query.filter_by(slug=slug).first()
    if not topic or (topic.level and topic.level not in PUBLIC_CEFR_CODES):
        abort(404)
    title = topic.title_ru or topic.title or ''
    subtitle = topic.title if topic.title and topic.title != title else ''
    data = render_og_image(
        kind='grammar',
        title=title,
        subtitle=subtitle,
        level=topic.level or '',
    )
    return Response(
        data,
        mimetype='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@seo_bp.route('/robots.txt')
def robots() -> Response:
    """Serve robots.txt."""
    site_url = (current_app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /admin/\n'
        'Disallow: /api/\n'
        'Disallow: /onboarding\n'
        'Disallow: /onboarding/\n'
        'Disallow: /uploads/\n'
        'Disallow: /curriculum/\n'
        'Disallow: /study/\n'
        'Disallow: /dashboard\n'
        'Disallow: /achievements\n'
        'Disallow: /telegram/\n'
        'Disallow: /reset_password\n'
        'Disallow: /notifications/\n'
    )
    content += f'\nSitemap: {site_url}/sitemap.xml\n'
    return Response(content, mimetype='text/plain')
