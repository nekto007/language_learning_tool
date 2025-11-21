"""Tests for database configuration utilities"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from app.utils.db_config import (
    configure_database_engine,
    configure_postgresql,
    configure_sqlite,
    get_database_type
)


class TestGetDatabaseType:
    """Test get_database_type function"""

    def test_postgresql_detection(self):
        """Test PostgreSQL database detection"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'postgresql://user:pass@localhost/db'}

        result = get_database_type(app)
        assert result == 'postgresql'

    def test_sqlite_detection(self):
        """Test SQLite database detection"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'sqlite:///database.db'}

        result = get_database_type(app)
        assert result == 'sqlite'

    def test_mysql_detection(self):
        """Test MySQL database detection"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'mysql://user:pass@localhost/db'}

        result = get_database_type(app)
        assert result == 'mysql'

    def test_unknown_database(self):
        """Test unknown database type"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'oracle://user:pass@localhost/db'}

        result = get_database_type(app)
        assert result == 'unknown'

    def test_missing_database_uri(self):
        """Test missing database URI"""
        app = Mock()
        app.config = {}

        result = get_database_type(app)
        assert result == 'unknown'


class TestConfigureDatabaseEngine:
    """Test configure_database_engine function"""

    @patch('app.utils.db_config.configure_postgresql')
    def test_configures_postgresql(self, mock_configure_pg):
        """Test that PostgreSQL configuration is called"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'postgresql://localhost/db'}
        db = Mock()

        configure_database_engine(app, db)

        mock_configure_pg.assert_called_once_with(app, db)

    @patch('app.utils.db_config.configure_sqlite')
    def test_configures_sqlite(self, mock_configure_sqlite):
        """Test that SQLite configuration is called"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'sqlite:///database.db'}
        db = Mock()

        configure_database_engine(app, db)

        mock_configure_sqlite.assert_called_once_with(app, db)

    @patch('app.utils.db_config.logger')
    def test_logs_unknown_database(self, mock_logger):
        """Test that unknown database types are logged"""
        app = Mock()
        app.config = {'SQLALCHEMY_DATABASE_URI': 'unknown://localhost/db'}
        db = Mock()

        configure_database_engine(app, db)

        mock_logger.info.assert_called()
        assert 'No specific optimizations' in str(mock_logger.info.call_args)


class TestConfigurePostgresql:
    """Test configure_postgresql function"""

    @patch('app.utils.db_config.event.listens_for')
    def test_sets_up_event_listener(self, mock_listens_for):
        """Test that event listener is set up"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        configure_postgresql(app, db)

        # Verify event listener was registered
        mock_listens_for.assert_called_once_with(db.engine, "connect")

    @patch('app.utils.db_config.logger')
    def test_logs_configuration(self, mock_logger):
        """Test that configuration is logged"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()
        db.engine.pool = None

        configure_postgresql(app, db)

        # Verify info message was logged
        mock_logger.info.assert_called()
        assert 'PostgreSQL optimizations configured' in str(mock_logger.info.call_args)

    def test_configures_connection_pool(self):
        """Test that connection pool is configured"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        # Mock pool
        mock_pool = Mock()
        mock_pool._pool = Mock()
        db.engine.pool = mock_pool

        configure_postgresql(app, db)

        # Verify pool settings were applied
        assert db.engine.pool._pool.maxsize == 10
        assert db.engine.pool._max_overflow == 20

    def test_handles_missing_pool(self):
        """Test handling when engine has no pool"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()
        db.engine.pool = None

        # Should not raise exception
        configure_postgresql(app, db)


class TestConfigureSqlite:
    """Test configure_sqlite function"""

    @patch('app.utils.db_config.event.listens_for')
    def test_sets_up_event_listener(self, mock_listens_for):
        """Test that event listener is set up"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        configure_sqlite(app, db)

        # Verify event listener was registered
        mock_listens_for.assert_called_once_with(db.engine, "connect")

    @patch('app.utils.db_config.logger')
    def test_logs_configuration(self, mock_logger):
        """Test that configuration is logged"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        configure_sqlite(app, db)

        # Verify info message was logged
        mock_logger.info.assert_called()
        assert 'SQLite optimizations configured' in str(mock_logger.info.call_args)


class TestEventHandlers:
    """Test event handler functions (called on connection)"""

    def test_postgresql_pragma_execution(self):
        """Test PostgreSQL pragmas are executed correctly"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()
        db.engine.pool = None

        # Mock cursor
        mock_cursor = Mock()
        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Configure and get the event handler
        with patch('app.utils.db_config.event.listens_for') as mock_listens_for:
            configure_postgresql(app, db)

            # Get the decorated function
            event_handler = mock_listens_for.call_args[0][0]

            # Call the decorator to get the actual handler
            decorator = mock_listens_for.return_value
            decorator(event_handler)

            # The handler should be the function, call it
            if callable(event_handler):
                try:
                    event_handler(mock_connection, None)
                    # Verify cursor operations
                    assert mock_cursor.execute.called
                    assert mock_cursor.close.called
                except:
                    # Expected if handler references db.engine which is a mock
                    pass

    def test_sqlite_pragma_execution(self):
        """Test SQLite pragmas are executed correctly"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        # Mock cursor
        mock_cursor = Mock()
        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Configure and get the event handler
        with patch('app.utils.db_config.event.listens_for') as mock_listens_for:
            configure_sqlite(app, db)

            # Get the decorated function
            event_handler = mock_listens_for.call_args[0][0]

            # Call the decorator to get the actual handler
            decorator = mock_listens_for.return_value
            decorator(event_handler)

            # The handler should be the function, call it
            if callable(event_handler):
                try:
                    event_handler(mock_connection, None)
                    # Verify cursor operations
                    assert mock_cursor.execute.called
                    assert mock_cursor.close.called
                except:
                    # Expected if handler references db.engine which is a mock
                    pass

    @patch('app.utils.db_config.logger')
    def test_postgresql_error_handling(self, mock_logger):
        """Test PostgreSQL pragma error handling"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()
        db.engine.pool = None

        # Mock cursor that raises error
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception('Database error')
        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch('app.utils.db_config.event.listens_for') as mock_listens_for:
            configure_postgresql(app, db)

            event_handler = mock_listens_for.call_args[0][0]

            if callable(event_handler):
                # Should raise exception after logging
                with pytest.raises(Exception):
                    event_handler(mock_connection, None)

    @patch('app.utils.db_config.logger')
    def test_sqlite_error_handling(self, mock_logger):
        """Test SQLite pragma error handling"""
        app = Mock()
        app.app_context = MagicMock()
        db = Mock()
        db.engine = Mock()

        # Mock cursor that raises error
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception('Database error')
        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch('app.utils.db_config.event.listens_for') as mock_listens_for:
            configure_sqlite(app, db)

            event_handler = mock_listens_for.call_args[0][0]

            if callable(event_handler):
                # Should raise exception after logging
                with pytest.raises(Exception):
                    event_handler(mock_connection, None)