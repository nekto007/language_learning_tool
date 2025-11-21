# app/admin/routes/__init__.py

"""
Admin routes package
Contains modularized route blueprints for the admin panel

Note: During refactoring, we need to re-export the 'admin' blueprint from the parent
routes.py file because app/admin/__init__.py expects to import it from 'app.admin.routes'.
Python finds this package directory before the routes.py file.
"""

# We cannot directly import from ..routes because that would be a circular reference
# to this package itself. Instead, we need to import from the parent module's routes.py file.
# Since routes.py is at app/admin/routes.py and we're in app/admin/routes/__init__.py,
# we actually want to import from app.admin's routes.py, not from this package.

# The simplest solution: temporarily change the import in app/admin/__init__.py
# For now, just export the new blueprints
from app.admin.routes.book_routes import book_bp
from app.admin.routes.curriculum_routes import curriculum_bp
from app.admin.routes.word_routes import word_bp
from app.admin.routes.audio_routes import audio_bp
from app.admin.routes.topic_routes import topic_bp
from app.admin.routes.collection_routes import collection_bp
from app.admin.routes.user_routes import user_bp
from app.admin.routes.system_routes import system_bp

__all__ = ['book_bp', 'curriculum_bp', 'word_bp', 'audio_bp', 'topic_bp', 'collection_bp', 'user_bp', 'system_bp']
