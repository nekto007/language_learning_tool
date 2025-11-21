"""
Tests for Database Configuration Utilities (app/utils/db_config.py)

Tests database engine configuration and optimization:
- configure_database_engine - main configuration function
- configure_postgresql - PostgreSQL-specific settings
- configure_sqlite - SQLite-specific settings
- get_database_type - database type detection

Coverage target: 95%+ for app/utils/db_config.py
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from sqlalchemy import event


class TestGetDatabaseType:
    """Test get_database_type function"""

    def test_detects_postgresql(self, app):
        """Test detects PostgreSQL from URI"""
        from app.utils.db_config import get_database_type

        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:pass@localhost/db'

        result = get_database_type(app)

        assert result == 'postgresql'

    def test_detects_sqlite(self, app):
        """Test detects SQLite from URI"""
        from app.utils.db_config import get_database_type

        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'

        result = get_database_type(app)

        assert result == 'sqlite'

    def test_detects_mysql(self, app):
        """Test detects MySQL from URI"""
        from app.utils.db_config import get_database_type

        app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://user:pass@localhost/db'

        result = get_database_type(app)

        assert result == 'mysql'

    def test_returns_unknown_for_unknown_db(self, app):
        """Test returns 'unknown' for unrecognized database"""
        from app.utils.db_config import get_database_type

        app.config['SQLALCHEMY_DATABASE_URI'] = 'mongodb://localhost/db'

        result = get_database_type(app)

        assert result == 'unknown'

    def test_handles_empty_uri(self, app):
        """Test handles empty database URI"""
        from app.utils.db_config import get_database_type

        app.config['SQLALCHEMY_DATABASE_URI'] = ''

        result = get_database_type(app)

        assert result == 'unknown'

    def test_handles_missing_config(self, app):
        """Test handles missing SQLALCHEMY_DATABASE_URI"""
        from app.utils.db_config import get_database_type

        if 'SQLALCHEMY_DATABASE_URI' in app.config:
            del app.config['SQLALCHEMY_DATABASE_URI']

        result = get_database_type(app)

        assert result == 'unknown'


class TestConfigureDatabaseEngine:
    """Test configure_database_engine function"""

    def test_configures_postgresql_when_detected(self, app):
        """Test calls configure_postgresql for PostgreSQL URI"""
        from app.utils.db_config import configure_database_engine
        from app import db

        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:pass@localhost/db'

        with patch('app.utils.db_config.configure_postgresql') as mock_pg:
            configure_database_engine(app, db)

            mock_pg.assert_called_once_with(app, db)

    def test_configures_sqlite_when_detected(self, app):
        """Test calls configure_sqlite for SQLite URI"""
        from app.utils.db_config import configure_database_engine
        from app import db

        # Force SQLite URI
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'

        with patch('app.utils.db_config.configure_sqlite') as mock_sqlite:
            configure_database_engine(app, db)

            mock_sqlite.assert_called_once_with(app, db)

    def test_logs_info_for_unknown_database(self, app):
        """Test logs info message for unknown database type"""
        from app.utils.db_config import configure_database_engine
        from app import db

        app.config['SQLALCHEMY_DATABASE_URI'] = 'mongodb://localhost/db'

        with patch('app.utils.db_config.logger') as mock_logger:
            configure_database_engine(app, db)

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert 'No specific optimizations' in call_args


class TestConfigurePostgresql:
    """Test configure_postgresql function"""

    def test_configures_postgresql_without_errors(self, app):
        """Test configure_postgresql runs without errors"""
        from app.utils.db_config import configure_postgresql
        from app import db

        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:pass@localhost/db'

        with patch('app.utils.db_config.logger'):
            # Should not raise exception
            configure_postgresql(app, db)


class TestConfigureSqlite:
    """Test configure_sqlite function"""

    def test_configures_sqlite_without_errors(self, app):
        """Test configure_sqlite runs without errors"""
        from app.utils.db_config import configure_sqlite
        from app import db

        # Should not raise exception
        with patch('app.utils.db_config.logger'):
            configure_sqlite(app, db)
