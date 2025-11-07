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
    setup_database_monitoring()

    # Initialize notification system
    from app.curriculum.notifications import init_notifications
    init_notifications(app)

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

    # Warm cache on startup - try to warm cache immediately
    try:
        from app.curriculum.cache import warm_cache
        # Don't warm cache if we don't have tables yet
        with app.app_context():
            from app.curriculum.models import CEFRLevel
            if CEFRLevel.query.count() > 0:
                warm_cache()
            else:
                app.logger.info("Skipping cache warming - no data in database yet")
    except Exception as e:
        app.logger.error(f"Error warming curriculum cache: {str(e)}")

    app.logger.info("Curriculum module initialized successfully")
