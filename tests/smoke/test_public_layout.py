"""Smoke tests for the public layout (public_base.html).

Covers Tasks 2–5 of the header/footer refresh: verifies that anonymous visitors
get rendered public pages and that the shared layout markup is present.
"""
import pytest


# Pages rendered through public_base.html for anonymous visitors. After Task 5
# this also includes legal/auth/SEO pages migrated off base.html.
PUBLIC_URLS = [
    '/',                # landing.index
    '/courses/',        # courses.catalog
    '/grammar-lab/',    # grammar_lab.index
    '/grammar-lab/topics',  # grammar_lab.topics
    '/dictionary',      # words.public_dictionary
    '/privacy',         # legal.privacy
    '/login',           # auth.login
    '/register',        # auth.register
    '/reset_password',  # auth.reset_request
]


# Endpoints that, after Task 5, must NOT extend base.html (the cabinet layout).
# Verified via response markers: cabinet layout exposes `xp-bar` + `bottom-nav`;
# public layout exposes `public-header`. Pages must show the latter only.
NON_CABINET_URLS = PUBLIC_URLS


@pytest.mark.smoke
@pytest.mark.parametrize('url', PUBLIC_URLS)
def test_public_pages_render_for_anon(client, url):
    """Each public URL renders with 200 and contains the public layout markers."""
    response = client.get(url)
    assert response.status_code == 200, f'{url} returned {response.status_code}'
    html = response.data.decode('utf-8', errors='replace')
    assert 'public-header' in html, f'{url} missing .public-header'
    assert 'public-footer' in html, f'{url} missing .public-footer'


@pytest.mark.smoke
def test_public_layout_loads_design_system_css(client):
    """public_base.html must link the canonical design-system.css instead of inline styles."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    assert 'css/design-system.css' in html, 'public layout should load design-system.css'


@pytest.mark.smoke
def test_public_layout_has_no_inline_style_block(client):
    """The legacy inline <style> block must be gone from public_base.html."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    assert '--public-text: #0f172a' not in html, (
        'inline public layout CSS should be served via design-system.css, not inline'
    )


@pytest.mark.smoke
def test_public_header_has_hamburger_toggle(client):
    """The new public header exposes a hamburger toggle (details/summary)."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    assert 'public-nav-collapse' in html, 'public header missing collapse wrapper'
    assert 'public-nav-toggle' in html, 'public header missing hamburger toggle'
    assert 'aria-label="Открыть меню навигации"' in html, 'hamburger toggle missing aria-label'


@pytest.mark.smoke
def test_public_header_drops_broken_books_link(client):
    """The anonymous header no longer points to login-gated book_courses."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    # The legacy broken link to /book-courses must be gone from the public header.
    assert '/book-courses' not in html, (
        'public header must not link to login-gated /book-courses for anonymous visitors'
    )


@pytest.mark.smoke
@pytest.mark.parametrize(
    'url,expected_active_label',
    [
        ('/courses/', 'Курсы'),
        ('/grammar-lab/', 'Грамматика'),
        ('/dictionary', 'Словарь'),
    ],
)
def test_public_header_marks_active_section(client, url, expected_active_label):
    """Current section gets aria-current=page and the active class."""
    response = client.get(url)
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    assert 'public-nav__link--active' in html, f'{url}: no active link rendered'
    assert 'aria-current="page"' in html, f'{url}: missing aria-current="page"'


@pytest.mark.smoke
@pytest.mark.parametrize('url', NON_CABINET_URLS)
def test_migrated_pages_use_public_layout(client, url):
    """SEO/auth/legal pages render via public_base.html — no cabinet markers."""
    response = client.get(url)
    assert response.status_code == 200, f'{url} returned {response.status_code}'
    html = response.data.decode('utf-8', errors='replace')
    assert 'public-header' in html, f'{url} missing public-header marker'
    # base.html exposes the cabinet bottom-nav and xp-bar widgets — must be absent.
    assert 'class="bottom-nav"' not in html, f'{url} leaks cabinet bottom-nav'
    assert 'class="xp-bar"' not in html, f'{url} leaks cabinet xp-bar'
    assert 'navbar-expand-lg' not in html, f'{url} leaks Bootstrap cabinet navbar'


@pytest.mark.smoke
def test_public_footer_has_legal_link_and_copyright(client):
    """The redesigned public footer exposes the privacy link and a dynamic copyright year."""
    from datetime import datetime, timezone

    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')
    assert 'public-footer__grid' in html, 'public footer missing 3-column grid wrapper'
    assert 'public-footer__col' in html, 'public footer columns missing'
    assert '/privacy' in html, 'public footer must link to /privacy'
    assert 'Политика конфиденциальности' in html, 'privacy link label missing'
    current_year = str(datetime.now(timezone.utc).year)
    assert current_year in html, f'public footer must render the current year ({current_year})'
    assert 'public-footer__brand' in html, 'public footer brand block missing'
