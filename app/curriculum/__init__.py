# app/curriculum/__init__.py

# Import and use main blueprint directly for compatibility
from app.curriculum.routes import admin_bp, api_bp, lessons_bp, main_bp as curriculum_bp
from app.curriculum.routes.main import learn_bp


def init_curriculum_module(app):
    """Initialize curriculum module with all components"""

    # Unauthorized handler is now configured globally in __init__.py

    # Initialize middleware and monitoring
    from app.curriculum.middleware import init_curriculum_monitoring
    init_curriculum_monitoring(app)

    # Initialize caching
    from app.curriculum.cache import init_cache
    init_cache(app)

    # Initialize rate limiting
    from app.curriculum.rate_limiter import init_rate_limiting
    init_rate_limiting(app)

    # Initialize metrics collection
    from app.curriculum.metrics import init_metrics, setup_database_monitoring
    init_metrics(app)
    with app.app_context():
        setup_database_monitoring()

    # Initialize backup system
    from app.curriculum.backup import init_backup_system
    init_backup_system(app)

    # Register additional blueprints
    app.register_blueprint(lessons_bp, url_prefix='/curriculum')
    # Register curriculum admin blueprint
    app.register_blueprint(admin_bp, url_prefix='/curriculum')
    app.register_blueprint(api_bp, url_prefix='/curriculum')
    
    # Register learn blueprint with short lesson URLs
    app.register_blueprint(learn_bp, url_prefix='/learn')
    
    # Register book courses blueprint
    from app.curriculum.routes.book_courses import book_courses_bp
    app.register_blueprint(book_courses_bp, url_prefix='/curriculum')
    
    # Register SRS API blueprint
    from app.curriculum.routes.srs_api import srs_api_bp
    app.register_blueprint(srs_api_bp, url_prefix='/curriculum')

    # Register public course catalog blueprint
    from app.curriculum.routes.public import courses_bp
    app.register_blueprint(courses_bp, url_prefix='/courses')

    app.logger.info("Curriculum module initialized successfully")
