import logging
import os
import threading
import time

from flask import Flask
from flask_compress import Compress
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from app.utils.db import db
from app.utils.i18n import init_babel
from app.utils.rate_limit_helpers import get_remote_address_key
from config.settings import Config

logger = logging.getLogger(__name__)

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Endpoint prefixes that skip onboarding redirect
_ONBOARDING_SKIP_PREFIXES = (
    'onboarding.', 'auth.', 'static', 'legal.', 'seo.',
    'grammar_lab.', 'landing.', 'telegram.',
    'api_auth.', 'api_words.', 'api_books.', 'api_books_catalog.',
    'api_anki.',
    'api_topics_collections.', 'api_daily_plan.',
    'uploads.',
    'admin.', 'user_admin.', 'audio_admin.', 'book_admin.',
    'collection_admin.', 'topic_admin.', 'word_admin.',
    'system_admin.', 'grammar_lab_admin.', 'admin_curriculum.',
    'curriculum_admin.', 'reminders.', 'settings_admin.', 'seo_admin.',
    'activity_admin.', 'audit_admin.', 'dashboard_admin.',
    'feedback.', 'feedback_admin.', 'acquisition_admin.',
    'telegram_channel_admin.', 'word_contrast_admin.',
    'refresh_csrf_token',
    'health_check',
    'reminder_tracking.',
)

csrf = CSRFProtect()

# Module-level TTL cache for public site settings (avoids DB query on every request).
_site_settings_cache: dict = {'data': None, 'expires': 0.0, 'lock': threading.Lock()}
_SITE_SETTINGS_TTL = 60  # seconds

jwt = JWTManager()

