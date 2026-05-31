"""Smoke tests for the public layout (public_base.html).

Covers Task 2 of the header/footer refresh: verifies that anonymous visitors
get rendered public pages and that the shared layout markup is present.
"""
import pytest


# Pages currently rendered through public_base.html for anonymous visitors.
# (Auth/legal templates migrate to public_base.html in Task 5; not yet covered here.)
PUBLIC_URLS = [
    '/',                # landing.index
    '/courses/',        # courses.catalog
    '/grammar-lab/',    # grammar_lab.index
    '/dictionary',      # words.public_dictionary
]


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
