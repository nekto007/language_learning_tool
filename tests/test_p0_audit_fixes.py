"""Regression tests for the P0 fixes shipped from the 2026-05-23 site audit.

Each test pins one finding from
``docs/audit/2026-05-23-audit-findings.md`` so a future refactor that
regresses one of these stays caught.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest


# ── F-001: SEO audit URL list must not contain the dead /book-courses ──


@pytest.mark.smoke
def test_seo_audit_public_urls_use_courses_not_book_courses():
    from app.admin.services.seo_audit_service import PUBLIC_URLS

    assert '/book-courses' not in PUBLIC_URLS, (
        '/book-courses 404s — the public catalog lives at /courses'
    )
    assert '/curriculum/book-courses' not in PUBLIC_URLS, (
        '/curriculum/book-courses is login-required and should not be audited '
        'as a public SEO page'
    )
    assert '/courses/' in PUBLIC_URLS
    assert '/dictionary' in PUBLIC_URLS


@pytest.mark.smoke
def test_seo_audit_excludes_login_required_learning_tools():
    from app.admin.services.seo_audit_service import PUBLIC_URLS

    assert '/books' not in PUBLIC_URLS
    assert '/words' not in PUBLIC_URLS
    assert '/study/collections' not in PUBLIC_URLS
    assert '/study/topics' not in PUBLIC_URLS


def test_seo_audit_rejects_old_cache_without_public_url_signature():
    from app.admin.services.seo_audit_service import _cached_urls_match_current

    assert _cached_urls_match_current({'pages': [{'url': '/courses/C2'}]}) is False


# ── F-004: reset_request renders meta description + canonical ──


@pytest.mark.smoke
def test_reset_request_page_has_meta_description_and_canonical(client):
    response = client.get('/reset_password')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert '<meta name="description"' in html
    assert '<link rel="canonical"' in html


@pytest.mark.smoke
def test_seo_audited_auth_get_pages_do_not_trigger_rate_limit(client):
    """SEO audit uses GET requests, so auth form pages must not spend POST limits."""
    paths = ['/login', '/register', '/reset_password']

    for _ in range(12):
        for path in paths:
            response = client.get(path)
            assert response.status_code != 429


# ── C-001: parsers.os.remove cleanup must log on failure, not swallow ──


def test_parsers_cleanup_logs_on_oserror(caplog):
    """Force the inner os.remove to fail and verify the logger sees it."""
    from app.books import parsers

    class _StubFile:
        filename = 'broken.txt'

        def save(self, path):
            # Pretend the upload succeeded so process_book_file proceeds to
            # parse + cleanup. We control os.path.exists/os.remove below.
            return None

    with patch('app.books.parsers.os.makedirs'), \
         patch('app.books.parsers.parse_book_file',
               side_effect=RuntimeError('parse blew up')), \
         patch('app.books.parsers.os.path.exists', return_value=True), \
         patch('app.books.parsers.os.remove', side_effect=OSError('boom')):
        with caplog.at_level(logging.WARNING, logger='app.books.parsers'):
            with pytest.raises(RuntimeError):
                parsers.process_uploaded_book(
                    file=_StubFile(), title='test', format_type='enhanced'
                )
    assert any('Failed to clean up temp file' in r.message for r in caplog.records)


# ── C-002: api_auth_required logs JWT verification failures ──


def test_api_auth_required_logs_jwt_failure(app, caplog):
    """A bad JWT must produce a 401 AND log the underlying failure."""
    from app.api.decorators import api_auth_required

    @api_auth_required
    def _endpoint():  # pragma: no cover — only reached on auth success
        return 'ok'

    with app.test_request_context(
        '/api/test', headers={'Authorization': 'Bearer not-a-real-jwt'}
    ):
        with caplog.at_level(logging.WARNING, logger='app.api.decorators'):
            response = _endpoint()
    # Flask helper returns (response, status) tuple here.
    assert response[1] == 401
    assert any('JWT verification failed' in r.message for r in caplog.records)


# ── C-004: onboarding wizard sanitizes ?next= on intake ──


def test_onboarding_wizard_strips_open_redirect_in_next_param(
    authenticated_client, test_user, db_session,
):
    test_user.onboarding_completed = False
    db_session.commit()
    response = authenticated_client.get(
        '/onboarding?next=https://evil.com/steal'
    )
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    # The malicious external URL must not survive into the form's hidden
    # `next` input — get_safe_redirect_url drops it on intake.
    assert 'evil.com' not in html


def test_onboarding_wizard_keeps_safe_local_next_param(
    authenticated_client, test_user, db_session,
):
    test_user.onboarding_completed = False
    db_session.commit()
    response = authenticated_client.get(
        '/onboarding?next=/study/insights'
    )
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert '/study/insights' in html
