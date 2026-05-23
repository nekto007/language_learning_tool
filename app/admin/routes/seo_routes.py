# app/admin/routes/seo_routes.py

"""Admin SEO analytics — meta-tag coverage audit, sitemap health, and GSC integration."""

import hmac
import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.secret_store import decrypt_secret, encrypt_secret
from app.admin.services.seo_audit_service import (
    SEO_AUDIT_CACHE_KEY,
    SEO_AUDIT_CACHE_TIMEOUT,
    run_seo_audit,
)
from app.admin.site_settings import get_site_setting, set_site_setting
from app.admin.utils.cache import clear_cache_by_prefix, get_cache
from app.admin.utils.decorators import admin_required
from app.utils.db import db

seo_bp = Blueprint('seo_admin', __name__)

logger = logging.getLogger(__name__)


def _get_gsc_refresh_token() -> str:
    """Read the decrypted GSC refresh token, or '' if unset/decrypt fails."""
    return decrypt_secret(get_site_setting('gsc_refresh_token'))


def _gsc_is_connected() -> bool:
    try:
        return bool(_get_gsc_refresh_token())
    except Exception:
        return False


def _google_config_present() -> bool:
    return bool(
        current_app.config.get('GOOGLE_CLIENT_ID')
        and current_app.config.get('GOOGLE_CLIENT_SECRET')
    )


@seo_bp.route('/seo')
@admin_required
def seo_index():
    app = current_app._get_current_object()
    is_cached = get_cache(SEO_AUDIT_CACHE_KEY, timeout=SEO_AUDIT_CACHE_TIMEOUT) is not None
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

    gsc_connected = _gsc_is_connected()
    gsc_data = None
    gsc_site_url = get_site_setting('gsc_site_url') or ''
    gsc_available_sites: list = []
    gsc_error = None

    if gsc_connected:
        try:
            from app.admin.services.gsc_service import (
                fetch_gsc_data,
                get_verified_sites_for_refresh_token,
            )
            gsc_data = fetch_gsc_data(
                refresh_token=_get_gsc_refresh_token(),
                site_url=gsc_site_url,
                client_id=current_app.config.get('GOOGLE_CLIENT_ID', ''),
                client_secret=current_app.config.get('GOOGLE_CLIENT_SECRET', ''),
            )
        except Exception:
            logger.exception('Failed to fetch GSC data')
            gsc_error = 'Не удалось получить данные из Google Search Console. Переподключите аккаунт.'

        try:
            gsc_available_sites = get_verified_sites_for_refresh_token(
                refresh_token=_get_gsc_refresh_token(),
                client_id=current_app.config.get('GOOGLE_CLIENT_ID', ''),
                client_secret=current_app.config.get('GOOGLE_CLIENT_SECRET', ''),
            )
        except Exception:
            logger.exception('Failed to list GSC verified sites')
            gsc_available_sites = []

    return render_template(
        'admin/seo/index.html',
        report=report,
        is_cached=is_cached,
        gsc_connected=gsc_connected,
        gsc_data=gsc_data,
        gsc_site_url=gsc_site_url,
        gsc_available_sites=gsc_available_sites,
        gsc_error=gsc_error,
        google_config_present=_google_config_present(),
    )


@seo_bp.route('/seo/refresh', methods=['POST'])
@admin_required
def seo_refresh():
    clear_cache_by_prefix('seo_audit')
    flash('Кэш SEO аудита очищен. Данные обновятся при следующем открытии страницы.', 'success')
    return redirect(url_for('seo_admin.seo_index'))


