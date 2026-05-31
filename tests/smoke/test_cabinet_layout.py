"""Smoke tests for the cabinet layout (base.html).

Covers Task 6 of the header/footer refresh: verifies that authenticated users
see the cabinet navbar, mobile bottom-nav, and the new 3-column cabinet footer.
"""
import pytest


@pytest.mark.smoke
def test_cabinet_nav_renders_for_auth_user(authenticated_client):
    """Authenticated dashboard renders the Bootstrap cabinet navbar + bottom-nav."""
    response = authenticated_client.get('/study/')
    assert response.status_code == 200, f'/study/ returned {response.status_code}'
    html = response.data.decode('utf-8', errors='replace')

    # Cabinet navbar markers — Bootstrap collapse + our cabinet-nav label wrapper.
    assert 'navbar-expand-lg' in html, 'cabinet navbar missing'
    assert 'cabinet-nav__label' in html, 'cabinet nav labels missing'

    # Mobile bottom navigation is present for authenticated users.
    assert 'class="bottom-nav"' in html, 'cabinet bottom-nav missing'

    # Cabinet footer uses the 3-column grid (synced with public footer).
    assert 'cabinet-footer__grid' in html, 'cabinet footer grid missing'
    assert 'cabinet-footer__col' in html, 'cabinet footer columns missing'

    # Public layout markers must NOT leak into the cabinet layout.
    assert 'public-header' not in html, 'cabinet page leaks public-header marker'


@pytest.mark.smoke
def test_cabinet_footer_has_legal_link_and_current_year(authenticated_client):
    """Cabinet footer exposes the privacy link and a dynamic copyright year."""
    from datetime import datetime, timezone

    response = authenticated_client.get('/study/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')

    assert '/privacy' in html, 'cabinet footer must link to /privacy'
    assert 'Политика конфиденциальности' in html, 'privacy link label missing'

    current_year = str(datetime.now(timezone.utc).year)
    assert current_year in html, f'cabinet footer must render current year ({current_year})'
    assert 'cabinet-footer__brand' in html, 'cabinet footer brand block missing'


@pytest.mark.smoke
def test_cabinet_header_a11y_labels(authenticated_client):
    """Cabinet header icon-only buttons expose aria-label for screen readers."""
    response = authenticated_client.get('/study/')
    assert response.status_code == 200
    html = response.data.decode('utf-8', errors='replace')

    # Notification bell + quick actions are icon-only — must be labelled.
    assert 'aria-label="Уведомления"' in html, 'notif bell missing aria-label'
    assert 'aria-label="Быстрые действия"' in html, 'quick actions missing aria-label'