limiter = Limiter(
    key_func=get_remote_address_key,
    default_limits=["10000 per hour", "100 per second"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
    swallow_errors=not os.environ.get('FLASK_DEBUG', ''),  # raise in debug, degrade gracefully in prod
    strategy="fixed-window"
)


def create_app(config_class=Config):
    from config.logging_config import configure_logging
    configure_logging()

    app = Flask(__name__)
    app.config.from_object(config_class)

    # Distinguish a SERVED web process (gunicorn / `flask run`) from a one-off
    # `flask <cmd>` management command (db upgrade, seed, start-email-scheduler,
    # ...). Background services and per-worker cache warming run only when
    # serving — see _start_background_services() and curriculum init_cache().
    app.config['IS_MANAGEMENT_COMMAND'] = _is_management_command()

    if not app.config.get('TESTING'):
        from config.settings import validate_environment
        validate_environment()

    # Behind nginx: trust X-Forwarded-Proto so request.scheme reflects HTTPS,
    # which makes url_for(_external=True) emit https://... URLs (otherwise
    # Flask sees the loopback gunicorn connection as http and links generated
    # inside templates — including reminder-email images — get blocked by the
    # `img-src 'self' data: https:` CSP on the production site).
    if not app.config.get('TESTING'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Fallback for URL generation outside a request context (email scheduler,
    # CLI tasks). With this set, url_for(_external=True) defaults to https://
    # even when there's no incoming request to read X-Forwarded-Proto from.
    app.config.setdefault('PREFERRED_URL_SCHEME', 'https')

    # Configure JWT
    from datetime import timedelta
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=15)
    app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)
    app.config['JWT_TOKEN_LOCATION'] = ['headers']
    app.config['JWT_HEADER_NAME'] = 'Authorization'
    app.config['JWT_HEADER_TYPE'] = 'Bearer'

    csrf.init_app(app)
    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)

    # Warn if using in-memory rate limit storage in production
    if not app.config.get('TESTING') and os.environ.get('RATELIMIT_STORAGE_URI', 'memory://') == 'memory://':
        logger.warning(
            "Rate limit storage is 'memory://' — limits are not shared across workers. "
            "Set RATELIMIT_STORAGE_URI to a Redis URL for production deployments."
        )
    jwt.init_app(app)
    init_babel(app)

    app.config.setdefault('COMPRESS_MIMETYPES', [
        'text/html', 'text/css', 'text/xml', 'text/javascript',
        'application/json', 'application/javascript',
    ])
    app.config.setdefault('COMPRESS_LEVEL', 6)
    app.config.setdefault('COMPRESS_MIN_SIZE', 500)
    Compress(app)

    # Import all models in dependency order - MUST happen before any blueprint that uses models
    from app.achievements import daily_race as achievements_daily_race  # noqa: F401
    from app.achievements import models as achievements_models  # noqa: F401
    from app.admin import audit as admin_audit  # noqa: F401
    from app.auth import models as auth_models  # noqa: F401
    from app.books import models as books_models  # noqa: F401
    from app.books import reading_session as books_reading_session  # noqa: F401
    from app.curriculum import book_courses as book_courses_models  # noqa: F401
    from app.curriculum import daily_lessons as daily_lessons_models  # noqa: F401
    from app.curriculum import models as curriculum_models  # noqa: F401
    from app.daily_plan import models as daily_plan_models  # noqa: F401
    from app.daily_plan.linear import models as daily_plan_linear_models  # noqa: F401
    from app.feedback import models as feedback_models  # noqa: F401
    from app.grammar_lab import models as grammar_models  # noqa: F401
    from app.modules import models as modules_models  # noqa: F401
    from app.notifications import models as notifications_models  # noqa: F401
    from app.reminders import models as reminders_models  # noqa: F401
    from app.study import models as study_models  # noqa: F401
    from app.telegram import channel_models as telegram_channel_models  # noqa: F401
    from app.telegram import models as telegram_models  # noqa: F401
    from app.words import models as words_models  # noqa: F401  # Also defines word_book_link table

    # In production, schema is managed by Alembic (`flask db upgrade head`).
    # In testing, create tables directly so tests don't need migrations.
    if app.config.get('TESTING', False):
        with app.app_context():
            db.create_all()

    from app.utils.template_utils import init_template_utils
    init_template_utils(app)

    from app.middleware.security import add_security_headers
    add_security_headers(app)

    from app.middleware.request_id import add_request_id
    add_request_id(app)

    from app.middleware.acquisition import add_acquisition_capture
    add_acquisition_capture(app)

    os.makedirs(app.config['AUDIO_UPLOAD_FOLDER'], exist_ok=True)

    # Landing page must be first — owns the root route
    from app.landing import landing_bp
    app.register_blueprint(landing_bp)

    from app.auth.routes import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from app.words.routes import words as words_blueprint
    app.register_blueprint(words_blueprint)

    from app.books.routes import books as books_blueprint
    app.register_blueprint(books_blueprint)

    from app.books.api import books_api as books_api_blueprint
    app.register_blueprint(books_api_blueprint)

    # Register admin routes (handles book courses separately to avoid circular imports)
    from app.admin import register_admin_routes
    register_admin_routes(app)

    from app.reminders.routes import reminders as reminders_blueprint
    app.register_blueprint(reminders_blueprint)

    from app.reminders.tracking import reminder_tracking as reminder_tracking_blueprint
    app.register_blueprint(reminder_tracking_blueprint)

    from app.study.routes import study as study_blueprint
    app.register_blueprint(study_blueprint, url_prefix='/study')

    from app.api.auth import api_auth as api_auth_blueprint
    app.register_blueprint(api_auth_blueprint, url_prefix='/api')

    from app.api.words import api_words as api_words_blueprint
    app.register_blueprint(api_words_blueprint, url_prefix='/api')

    from app.api.books import api_books as api_books_blueprint
    app.register_blueprint(api_books_blueprint, url_prefix='/api')

    from app.api.books_catalog import api_books_catalog as api_books_catalog_blueprint
    app.register_blueprint(api_books_catalog_blueprint, url_prefix='/api')

    from app.api.anki import api_anki as api_anki_blueprint
    app.register_blueprint(api_anki_blueprint, url_prefix='/api')

    from app.api.topics_collections import api_topics_collections
    app.register_blueprint(api_topics_collections, url_prefix='/api')

    from app.api.daily_plan import api_daily_plan
    app.register_blueprint(api_daily_plan, url_prefix='/api')

    from app.curriculum import curriculum_bp, init_curriculum_module
    app.register_blueprint(curriculum_bp, url_prefix='/curriculum')

    init_curriculum_module(app)

    from app.modules import modules_bp
    app.register_blueprint(modules_bp)

    from app.grammar_lab import grammar_lab_bp
    app.register_blueprint(grammar_lab_bp)

    from app.onboarding import onboarding_bp
    app.register_blueprint(onboarding_bp)

    from app.feedback import feedback_bp
    app.register_blueprint(feedback_bp)

    from app.seo import seo_bp
    app.register_blueprint(seo_bp)

    from app.legal import legal_bp
    app.register_blueprint(legal_bp)

    from app.race import race_bp
    app.register_blueprint(race_bp)

    from app.telegram import telegram_bp
    app.register_blueprint(telegram_bp)

    from app.notifications import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')

    from app.uploads.routes import uploads as uploads_blueprint
    app.register_blueprint(uploads_blueprint, url_prefix='/uploads')

    from app.modules.service import ModuleService

    def has_module(module_code) -> bool:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return False
        return ModuleService.is_module_enabled_for_user(current_user.id, module_code)

    def get_user_modules() -> list:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return []
        return ModuleService.get_user_modules(current_user.id, enabled_only=True)

    def books_nav_visible() -> bool:
        from flask_login import current_user
        from app.books.access import books_section_visible
        return books_section_visible(current_user)

    app.jinja_env.globals.update(enumerate=enumerate)
    app.jinja_env.globals.update(chr=chr)
    app.jinja_env.globals.update(has_module=has_module)
    app.jinja_env.globals.update(get_user_modules=get_user_modules)
    app.jinja_env.globals.update(books_nav_visible=books_nav_visible)

    # CSRF token refresh endpoint (for long-lived pages like quizzes)
    from flask import jsonify as _jsonify
    from flask_login import login_required as _login_required

    @app.route('/csrf-token', methods=['GET'])
    @_login_required
    def refresh_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return _jsonify({'csrf_token': generate_csrf()})

    # Health check blueprint (no auth, no CSRF)
    from app.health import health_bp
    app.register_blueprint(health_bp)
    csrf.exempt(app.view_functions['health_check.health'])

    # Add CSRF error handler for AJAX requests
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        from flask import jsonify, request

        # Return JSON for AJAX requests and API endpoints
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        is_api = request.path.startswith('/api/')
        accepts_json = 'application/json' in request.headers.get('Accept', '')

        if is_ajax or is_api or accepts_json:
            return jsonify({
                'success': False, 'error': 'CSRF token expired. Please refresh the page.', 'csrf_expired': True,
            }), 400

        # Обычная форма: вместо голого текста — flash и возврат на страницу,
        # чтобы пользователь мог сразу повторить отправку со свежим токеном.
        from flask import flash, redirect

        from app.auth.routes import get_safe_redirect_url
        flash('Сессия устарела, страница обновлена — попробуйте ещё раз.', 'warning')
        return redirect(get_safe_redirect_url(request.referrer, fallback='/'))

    def _wants_json():
        """Check if the client prefers a JSON response."""
        from flask import request
        return (
            request.path.startswith('/api/')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    @app.errorhandler(403)
    def handle_403_error(e):
        from flask import jsonify, render_template

        from app.admin.error_handlers import is_admin_request, render_admin_403
        if _wants_json():
            return jsonify({'success': False, 'error': 'forbidden', 'message': 'Forbidden', 'status': 403}), 403
        if is_admin_request():
            return render_admin_403()
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def handle_404_error(e):
        from flask import jsonify, render_template

        from app.admin.error_handlers import is_admin_request, render_admin_404
        if _wants_json():
            return jsonify({'success': False, 'error': 'not_found', 'message': 'Not found', 'status': 404}), 404
        if is_admin_request():
            return render_admin_404()
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def handle_500_error(e):
        from flask import jsonify, render_template

        from app.admin.error_handlers import is_admin_request, render_admin_500
        from app.admin.routes.dashboard_routes import increment_5xx_counter
        try:
            db.session.rollback()
        except Exception:
            logger.exception("Failed to rollback session in 500 handler")
        increment_5xx_counter()
        if _wants_json():
            return jsonify({
                'success': False, 'error': 'internal_error', 'message': 'Internal server error', 'status': 500,
            }), 500
        if is_admin_request():
            return render_admin_500()
        return render_template('errors/500.html'), 500

    @login_manager.user_loader
    def load_user(user_id):
        from app.auth.models import User
        try:
            return User.query.get(int(user_id))
        except Exception:
            db.session.rollback()
            logger.exception("Failed to load user %s", user_id)
            return None

    @app.before_request
    def redirect_www_to_apex():
        """Consolidate the www host to the apex host — one canonical host (SEO)."""
        from flask import redirect, request

        host = request.host or ''
        if host.split(':')[0].startswith('www.'):
            apex_host = host[4:]
            new_url = request.url.replace('://' + host, '://' + apex_host, 1)
            code = 301 if request.method in ('GET', 'HEAD') else 308
            return redirect(new_url, code=code)

    @app.before_request
    def update_last_active():
        """Update user's last_login every 12 hours on activity"""
        from datetime import datetime, timedelta, timezone

        from flask import redirect, request, url_for
        from flask_login import current_user

        try:
            is_auth = current_user.is_authenticated
        except Exception:
            is_auth = False

        if is_auth:
            now = datetime.now(timezone.utc)
            # Update if last_login is None or older than 12 hours
            if current_user.last_login is None or \
               (now - current_user.last_login.replace(tzinfo=timezone.utc)) > timedelta(hours=12):
                current_user.last_login = now
                db.session.commit()

            # Redirect to onboarding if not completed (e.g. remember-me cookie login)
            # Skip AJAX/API requests and public/auth endpoints
            if not current_user.onboarding_completed and request.endpoint \
               and not any(request.endpoint.startswith(p) for p in _ONBOARDING_SKIP_PREFIXES) \
               and request.headers.get('X-Requested-With') != 'XMLHttpRequest' \
               and 'application/json' not in request.headers.get('Accept', ''):
                return redirect(url_for('onboarding.wizard', next=request.path))

    @login_manager.unauthorized_handler
    def unauthorized():
        """Custom unauthorized handler that preserves the original URL"""
        from flask import jsonify, redirect, request, url_for

        # For AJAX requests, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Authentication required'}), 401

        # For regular requests, redirect to login with next parameter
        return redirect(url_for('auth.login', next=request.url))

    _LESSON_ENDPOINT_PREFIXES = (
        'curriculum_lessons.',
        'learn.',
        'study.',
        'books.',
        'book_courses.',
    )

    @app.context_processor
    def _inject_daily_plan_ctx():
        from flask import request
        from flask_login import current_user

        try:
            if not current_user.is_authenticated:
                return {}
        except Exception:
            return {}

        endpoint = request.endpoint or ''
        if not any(endpoint.startswith(prefix) for prefix in _LESSON_ENDPOINT_PREFIXES):
            return {}

        # Skip non-page endpoints inside lesson blueprints (e.g. API JSON helpers).
        if endpoint.endswith('_json') or '.api_' in endpoint:
            return {}

        from app.daily_plan.linear.lesson_context import build_lesson_context

        lesson_id = None
        view_args = request.view_args or {}
        for key in ('lesson_id', 'lesson'):
            val = view_args.get(key)
            if isinstance(val, int):
                lesson_id = val
                break
            if isinstance(val, str) and val.isdigit():
                lesson_id = int(val)
                break

        try:
            # NB: pass the SQLAlchemy `db` object, not `db.session`. The
            # downstream call chain (build_lesson_context → get_daily_plan
            # → find_next_lesson_linear) does `db.session.query(...)`; if
            # we hand it a scoped session, that becomes `session.session`
            # and silently dies, leaving the lesson page with catalog CTAs
            # even when ?from=linear_plan is set on the URL.
            ctx = build_lesson_context(
                current_user.id, db, current_lesson_id=lesson_id
            )
        except Exception:
            logger.exception("daily_plan_ctx build failed for endpoint=%s", endpoint)
            return {}

        return {'daily_plan_ctx': ctx}

    @app.context_processor
    def _inject_current_year():
        from datetime import datetime, timezone
        return {'current_year': datetime.now(timezone.utc).year}

    @app.context_processor
    def _inject_site_settings():
        from flask import g

        # Fast path: already resolved for this request.
        request_cached = getattr(g, '_site_settings_cached', None)
        if request_cached is not None:
            return {'site_settings': request_cached}

        # Cross-request TTL cache: one DB query per 60 s across all requests.
        now = time.time()
        with _site_settings_cache['lock']:
            if _site_settings_cache['data'] is not None and now < _site_settings_cache['expires']:
                result = _site_settings_cache['data']
                g._site_settings_cached = result
                return {'site_settings': result}

        try:
            from app.admin.site_settings import get_public_settings
            fresh = get_public_settings()
        except Exception:
            # On failure NEVER overwrite a populated cache with {} — a single
            # slow/erroring load would blank contacts/feature-flags for everyone
            # until TTL (audit E-084). Serve stale-good if we have it; otherwise
            # cache empty only briefly so we retry soon.
            logger.exception('Failed to load public site settings')
            with _site_settings_cache['lock']:
                existing = _site_settings_cache['data']
                if existing is not None:
                    _site_settings_cache['expires'] = time.time() + _SITE_SETTINGS_TTL
                else:
                    existing = {}
                    _site_settings_cache['expires'] = time.time() + 5
            g._site_settings_cached = existing
            return {'site_settings': existing}

        with _site_settings_cache['lock']:
            _site_settings_cache['data'] = fresh
            _site_settings_cache['expires'] = time.time() + _SITE_SETTINGS_TTL

        g._site_settings_cached = fresh
        return {'site_settings': fresh}

    # Set up database-specific optimizations via SQLAlchemy events
    from app.utils.db_config import configure_database_engine
    configure_database_engine(app, db)

    # Register CLI commands for startup jobs (seed, warm-cache, start-bot, start-email-scheduler)
    _register_cli_commands(app)

    # Start runtime background services — only in a serving web process.
    _start_background_services(app)

    return app


def _is_management_command() -> bool:
    """True when this process is a one-off ``flask <subcommand>`` management
    command (db upgrade, seed, warm-cache, start-email-scheduler, ...) rather
    than a served web app (gunicorn or ``flask run``).

    AUTO-started background services (``_start_background_services``) and
    per-worker cache warming must NOT run in these processes: a short-lived
    ``flask <cmd>`` would spin up a scheduler thread that dies the moment the
    command finishes. The long-lived ``flask start-email-scheduler`` (the
    dedicated scheduler container) is the exception — it starts the Telegram +
    email schedulers EXPLICITLY in its command body, which is their single
    stable home.
    """
    import sys
    prog = os.path.basename(sys.argv[0] or '')
    if prog != 'flask':
        # gunicorn, `python run.py`, pytest — treat as a serving/test process.
        return False
    # `flask run` is a serving process; any other `flask <cmd>` is management.
    return not (len(sys.argv) > 1 and sys.argv[1] == 'run')


def _start_background_services(app) -> None:
    """Single home for runtime services that belong to a SERVING web process
    (gunicorn / ``flask run``). Skipped in tests and management commands.

    The Telegram scheduler deliberately does NOT run here. It used to auto-start
    inside whichever gunicorn worker won an advisory lock, but gunicorn recycles
    workers (timeout/memory): the lock-holder dies, a restarted worker grabs the
    freed lock, and you end up with TWO _hourly_check loops → duplicate
    notifications. It now lives in exactly one stable, single-process place — the
    dedicated ``scheduler`` container, which starts it explicitly in
    ``start-email-scheduler``. Add future serving-process background services
    here; keep the gating in one place rather than inline in create_app().
    """
    if app.config.get('TESTING') or app.config.get('IS_MANAGEMENT_COMMAND'):
        return
    # No serving-process background services at the moment — the Telegram
    # scheduler runs in the dedicated scheduler container (see above).


def _register_cli_commands(app):
    """Register CLI commands for operations previously done as side effects in create_app()."""
    import click

    @app.cli.command('seed')
    def seed_cmd():
        """Seed initial data (modules and achievements). Safe to run multiple times."""
        from app.achievements.seed import seed_achievements
        from app.modules.migrations import seed_initial_modules
        seed_initial_modules()
        seed_achievements()
        click.echo('Seeding complete.')

    @app.cli.command('seed-word-contrasts')
    def seed_word_contrasts_cmd():
        """Load word_contrasts.json into the DB. Idempotent (existing pairs untouched)."""
        from app.words.seed_contrasts import seed_word_contrasts
        created, skipped, missing = seed_word_contrasts()
        click.echo(
            f'Word contrasts seeded: {created} created, {skipped} already present, '
            f'{missing} skipped (word not in DB).'
        )

    @app.cli.command('warm-cache')
    def warm_cache_cmd():
        """Warm the curriculum cache."""
        from app.curriculum.cache import warm_cache
        from app.curriculum.models import CEFRLevel
        if CEFRLevel.query.count() > 0:
            warm_cache()
            click.echo('Cache warmed.')
        else:
            click.echo('No data to warm cache with.')

    @app.cli.command('start-bot')
    def start_bot_cmd():
        """Start Telegram bot scheduler and polling (dev mode)."""
        has_token = bool(app.config.get('TELEGRAM_BOT_TOKEN'))
        if not has_token:
            click.echo('TELEGRAM_BOT_TOKEN not set — bot disabled.')
            return

        from app.telegram.scheduler import init_scheduler
        init_scheduler(app)
        click.echo('Telegram scheduler started.')

        is_dev = os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('TELEGRAM_POLLING')
        if is_dev:
            from app.telegram.polling import start_polling
            start_polling(app)
            click.echo('Telegram polling started.')

    @app.cli.command('start-email-scheduler')
    def start_email_scheduler_cmd():
        """Run the dedicated scheduler process: Telegram notifications + email
        re-engagement. The `scheduler` container runs this — it is the SINGLE,
        stable home for the Telegram scheduler (off the volatile gunicorn
        workers), so a second scheduler can't appear and users never get
        duplicate notifications. Blocks until SIGTERM so the daemon threads keep
        running in the container.
        """
        if app.config.get('TELEGRAM_BOT_TOKEN'):
            # Non-blocking BackgroundScheduler thread; the email scheduler below
            # blocks the main thread and keeps the process (and this thread) alive.
            from app.telegram.scheduler import init_scheduler
            init_scheduler(app)
            click.echo('Telegram scheduler started.')
        from app.email_scheduler import init_email_scheduler
        click.echo('Email scheduler started; waiting for jobs (SIGTERM to stop).')
        init_email_scheduler(app, blocking=True)

    @app.cli.command('backfill-achievements')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='Compute grants without committing to DB')
    def backfill_achievements_cmd(dry_run):
        """Backfill achievements for all existing users. Safe to run multiple times."""
        from app.utils.db import db
        from scripts.backfill_achievements import run_backfill
        mode = 'dry-run' if dry_run else 'live'
        click.echo(f'Achievement backfill starting ({mode}) ...')
        report = run_backfill(db.session, dry_run=dry_run, verbose=True)
        if dry_run:
            db.session.rollback()
        click.echo(f'\nDone.')
        click.echo(f'  Users processed : {report.total_users}')
        click.echo(f'  Users affected  : {report.users_affected}')
        click.echo(f'  Achievements    : {report.total_newly_granted}')
        if report.errors:
            click.echo(f'\n  Errors ({len(report.errors)}):')
            for e in report.errors:
                click.echo(f'    - {e}')

    @app.cli.command('purge-audio-grammar-exercises')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='Report what would be deleted without committing')
    def purge_audio_grammar_exercises_cmd(dry_run):
        """Delete grammar_lab exercises that were mis-imported from module
        ``listening_choice`` items (audio playback unsupported in grammar_lab
        UI). Heuristic: ``source='module_import'`` AND content has both
        non-empty ``options`` AND the question is a known listening prompt
        ('Что означает эта фраза?', 'Что вы услышали?', 'Прослушайте...').
        Idempotent; safe to re-run.
        """
        from app.grammar_lab.models import GrammarExercise, UserGrammarExercise
        from app.utils.db import db

        AUDIO_HINTS = (
            'что означает эта фраза',
            'что вы услышали',
            'прослушайте',
            'послушайте',
        )

        # Type-agnostic scan: a re-import may have produced rows of any
        # exercise_type (translation/multiple_choice/etc.) carrying the
        # same audio-only prompt. Heuristic: source=module_import AND
        # question matches a listening prompt. Options non-empty is no
        # longer required — translation-typed audio leftovers have no
        # options but still need cleanup.
        rows = db.session.query(GrammarExercise).all()
        candidates = []
        for ex in rows:
            content = ex.content if isinstance(ex.content, dict) else {}
            if content.get('source') != 'module_import':
                continue
            question = (content.get('question') or '').lower().strip()
            if not any(h in question for h in AUDIO_HINTS):
                continue
            candidates.append(ex)

        click.echo(f'Found {len(candidates)} audio-misimported grammar exercises.')
        if dry_run:
            for ex in candidates[:20]:
                content = ex.content if isinstance(ex.content, dict) else {}
                click.echo(f'  id={ex.id} topic={ex.topic_id} q="{content.get("question", "")[:60]}"')
            click.echo(f'(showing up to 20; dry-run, nothing deleted)')
            return

        # Cascade also drops user progress on these exercises (FK ON DELETE CASCADE).
        ids = [ex.id for ex in candidates]
        if ids:
            from app.utils.db_utils import chunk_ids
            deleted = 0
            for chunk in chunk_ids(ids, 500):
                q = db.session.query(GrammarExercise).filter(GrammarExercise.id.in_(chunk))
                deleted += q.delete(synchronize_session=False)
            db.session.commit()
            click.echo(f'Deleted {deleted} exercises.')
        else:
            click.echo('Nothing to delete.')

    @app.cli.command('reconcile-lesson-progress')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='Scan and report without writing flips to DB')
    def reconcile_lesson_progress_cmd(dry_run):
        """Flip stuck LessonProgress rows to 'completed' when an attempt
        passed or score already meets the lesson's threshold. Idempotent.
        """
        from app.curriculum.recovery import reconcile_stuck_lesson_progress
        from app.utils.db import db
        mode = 'dry-run' if dry_run else 'live'
        click.echo(f'Reconcile stuck lesson_progress starting ({mode}) ...')
        report = reconcile_stuck_lesson_progress(db.session, dry_run=dry_run)
        click.echo(f'\nDone.')
        click.echo(f'  Scanned          : {report.scanned}')
        click.echo(f'  Flipped          : {report.flipped}')
        click.echo(f'    by attempt     : {report.flipped_by_attempt}')
        click.echo(f'    by score       : {report.flipped_by_score}')
        click.echo(f'    by data perfect: {report.flipped_by_data_perfect}')
        if report.errors:
            click.echo(f'\n  Errors ({len(report.errors)}):')
            for e in report.errors:
                click.echo(f'    - {e}')

    from app.cli.content_commands import register_content_commands
    register_content_commands(app)
