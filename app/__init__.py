import os

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate

from app.utils.db import db
from app.utils.db_init import init_db, optimize_db
from app.utils.i18n import init_babel
from app.utils.cache import init_cache
from app.utils.rate_limit_helpers import get_remote_address_key
from config.settings import Config

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

csrf = CSRFProtect()

# JWT Manager for API authentication
jwt = JWTManager()

# Initialize rate limiter with enhanced configuration
limiter = Limiter(
    key_func=get_remote_address_key,
    default_limits=["10000 per hour", "100 per second"],  # More generous limits
    storage_uri="memory://",
    # Customizable error messages
    headers_enabled=True,  # Enable X-RateLimit headers
    swallow_errors=False,  # Raise errors in development
    # Strategy for rate limit windows
    strategy="fixed-window"
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configure JWT
    from datetime import timedelta
    app.config['JWT_SECRET_KEY'] = app.config['SECRET_KEY']
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
    init_cache(app)

    # Import all models in dependency order - MUST happen before any blueprint that uses models
    from app.auth import models as auth_models
    from app.books import models as books_models
    from app.words import models as words_models  # Also defines word_book_link table
    from app.study import models as study_models
    from app.curriculum import models as curriculum_models
    from app.curriculum import book_courses as book_courses_models
    from app.curriculum import daily_lessons as daily_lessons_models
    from app.modules import models as modules_models
    from app.grammar_lab import models as grammar_models
    from app.reminders import models as reminders_models
    from app.telegram import models as telegram_models
    from app.achievements import models as achievements_models

    # Database initialization and seeding - MUST happen before any module that queries DB
    # Skip in testing mode - tests will handle their own data setup
    if not app.config.get('TESTING', False):
        with app.app_context():
            # Check if tables exist, create if not
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()

            if 'users' not in existing_tables:
                # Database is empty - create all tables
                print('🔧 Creating database tables...')
                db.create_all()
                print('✅ Database tables created successfully!')

            # Seed initial data for modules system
            from app.modules.migrations import seed_initial_modules
            seed_initial_modules()

            # Seed initial achievements
            from app.achievements.seed import seed_achievements
            seed_achievements()
    else:
        # Ensure tables exist when running in testing mode (SQLite, etc.)
        with app.app_context():
            db.create_all()

    # Initialize template utilities
    from app.utils.template_utils import init_template_utils
    init_template_utils(app)

    # Initialize security middleware
    from app.middleware.security import add_security_headers
    add_security_headers(app)

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

    from app.api.anki import api_anki as api_anki_blueprint
    app.register_blueprint(api_anki_blueprint, url_prefix='/api')

    from app.api.topics_collections import api_topics_collections
    app.register_blueprint(api_topics_collections, url_prefix='/api')

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

    # Register Telegram bot blueprint
    from app.telegram import telegram_bp
    app.register_blueprint(telegram_bp)

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
            return jsonify({'success': False, 'error': 'CSRF token missing or invalid'}), 400
        return e.description, 400

    @login_manager.user_loader
    def load_user(user_id):
        from app.auth.models import User
        return User.query.get(int(user_id))

    @app.before_request
    def update_last_active():
        """Update user's last_login every 12 hours on activity"""
        from flask_login import current_user
        from datetime import datetime, timezone, timedelta

        if current_user.is_authenticated:
            now = datetime.now(timezone.utc)
            # Update if last_login is None or older than 12 hours
            if current_user.last_login is None or \
               (now - current_user.last_login.replace(tzinfo=timezone.utc)) > timedelta(hours=12):
                current_user.last_login = now
                db.session.commit()

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

    # Start Telegram services (skip in tests)
    has_token = bool(app.config.get('TELEGRAM_BOT_TOKEN'))
    if not app.config.get('TESTING', False) and has_token:
        from app.telegram.scheduler import init_scheduler
        init_scheduler(app)

        # Dev mode: use polling instead of webhook
        # WERKZEUG_RUN_MAIN=true means we're in Flask reloader child (dev mode)
        is_dev = os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('TELEGRAM_POLLING')
        if is_dev:
            from app.telegram.polling import start_polling
            start_polling(app)
            print('🤖 Telegram polling started')
    elif not app.config.get('TESTING', False):
        print(f'🤖 Telegram bot disabled (token set: {has_token})')

    return app
