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
