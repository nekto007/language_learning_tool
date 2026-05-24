"""Regression tests for the Task 4 UX/UI audit fixes (2026-05-23).

Each test pins one finding from
``docs/audit/2026-05-23-audit-findings.md`` so future refactors stay caught.
"""
from __future__ import annotations

import pytest


# ── F-002 / F-003: SEO audit covers /courses/<level> and grammar c2 ──


@pytest.mark.smoke
def test_seo_audit_includes_course_level_pages():
    from app.admin.services.seo_audit_service import PUBLIC_URLS

    for level in ('A1', 'A2', 'B1', 'B2', 'C1'):
        assert f'/courses/{level}' in PUBLIC_URLS, (
            f'public catalog page for {level} must be SEO-audited'
        )


@pytest.mark.smoke
def test_seo_audit_includes_grammar_c1_topics():
    from app.admin.services.seo_audit_service import PUBLIC_URLS

    assert '/grammar-lab/topics/c1' in PUBLIC_URLS


# ── F-008 / F-009: robots.txt disallows login-walled prefixes ──


@pytest.mark.smoke
def test_robots_txt_disallows_login_walled_prefixes(client):
    response = client.get('/robots.txt')
    assert response.status_code == 200
    text = response.data.decode('utf-8')

    for path in (
        '/admin/',
        '/api/',
        '/onboarding',
        '/uploads/',
        '/curriculum/',
        '/study/',
        '/dashboard',
    ):
        assert f'Disallow: {path}' in text, (
            f'robots.txt should disallow login-walled prefix {path}'
        )


# ── F-006 / F-007: hardcoded llt-english.com share URLs removed ──


def test_final_test_results_template_uses_url_for_for_share_url():
    """The share block must not contain a hardcoded production URL."""
    path = 'app/templates/curriculum/lessons/final_test_results.html'
    with open(path, encoding='utf-8') as f:
        template = f.read()
    assert "share_url = 'https://llt-english.com'" not in template
    assert "url_for('landing.index', _external=True)" in template


def test_levelup_modal_uses_url_for_for_share_url():
    """base.html levelup modal must not hardcode llt-english.com."""
    path = 'app/templates/base.html'
    with open(path, encoding='utf-8') as f:
        template = f.read()
    # The levelup share link should construct its URL via url_for.
    assert "shareVia('telegram','https://llt-english.com'" not in template


# ── AD-022: redundant @login_required removed from admin routes ──


def test_collection_routes_do_not_double_decorate_with_login_required():
    path = 'app/admin/routes/collection_routes.py'
    with open(path, encoding='utf-8') as f:
        source = f.read()
    assert '@login_required' not in source, (
        '@admin_required already wraps with login_required; the explicit '
        '@login_required on top is redundant.'
    )


def test_topic_routes_do_not_double_decorate_with_login_required():
    path = 'app/admin/routes/topic_routes.py'
    with open(path, encoding='utf-8') as f:
        source = f.read()
    assert '@login_required' not in source


def test_grammar_lab_routes_do_not_double_decorate_with_login_required():
    path = 'app/admin/routes/grammar_lab_routes.py'
    with open(path, encoding='utf-8') as f:
        source = f.read()
    assert '@login_required' not in source


# ── AD-023: activity/audit pagination is clamped at an upper bound ──


def test_admin_activity_page_param_is_clamped(admin_client):
    response = admin_client.get('/admin/activity?page=999999')
    assert response.status_code == 200
    # Template renders "Страница {{ page }}" — clamped value (100) must appear,
    # raw input (999999) must NOT, so unclamped regressions fail.
    assert 'Страница 100'.encode('utf-8') in response.data
    assert b'999999' not in response.data


def test_admin_audit_log_page_param_is_clamped(admin_client):
    response = admin_client.get('/admin/audit-log?page=999999')
    assert response.status_code == 200
    assert 'Страница 1000'.encode('utf-8') in response.data
    assert b'999999' not in response.data


# ── AD-024..AD-026: inline styles in admin templates moved to CSS ──


def test_admin_funnel_template_has_no_static_inline_styles():
    path = 'app/templates/admin/activity/funnel.html'
    with open(path, encoding='utf-8') as f:
        template = f.read()
    # Only the dynamic per-step progress width may remain as inline style.
    # All hardcoded background/min-width/font-size must use CSS classes.
    assert 'background-color:#d4edda' not in template
    assert 'background-color:#fff3cd' not in template
    assert 'background-color:#f8d7da' not in template
    assert 'style="min-width: 200px;"' not in template
    assert 'style="font-size: 0.85rem;"' not in template
    assert 'style="width: auto;"' not in template


def test_admin_activity_template_has_no_static_inline_styles():
    path = 'app/templates/admin/activity/index.html'
    with open(path, encoding='utf-8') as f:
        template = f.read()
    assert 'style=' not in template


def test_admin_audit_template_has_no_static_inline_styles():
    path = 'app/templates/admin/audit/index.html'
    with open(path, encoding='utf-8') as f:
        template = f.read()
    assert 'style=' not in template


def test_design_system_css_exposes_admin_helper_classes():
    path = 'app/static/css/design-system.css'
    with open(path, encoding='utf-8') as f:
        css = f.read()
    for cls in (
        '.admin-funnel-select',
        '.admin-funnel-progress',
        '.admin-funnel-cohort-table',
        '.admin-funnel-heatmap--high',
        '.admin-funnel-heatmap--mid',
        '.admin-funnel-heatmap--low',
        '.admin-activity-th--time',
        '.admin-activity-dropdown-list',
        '.admin-audit-th--time',
    ):
        assert cls in css, f'design-system.css must define {cls}'
