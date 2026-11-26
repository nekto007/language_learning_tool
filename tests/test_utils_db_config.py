"""
Tests for Database Configuration Utilities (app/utils/db_config.py)

Tests database engine configuration and optimization:
- configure_database_engine - main configuration function
- configure_postgresql - PostgreSQL-specific settings
- configure_sqlite - SQLite-specific settings
- get_database_type - database type detection

Coverage target: 95%+ for app/utils/db_config.py
"""
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.pool import NullPool

from app.utils.db import db
from app.utils.db_config import configure_postgresql, configure_sqlite


@pytest.fixture
def configured_sqlite(app: Flask, tmp_path: Path) -> Iterator[Engine]:
    url = URL.create('sqlite', database=str(tmp_path / 'pragma.sqlite'))
    engine = create_engine(url, poolclass=NullPool)
    try:
        configure_sqlite(app, SimpleNamespace(engine=engine))
        yield engine
    finally:
        engine.dispose()


class TestGetDatabaseType:
    """Test get_database_type function"""

    def test_detects_postgresql(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test detects PostgreSQL from URI"""
        from app.utils.db_config import get_database_type

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'postgresql://user:pass@localhost/db')

        result = get_database_type(app)

        assert result == 'postgresql'

    def test_detects_sqlite(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test detects SQLite from URI"""
        from app.utils.db_config import get_database_type

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///test.db')

        result = get_database_type(app)

        assert result == 'sqlite'

    def test_detects_mysql(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test detects MySQL from URI"""
        from app.utils.db_config import get_database_type

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'mysql://user:pass@localhost/db')

        result = get_database_type(app)

        assert result == 'mysql'

    def test_returns_unknown_for_unknown_db(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test returns 'unknown' for unrecognized database"""
        from app.utils.db_config import get_database_type

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'mongodb://localhost/db')

        result = get_database_type(app)

        assert result == 'unknown'

    def test_handles_empty_uri(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test handles empty database URI"""
        from app.utils.db_config import get_database_type

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', '')

        result = get_database_type(app)

        assert result == 'unknown'

    def test_handles_missing_config(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test handles missing SQLALCHEMY_DATABASE_URI"""
        from app.utils.db_config import get_database_type

        monkeypatch.delitem(app.config, 'SQLALCHEMY_DATABASE_URI', raising=False)

        result = get_database_type(app)

        assert result == 'unknown'


class TestConfigureDatabaseEngine:
    """Test configure_database_engine function"""

    def test_configures_postgresql_when_detected(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test calls configure_postgresql for PostgreSQL URI"""
        from app.utils.db_config import configure_database_engine
        from app import db

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'postgresql://user:pass@localhost/db')

        with (patch('app.utils.db_config.configure_postgresql') as mock_pg,
              patch('app.utils.db_config.configure_slow_query_logging') as mock_slow_queries):
            configure_database_engine(app, db)

            mock_pg.assert_called_once_with(app, db)
            mock_slow_queries.assert_called_once_with(app, db)

    def test_configures_sqlite_when_detected(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test calls configure_sqlite for SQLite URI"""
        from app.utils.db_config import configure_database_engine
        from app import db

        # Force SQLite URI
        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///test.db')

        with (patch('app.utils.db_config.configure_sqlite') as mock_sqlite,
              patch('app.utils.db_config.configure_slow_query_logging') as mock_slow_queries):
            configure_database_engine(app, db)

            mock_sqlite.assert_called_once_with(app, db)
            mock_slow_queries.assert_called_once_with(app, db)

    def test_logs_info_for_unknown_database(self, app, monkeypatch: pytest.MonkeyPatch):
        """Test logs info message for unknown database type"""
        from app.utils.db_config import configure_database_engine
        from app import db

        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', 'mongodb://localhost/db')

        with (patch('app.utils.db_config.logger') as mock_logger,
              patch('app.utils.db_config.configure_slow_query_logging') as mock_slow_queries):
            configure_database_engine(app, db)

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert 'No specific optimizations' in call_args
            mock_slow_queries.assert_called_once_with(app, db)


class TestConfigurePostgresql:
    """Test configure_postgresql function"""

    def test_configures_postgresql_without_errors(self, app: Flask) -> None:
        """Verify settings on an engine owned by this test."""
        with app.app_context():
            url = db.engine.url
        if url.get_backend_name() != 'postgresql':
            pytest.skip('PostgreSQL connection settings require a PostgreSQL test database')
        engine = create_engine(url, poolclass=NullPool)
        try:
            configure_postgresql(app, SimpleNamespace(engine=engine))
            with engine.connect() as connection:
                assert connection.scalar(text('SHOW statement_timeout')) == '30s'
                assert connection.scalar(text('SHOW idle_in_transaction_session_timeout')) == '1min'
        finally:
            engine.dispose()


class TestConfigureSqlite:
    """Test configure_sqlite function"""

    def test_configures_sqlite_without_errors(self, configured_sqlite: Engine) -> None:
        """Open real connections and verify the PRAGMAs set by the listener."""
        for _ in range(2):
            with configured_sqlite.connect() as connection:
                assert connection.scalar(text('PRAGMA foreign_keys')) == 1
                assert connection.scalar(text('PRAGMA journal_mode')) == 'wal'
                assert connection.scalar(text('PRAGMA synchronous')) == 1
                assert connection.scalar(text('PRAGMA cache_size')) == -10000

    def test_sqlite_configuration_leaves_postgresql_reconnect_usable(
        self, app: Flask, configured_sqlite: Engine,
    ) -> None:
        """Exercise both dialects in order within the same worker."""
        with app.app_context():
            engine = db.engine
            if engine.dialect.name != 'postgresql':
                pytest.skip('Reconnecting the shared PostgreSQL engine requires a PostgreSQL test database')
            with configured_sqlite.connect() as sqlite_connection:
                assert sqlite_connection.scalar(text('PRAGMA foreign_keys')) == 1
            engine.dispose()
            with engine.connect() as first, engine.connect() as second:
                assert first.scalar(text('SELECT 1')) == second.scalar(text('SELECT 1')) == 1
                assert first.scalar(text('SELECT pg_backend_pid()')) != second.scalar(text('SELECT pg_backend_pid()'))
