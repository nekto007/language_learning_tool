# app/admin/__init__.py

"""
Admin module initialization
Handles blueprint registration and avoids circular imports
"""


def register_admin_routes(flask_app):
    """Register all admin routes with the Flask app"""

    # Import the main admin blueprint (this creates the blueprint object)
    # Note: Renamed from routes.py to main_routes.py to avoid conflict with routes/ package
    from app.admin.main_routes import admin

    # Import and register book course routes BEFORE registering the blueprint
    from app.admin.book_courses import register_book_course_routes
    register_book_course_routes(admin)

    # Import and register module management routes
    from app.admin.modules import register_module_admin_routes
    register_module_admin_routes(admin)

    # Import quiz decks routes (they are already added via @admin.route decorators)
    import app.admin.quiz_decks

    # Import and register book routes blueprint
    from app.admin.routes.book_routes import book_bp
    flask_app.register_blueprint(book_bp, url_prefix='/admin')

    # Import and register curriculum routes blueprint
    from app.admin.routes.curriculum_routes import curriculum_bp
    flask_app.register_blueprint(curriculum_bp, url_prefix='/admin')

    # Import and register word routes blueprint
    from app.admin.routes.word_routes import word_bp
    flask_app.register_blueprint(word_bp, url_prefix='/admin')

    # Import and register audio routes blueprint
    from app.admin.routes.audio_routes import audio_bp
    flask_app.register_blueprint(audio_bp, url_prefix='/admin')

    # Import and register topic routes blueprint
    from app.admin.routes.topic_routes import topic_bp
    flask_app.register_blueprint(topic_bp, url_prefix='/admin')

    # Import and register collection routes blueprint
    from app.admin.routes.collection_routes import collection_bp
    flask_app.register_blueprint(collection_bp, url_prefix='/admin')

    # Import and register user routes blueprint
    from app.admin.routes.user_routes import user_bp
    flask_app.register_blueprint(user_bp, url_prefix='/admin')

    # Import and register system routes blueprint
    from app.admin.routes.system_routes import system_bp
    flask_app.register_blueprint(system_bp, url_prefix='/admin')

    # Now register the complete blueprint with all routes
    flask_app.register_blueprint(admin)
