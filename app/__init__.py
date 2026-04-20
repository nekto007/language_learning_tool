import logging
import os

from flask import Flask
from flask_compress import Compress

logger = logging.getLogger(__name__)
from flask_limiter import Limiter

from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

from app.utils.db import db
from app.utils.i18n import init_babel
from app.utils.rate_limit_helpers import get_remote_address_key
from config.settings import Config

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
    'curriculum_admin.', 'reminders.',
    'refresh_csrf_token',
    'health_check',
)

csrf = CSRFProtect()

# JWT Manager for API authentication
jwt = JWTManager()

# Initialize rate limiter with enhanced configuration
limiter = Limiter(
    key_func=get_remote_address_key,
    default_limits=["10000 per hour", "100 per second"],  # More generous limits
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    # Customizable error messages
    headers_enabled=True,  # Enable X-RateLimit headers
    swallow_errors=not os.environ.get('FLASK_DEBUG', ''),  # Raise in debug, degrade gracefully in prod
    # Strategy for rate limit windows
    strategy="fixed-window"
)


def create_app(config_class=Config):
    from config.logging_config import configure_logging
    configure_logging()

    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get('TESTING'):
        from config.settings import validate_environment
        validate_environment()

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
    migrate = Migrate(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)
    jwt.init_app(app)
    init_babel(app)

    # Enable gzip compression for HTTP responses
    app.config.setdefault('COMPRESS_MIMETYPES', [
        'text/html', 'text/css', 'text/xml', 'text/javascript',
        'application/json', 'application/javascript',
    ])
    app.config.setdefault('COMPRESS_LEVEL', 6)
    app.config.setdefault('COMPRESS_MIN_SIZE', 500)
    Compress(app)

    # Import all models in dependency order - MUST happen before any blueprint that uses models
    from app.auth import models as auth_models  # noqa: F401
    from app.books import models as books_models  # noqa: F401
    from app.words import models as words_models  # noqa: F401  # Also defines word_book_link table
    from app.study import models as study_models  # noqa: F401
    from app.curriculum import models as curriculum_models  # noqa: F401
    from app.curriculum import book_courses as book_courses_models  # noqa: F401
    from app.curriculum import daily_lessons as daily_lessons_models  # noqa: F401
    from app.modules import models as modules_models  # noqa: F401
    from app.grammar_lab import models as grammar_models  # noqa: F401
    from app.reminders import models as reminders_models  # noqa: F401
    from app.telegram import models as telegram_models  # noqa: F401
    from app.achievements import models as achievements_models  # noqa: F401
    from app.achievements import daily_race as achievements_daily_race  # noqa: F401
    from app.notifications import models as notifications_models  # noqa: F401
    from app.admin import audit as admin_audit  # noqa: F401
    from app.daily_plan import models as daily_plan_models  # noqa: F401
    from app.daily_plan.linear import models as daily_plan_linear_models  # noqa: F401

    # In production, schema is managed by Alembic (`flask db upgrade head`).
    # In testing, create tables directly so tests don't need migrations.
    if app.config.get('TESTING', False):
        with app.app_context():
            db.create_all()

    # Initialize template utilities
    from app.utils.template_utils import init_template_utils
    init_template_utils(app)

    # Initialize security middleware
    from app.middleware.security import add_security_headers
    add_security_headers(app)

    # Initialize request ID middleware
    from app.middleware.request_id import add_request_id
    add_request_id(app)

    # Ensure directories exist
    os.makedirs(app.config['AUDIO_UPLOAD_FOLDER'], exist_ok=True)

    # Register blueprints
    # Landing page (public, must be first for root route)
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

    # Initialize curriculum module with all components
    init_curriculum_module(app)

    # Register modules blueprint
    from app.modules import modules_bp
    app.register_blueprint(modules_bp)

    # Register Grammar Lab blueprint
    from app.grammar_lab import grammar_lab_bp
    app.register_blueprint(grammar_lab_bp)

    # Register Onboarding blueprint
    from app.onboarding import onboarding_bp
    app.register_blueprint(onboarding_bp)

    # Register SEO blueprint (sitemap.xml, robots.txt)
    from app.seo import seo_bp
    app.register_blueprint(seo_bp)

    # Register Legal blueprint (privacy policy)
    from app.legal import legal_bp
    app.register_blueprint(legal_bp)

    # Register Daily Race blueprint (/race page)
    from app.race import race_bp
    app.register_blueprint(race_bp)

    # Register Telegram bot blueprint
    from app.telegram import telegram_bp
    app.register_blueprint(telegram_bp)

    # Register notifications blueprint
    from app.notifications import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')

    # Register uploads blueprint for secure file serving
    from app.uploads.routes import uploads as uploads_blueprint
    app.register_blueprint(uploads_blueprint, url_prefix='/uploads')

    # Add module utilities to Jinja globals
    from app.modules.service import ModuleService

    def has_module(module_code):
        """Check if current user has access to a module"""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return False
        return ModuleService.is_module_enabled_for_user(current_user.id, module_code)

    def get_user_modules():
        """Get all enabled modules for current user"""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return []
        return ModuleService.get_user_modules(current_user.id, enabled_only=True)

    app.jinja_env.globals.update(enumerate=enumerate)
    app.jinja_env.globals.update(chr=chr)
    app.jinja_env.globals.update(has_module=has_module)
    app.jinja_env.globals.update(get_user_modules=get_user_modules)

    # CSRF token refresh endpoint (for long-lived pages like quizzes)
    from flask_login import login_required as _login_required
    from flask import jsonify as _jsonify

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
        from flask import request, jsonify
        # Return JSON for AJAX requests and API endpoints
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        is_api = request.path.startswith('/api/')
        accepts_json = 'application/json' in request.headers.get('Accept', '')

        if is_ajax or is_api or accepts_json:
            return jsonify({'success': False, 'error': 'CSRF token expired. Please refresh the page.', 'csrf_expired': True}), 400
        return e.description, 400

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
        if _wants_json():
            return jsonify({'success': False, 'error': 'Forbidden'}), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def handle_404_error(e):
        from flask import jsonify, render_template
        if _wants_json():
            return jsonify({'success': False, 'error': 'Not found'}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def handle_500_error(e):
        from flask import jsonify, render_template
        from app.admin.main_routes import increment_5xx_counter
        try:
            db.session.rollback()
        except Exception:
            logger.exception("Failed to rollback session in 500 handler")
        increment_5xx_counter()
        if _wants_json():
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
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
    def update_last_active():
        """Update user's last_login every 12 hours on activity"""
        from flask import redirect, request, url_for
        from flask_login import current_user
        from datetime import datetime, timezone, timedelta

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
        from flask import request, url_for, redirect, jsonify

        # For AJAX requests, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Authentication required'}), 401

        # For regular requests, redirect to login with next parameter
        return redirect(url_for('auth.login', next=request.url))

    # Set up database-specific optimizations via SQLAlchemy events
    from app.utils.db_config import configure_database_engine
    configure_database_engine(app, db)

    # Register CLI commands for startup jobs (seed, warm-cache, start-bot, start-email-scheduler)
    _register_cli_commands(app)

    return app


def _register_cli_commands(app):
    """Register CLI commands for operations previously done as side effects in create_app()."""
    import click

    @app.cli.command('seed')
    def seed_cmd():
        """Seed initial data (modules and achievements). Safe to run multiple times."""
        from app.modules.migrations import seed_initial_modules
        from app.achievements.seed import seed_achievements
        seed_initial_modules()
        seed_achievements()
        click.echo('Seeding complete.')

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
        """Start the email re-engagement scheduler."""
        from app.email_scheduler import init_email_scheduler
        init_email_scheduler(app)
        click.echo('Email scheduler started.')

    from app.cli.linear_plan_commands import register_linear_plan_commands
    register_linear_plan_commands(app)
