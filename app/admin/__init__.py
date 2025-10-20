# app/admin/__init__.py

"""
Admin module initialization
Handles blueprint registration and avoids circular imports
"""


def register_admin_routes(app):
    """Register all admin routes with the Flask app"""

    # Import the main admin blueprint (this creates the blueprint object)
    from app.admin.routes import admin

    # Import and register book course routes BEFORE registering the blueprint
    from app.admin.book_courses import register_book_course_routes
    register_book_course_routes(admin)

    # Import and register module management routes
    from app.admin.modules import register_module_admin_routes
    register_module_admin_routes(admin)

    # Now register the complete blueprint with all routes
    app.register_blueprint(admin)