@seo_bp.route('/seo/connect')
@admin_required
def gsc_connect():
    """Redirect admin to Google OAuth2 consent screen for GSC read-only access."""
    if not _google_config_present():
        flash('GOOGLE_CLIENT_ID или GOOGLE_CLIENT_SECRET не настроены в конфигурации.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    from app.admin.services.gsc_service import build_flow

    redirect_uri = url_for('seo_admin.gsc_callback', _external=True)
    flow = build_flow(
        redirect_uri=redirect_uri,
        client_id=current_app.config['GOOGLE_CLIENT_ID'],
        client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    session['gsc_oauth_state'] = state
    return redirect(auth_url)


@seo_bp.route('/seo/callback')
@admin_required
def gsc_callback():
    """Handle Google OAuth2 callback — exchange code for tokens and store them."""
    if 'error' in request.args:
        flash(f'Google OAuth ошибка: {request.args["error"]}', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    if not _google_config_present():
        flash('Google OAuth не настроен в конфигурации.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    from app.admin.services.gsc_service import build_flow, get_verified_sites

    redirect_uri = url_for('seo_admin.gsc_callback', _external=True)
    flow = build_flow(
        redirect_uri=redirect_uri,
        client_id=current_app.config['GOOGLE_CLIENT_ID'],
        client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
    )

    expected_state = session.pop('gsc_oauth_state', None)
    received_state = request.args.get('state') or ''
    if not expected_state or not hmac.compare_digest(expected_state, received_state):
        flash('Неверный state параметр. Повторите подключение.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception:
        logger.exception('GSC token exchange failed')
        flash('Ошибка получения токена. Подробности в логах сервера.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    credentials = flow.credentials
    refresh_token = credentials.refresh_token
    if not refresh_token:
        flash(
            'Google не вернул refresh_token. Отзовите доступ приложения в Google Account и переподключите.',
            'warning',
        )
        return redirect(url_for('seo_admin.seo_index'))

    # Determine site_url from verified GSC properties
    sites: list = []
    discovery_failed = False
    try:
        sites = get_verified_sites(credentials)
    except Exception:
        logger.exception('Could not list GSC verified sites')
        discovery_failed = True

    if discovery_failed:
        flash(
            'Не удалось получить список сайтов из Google Search Console. Повторите подключение.',
            'danger',
        )
        return redirect(url_for('seo_admin.seo_index'))

    if not sites:
        flash(
            'У этого Google-аккаунта нет верифицированных сайтов в Search Console. '
            'Подтвердите домен и переподключите.',
            'warning',
        )
        return redirect(url_for('seo_admin.seo_index'))

    if len(sites) > 1:
        logger.info('GSC discovered %d verified sites; defaulting to first: %s', len(sites), sites[0])

    site_url = sites[0]

    set_site_setting('gsc_refresh_token', encrypt_secret(refresh_token))
    set_site_setting('gsc_site_url', site_url)
    log_admin_action(current_user.id, 'gsc_connect', target_type='site_settings')
    db.session.commit()

    msg = f'Google Search Console подключён ({site_url}).'
    if len(sites) > 1:
        msg += ' В аккаунте несколько сайтов — выбран первый из списка.'
    flash(msg, 'success')
    return redirect(url_for('seo_admin.seo_index'))


@seo_bp.route('/seo/disconnect', methods=['POST'])
@admin_required
def gsc_disconnect():
    """Remove stored GSC credentials."""
    set_site_setting('gsc_refresh_token', '')
    set_site_setting('gsc_site_url', '')
    log_admin_action(current_user.id, 'gsc_disconnect', target_type='site_settings')
    db.session.commit()
    flash('Google Search Console отключён.', 'info')
    return redirect(url_for('seo_admin.seo_index'))


@seo_bp.route('/seo/select-site', methods=['POST'])
@admin_required
def gsc_select_site():
    """Switch the active GSC property to one of the admin's verified sites."""
    if not _gsc_is_connected():
        flash('Сначала подключите Google Search Console.', 'warning')
        return redirect(url_for('seo_admin.seo_index'))

    desired = (request.form.get('site_url') or '').strip()
    if not desired:
        flash('Не выбран сайт.', 'warning')
        return redirect(url_for('seo_admin.seo_index'))

    if not _google_config_present():
        flash('Google OAuth не настроен в конфигурации.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    from app.admin.services.gsc_service import get_verified_sites_for_refresh_token

    try:
        verified = get_verified_sites_for_refresh_token(
            refresh_token=_get_gsc_refresh_token(),
            client_id=current_app.config['GOOGLE_CLIENT_ID'],
            client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
        )
    except Exception:
        logger.exception('Failed to verify GSC site selection')
        flash('Не удалось проверить список сайтов. Повторите попытку.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    if desired not in verified:
        flash('Выбранный сайт не верифицирован в этом аккаунте.', 'danger')
        return redirect(url_for('seo_admin.seo_index'))

    set_site_setting('gsc_site_url', desired)
    log_admin_action(current_user.id, 'gsc_select_site', target_type='site_settings')
    db.session.commit()
    clear_cache_by_prefix('seo_audit')
    flash(f'Активный сайт GSC изменён на {desired}.', 'success')
    return redirect(url_for('seo_admin.seo_index'))
