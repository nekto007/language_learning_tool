# app/admin/routes/seo_routes.py

"""Admin SEO analytics — meta-tag coverage audit and sitemap health."""

import logging

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from app.admin.services.seo_audit_service import SEO_AUDIT_CACHE_KEY, run_seo_audit
from app.admin.utils.cache import clear_cache_by_prefix, get_cache
from app.admin.utils.decorators import admin_required

seo_bp = Blueprint('seo_admin', __name__)

logger = logging.getLogger(__name__)


@seo_bp.route('/seo')
@admin_required
def seo_index():
    app = current_app._get_current_object()
    try:
        report = run_seo_audit(app)
    except Exception:
        logger.exception('SEO audit failed')
        report = {
            'pages': [],
            'sitemap': {'url_count': 0, 'newest_lastmod': None, 'error': 'Audit failed'},
            'fully_covered_count': 0,
            'reachable_count': 0,
            'total_pages': 0,
        }
    cached = get_cache(SEO_AUDIT_CACHE_KEY, timeout=3600)
    is_cached = cached is not None
    return render_template(
        'admin/seo/index.html',
        report=report,
        is_cached=is_cached,
        gsc_connected=False,  # placeholder until Task 4
    )


@seo_bp.route('/seo/refresh', methods=['POST'])
@admin_required
def seo_refresh():
    clear_cache_by_prefix('seo_audit')
    flash('Кэш SEO аудита очищен. Данные обновятся при следующем открытии страницы.', 'success')
    return redirect(url_for('seo_admin.seo_index'))
