from datetime import datetime

from app.auth.models import User
from app.utils.db import db


def init_db(app):
    """
    DEPRECATED: Legacy database initialization function

    ARCHITECTURE CHANGES:
    - db.create_all() removed - use Alembic migrations: flask db upgrade
    - PRAGMA statements removed - now applied via SQLAlchemy events in db_config.py
    - Indexes should be created via Alembic migrations

    This function is kept for backward compatibility but does minimal work.
    Most initialization is now handled properly through migrations and event listeners.

    Use this function only if you need to create indexes on existing databases
    that don't have migrations.
    """
    with app.app_context():
        from app.utils.db_config import get_database_type

        database_type = get_database_type(app)

        # ARCHITECTURE FIX: db.create_all() removed
        # Schema management should be done through Alembic migrations only
        # If you need to create tables: flask db upgrade

        # ARCHITECTURE FIX: PRAGMA statements removed
        # SQLite/PostgreSQL optimizations are now applied via SQLAlchemy event listeners
        # See app/utils/db_config.py for implementation

        # SECURITY: Admin user creation removed
        # Use the create_admin.py CLI script to create the first admin user

        # Create indexes for legacy databases (if not using migrations)
        # These should ideally be in an Alembic migration
        try:
            db.session.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status_user ON user_word_status (user_id)")
            db.session.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status_word ON user_word_status (word_id)")
            db.session.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_book ON word_book_link (book_id)")
            db.session.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_word ON word_book_link (word_id)")
            db.session.commit()
        except Exception as e:
            # Indexes may already exist or tables may not exist yet
            db.session.rollback()
            app.logger.warning(f"Could not create indexes (this is normal if using migrations): {e}")


def optimize_db():
    """Run periodically to optimize the SQLite database."""
    # Vacuum database to reclaim space and defragment
    db.session.execute("VACUUM")

    # Analyze tables for query optimization
    db.session.execute("ANALYZE")

    db.session.commit()
