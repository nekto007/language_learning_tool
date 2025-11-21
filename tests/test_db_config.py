"""
Tests for database configuration utilities
Тесты утилит конфигурации базы данных
"""
import pytest
from unittest.mock import patch, MagicMock, call, Mock
from app.utils.db_config import (
    configure_database_engine,
    configure_postgresql,
    configure_sqlite,
    get_database_type
)


class TestGetDatabaseType:
    """Тесты определения типа базы данных"""

    def test_get_database_type_postgresql(self, app):
        """Тест определения PostgreSQL"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://localhost/testdb'
        result = get_database_type(app)
        assert result == 'postgresql'

    def test_get_database_type_sqlite(self, app):
        """Тест определения SQLite"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
        result = get_database_type(app)
        assert result == 'sqlite'

    def test_get_database_type_mysql(self, app):
        """Тест определения MySQL"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://localhost/testdb'
        result = get_database_type(app)
        assert result == 'mysql'

    def test_get_database_type_unknown(self, app):
        """Тест определения неизвестного типа БД"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'mongodb://localhost/testdb'
        result = get_database_type(app)
        assert result == 'unknown'

    def test_get_database_type_empty_uri(self, app):
        """Тест когда URI пустой"""
        app.config['SQLALCHEMY_DATABASE_URI'] = ''
        result = get_database_type(app)
        assert result == 'unknown'

    def test_get_database_type_missing_config(self, app):
        """Тест когда конфигурация отсутствует"""
        if 'SQLALCHEMY_DATABASE_URI' in app.config:
            del app.config['SQLALCHEMY_DATABASE_URI']
        result = get_database_type(app)
        assert result == 'unknown'


class TestConfigureDatabaseEngine:
    """Тесты главной функции конфигурации"""

    def test_configure_database_engine_postgresql(self, app):
        """Тест что PostgreSQL конфигурация вызывается"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://localhost/testdb'
        mock_db = MagicMock()

        with patch('app.utils.db_config.configure_postgresql') as mock_pg:
            configure_database_engine(app, mock_db)
            mock_pg.assert_called_once_with(app, mock_db)

    def test_configure_database_engine_sqlite(self, app):
        """Тест что SQLite конфигурация вызывается"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
        mock_db = MagicMock()

        with patch('app.utils.db_config.configure_sqlite') as mock_sqlite:
            configure_database_engine(app, mock_db)
            mock_sqlite.assert_called_once_with(app, mock_db)

    def test_configure_database_engine_unknown_does_not_crash(self, app):
        """Тест что неизвестная БД не вызывает ошибку"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'mongodb://localhost/testdb'
        mock_db = MagicMock()

        # Should not raise any exception
        configure_database_engine(app, mock_db)


class TestConfigurePostgresql:
    """Тесты конфигурации PostgreSQL"""

    def test_configure_postgresql_sets_up_event_listener(self, app):
        """Тест что настраивается event listener для PostgreSQL"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://localhost/testdb'
        mock_db = MagicMock()
        mock_engine = MagicMock()
        mock_db.engine = mock_engine

        with patch('app.utils.db_config.event.listens_for') as mock_listen:
            configure_postgresql(app, mock_db)

            # Verify event listener was set up
            mock_listen.assert_called()
            # First argument should be the engine
            assert mock_listen.call_args[0][0] == mock_engine

    def test_configure_postgresql_configures_pool(self, app):
        """Тест что настраивается connection pool"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://localhost/testdb'
        mock_db = MagicMock()
        mock_engine = MagicMock()
        mock_pool = MagicMock()
        mock_pool._pool = MagicMock()
        mock_engine.pool = mock_pool
        mock_db.engine = mock_engine

        with patch('app.utils.db_config.event.listens_for'):
            configure_postgresql(app, mock_db)

            # Verify pool was configured
            assert mock_pool._pool.maxsize == 10
            assert mock_pool._max_overflow == 20

class TestConfigureSqlite:
    """Тесты конфигурации SQLite"""

    def test_configure_sqlite_sets_up_event_listener(self, app):
        """Тест что настраивается event listener для SQLite"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
        mock_db = MagicMock()
        mock_engine = MagicMock()
        mock_db.engine = mock_engine

        with patch('app.utils.db_config.event.listens_for') as mock_listen:
            configure_sqlite(app, mock_db)

            # Verify event listener was set up
            mock_listen.assert_called()
            # First argument should be the engine
            assert mock_listen.call_args[0][0] == mock_engine

class TestIntegration:
    """Интеграционные тесты"""

    def test_full_postgresql_configuration_flow(self, app):
        """Тест полного потока конфигурации для PostgreSQL"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://localhost/testdb'
        mock_db = MagicMock()
        mock_engine = MagicMock()
        mock_pool = MagicMock()
        mock_pool._pool = MagicMock()
        mock_engine.pool = mock_pool
        mock_db.engine = mock_engine

        with patch('app.utils.db_config.event.listens_for'):
            configure_database_engine(app, mock_db)

            # Verify pool configuration
            assert mock_pool._pool.maxsize == 10
            assert mock_pool._max_overflow == 20

    def test_full_sqlite_configuration_flow(self, app):
        """Тест полного потока конфигурации для SQLite"""
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
        mock_db = MagicMock()
        mock_engine = MagicMock()
        mock_db.engine = mock_engine

        with patch('app.utils.db_config.event.listens_for') as mock_listen:
            configure_database_engine(app, mock_db)

            # Verify event listener was registered
            mock_listen.assert_called()
