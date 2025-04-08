from datetime import datetime

from app.auth.models import User
from app.utils.db import db


def init_db(app):
    """Initialize database and optimize for SQLite."""
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()

        # Enable foreign key constraints for SQLite
        db.session.execute("PRAGMA foreign_keys = ON")

        # Enable WAL (Write-Ahead Logging) mode for better performance
        db.session.execute("PRAGMA journal_mode = WAL")

        # Set synchronous mode to normal for better performance
        db.session.execute("PRAGMA synchronous = NORMAL")

        # Create admin user if no users exist
        if User.query.count() == 0:
            admin_user = User(username="admin", email="admin@example.com")
            admin_user.set_password("password")
            admin_user.created_at = datetime.utcnow()
            db.session.add(admin_user)
            db.session.commit()

        # Create indexes that might not be auto-created by SQLAlchemy
        db.session.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status_user ON user_word_status (user_id)")
        db.session.execute("CREATE INDEX IF NOT EXISTS idx_user_word_status_word ON user_word_status (word_id)")
        db.session.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_book ON word_book_link (book_id)")
        db.session.execute("CREATE INDEX IF NOT EXISTS idx_word_book_link_word ON word_book_link (word_id)")

        db.session.commit()


def optimize_db():
    """Run periodically to optimize the SQLite database."""
    # Vacuum database to reclaim space and defragment
    db.session.execute("VACUUM")

    # Analyze tables for query optimization
    db.session.execute("ANALYZE")

    db.session.commit()
