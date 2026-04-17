"""
Database configuration and optimization via SQLAlchemy events

ARCHITECTURE: Database-specific optimizations are applied via event listeners
instead of being executed in create_app() factory. This ensures proper separation
of concerns and prevents race conditions.
"""
import logging
import os
import time
from sqlalchemy import event

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

    configure_slow_query_logging(app, db)


def configure_postgresql(app, db):
    """
    Configure PostgreSQL-specific optimizations via event listeners

    These settings are applied per-connection, not globally in create_app().
    """
    # Access engine within app context to ensure it's been created
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def set_postgresql_pragmas(dbapi_conn, connection_record):
            """Set PostgreSQL session parameters on each connection"""
            cursor = dbapi_conn.cursor()

            try:
                # Only disable synchronous_commit in development (explicit opt-in)
                if os.environ.get('FLASK_ENV') == 'development':
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

        logger.info("PostgreSQL optimizations configured via event listeners")


def configure_sqlite(app, db):
    """
    Configure SQLite-specific optimizations via event listeners

    CRITICAL: These PRAGMA statements are SQLite-specific and will fail on PostgreSQL.
    That's why we check the database type first.
    """
    # Access engine within app context to ensure it's been created
    with app.app_context():
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


def configure_slow_query_logging(app, db):
    """
    Register before/after_cursor_execute listeners to log slow SQL queries.

    Queries that exceed SLOW_QUERY_MS (default 100ms) are logged at WARNING level
    with the elapsed time and the first 200 characters of the statement.

    Args:
        app: Flask application instance
        db: SQLAlchemy database instance
    """
    threshold_ms: int = app.config.get('SLOW_QUERY_MS', 100)

    with app.app_context():
        @event.listens_for(db.engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault("query_start_time", []).append(time.time())

        @event.listens_for(db.engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            times = conn.info.get("query_start_time", [])
            if not times:
                return
            elapsed = time.time() - times.pop(-1)
            if elapsed * 1000 > threshold_ms:
                logger.warning(
                    "slow_query elapsed_ms=%.1f statement=%s",
                    elapsed * 1000,
                    statement[:200],
                )

    logger.debug("Slow query logging configured (threshold=%dms)", threshold_ms)


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