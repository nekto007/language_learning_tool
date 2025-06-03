import os

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.utils.db import db
from app.utils.db_init import init_db, optimize_db
from app.utils.i18n import init_babel
from config.settings import Config

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

csrf = CSRFProtect()

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    csrf.init_app(app)
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    init_babel(app)

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

    from app.admin.routes import admin as admin_blueprint
    app.register_blueprint(admin_blueprint)

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

    app.jinja_env.globals.update(enumerate=enumerate)
    app.jinja_env.globals.update(chr=chr)

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

    # Create database tables and configure PostgreSQL
    with app.app_context():
        try:
            # Create tables
            db.create_all()

            # Set up database specific configurations
            if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']:
                # PostgreSQL specific optimizations
                from sqlalchemy import text
                db.session.execute(text("SET synchronous_commit = OFF"))  # Improves performance, slightly less durable
                db.session.execute(text("SET statement_timeout = '30s'"))  # Prevents long-running queries
                db.session.execute(text("SET idle_in_transaction_session_timeout = '60s'"))  # Prevents idle transactions

                # Enable connection pooling
                db.engine.pool_size = 10
                db.engine.max_overflow = 20

                app.logger.info("PostgreSQL optimizations enabled")

        except Exception as e:
            app.logger.error(f"Error initializing database: {e}")

    return app
