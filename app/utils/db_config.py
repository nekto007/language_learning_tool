"""
Database configuration and optimization via SQLAlchemy events

ARCHITECTURE: Database-specific optimizations are applied via event listeners
instead of being executed in create_app() factory. This ensures proper separation
of concerns and prevents race conditions.
"""
import logging
from sqlalchemy import event, text

logger = logging.getLogger(__name__)


def configure_database_engine(app, db):
    """
    Configure database engine with database-specific optimizations

    Uses SQLAlchemy event listeners to apply configuration when connections are established.
    This is the correct approach vs. executing in create_app().

    Args:
        app: Flask application instance
        db: SQLAlchemy database instance
    """
    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')

    if 'postgresql' in database_uri:
        configure_postgresql(app, db)
    elif 'sqlite' in database_uri:
        configure_sqlite(app, db)
    else:
        logger.info(f"No specific optimizations for database type: {database_uri}")


def configure_postgresql(app, db):
    """
    Configure PostgreSQL-specific optimizations via event listeners

    These settings are applied per-connection, not globally in create_app().
    """
    @event.listens_for(db.engine, "connect")
    def set_postgresql_pragmas(dbapi_conn, connection_record):
        """Set PostgreSQL session parameters on each connection"""
        cursor = dbapi_conn.cursor()

        try:
            # Improves write performance, slightly less durable
            # Good for development; reconsider for production
            cursor.execute("SET synchronous_commit = OFF")

            # Prevents long-running queries from blocking
            cursor.execute("SET statement_timeout = '30s'")

            # Prevents idle transactions from holding locks
            cursor.execute("SET idle_in_transaction_session_timeout = '60s'")

            cursor.close()
            logger.debug("PostgreSQL session parameters applied")

        except Exception as e:
            logger.error(f"Error setting PostgreSQL pragmas: {e}")
            cursor.close()
            raise

    # Configure connection pool
    if hasattr(db.engine, 'pool'):
        db.engine.pool._pool.maxsize = 10
        db.engine.pool._max_overflow = 20

    logger.info("PostgreSQL optimizations configured via event listeners")


def configure_sqlite(app, db):
    """
    Configure SQLite-specific optimizations via event listeners

    CRITICAL: These PRAGMA statements are SQLite-specific and will fail on PostgreSQL.
    That's why we check the database type first.
    """
    @event.listens_for(db.engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, connection_record):
        """Set SQLite PRAGMAs on each connection"""
        cursor = dbapi_conn.cursor()

        try:
            # CRITICAL: Enable foreign key constraints
            # SQLite disables them by default!
            cursor.execute("PRAGMA foreign_keys = ON")

            # Enable WAL (Write-Ahead Logging) for better concurrency
            cursor.execute("PRAGMA journal_mode = WAL")

            # Balance between safety and performance
            cursor.execute("PRAGMA synchronous = NORMAL")

            # Increase cache size for better read performance (10MB)
            cursor.execute("PRAGMA cache_size = -10000")

            cursor.close()
            logger.debug("SQLite PRAGMAs applied")

        except Exception as e:
            logger.error(f"Error setting SQLite pragmas: {e}")
            cursor.close()
            raise

    logger.info("SQLite optimizations configured via event listeners")


def get_database_type(app):
    """
    Determine the type of database from connection string

    Returns:
        str: 'postgresql', 'sqlite', 'mysql', or 'unknown'
    """
    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')

    if 'postgresql' in database_uri:
        return 'postgresql'
    elif 'sqlite' in database_uri:
        return 'sqlite'
    elif 'mysql' in database_uri:
        return 'mysql'
    else:
        return 'unknown'