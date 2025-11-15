import os

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_jwt_extended import JWTManager

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
    default_limits=["1000 per hour"],  # Global limit per IP
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
    login_manager.init_app(app)
    limiter.init_app(app)
    jwt.init_app(app)
    init_babel(app)
    init_cache(app)

    # Initialize template utilities
    from app.utils.template_utils import init_template_utils
    init_template_utils(app)

    # Initialize security middleware
    from app.middleware.security import add_security_headers
    add_security_headers(app)

    # Ensure directories exist
    os.makedirs(app.config['AUDIO_UPLOAD_FOLDER'], exist_ok=True)

    # Register blueprints
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

    from app.api.telegram import api_telegram as api_telegram_blueprint
    app.register_blueprint(api_telegram_blueprint, url_prefix='/api')

    from app.curriculum import curriculum_bp, init_curriculum_module
    app.register_blueprint(curriculum_bp, url_prefix='/curriculum')

    # Initialize curriculum module with all components
    init_curriculum_module(app)

    # Register modules blueprint
    from app.modules import modules_bp
    app.register_blueprint(modules_bp, url_prefix='/modules')

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
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'CSRF token missing or invalid'}), 400
        return e.description, 400

    @login_manager.user_loader
    def load_user(user_id):
        from app.auth.models import User
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        """Custom unauthorized handler that preserves the original URL"""
        from flask import request, url_for, redirect, jsonify

        # For AJAX requests, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Authentication required'}), 401

        # For regular requests, redirect to login with next parameter
        return redirect(url_for('auth.login', next=request.url))

    # Create database tables if they don't exist
    # Safe operation - only creates missing tables, never drops or modifies existing ones
    with app.app_context():
        db.create_all()

    # Set up database-specific optimizations via SQLAlchemy events
    from app.utils.db_config import configure_database_engine
    configure_database_engine(app, db)

    return app
