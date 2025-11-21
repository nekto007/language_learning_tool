"""
Tests for database initialization utilities
Тесты утилит инициализации базы данных
"""
import pytest
from unittest.mock import patch, MagicMock, call
from app.utils.db_init import init_db, optimize_db


class TestInitDb:
    """Тесты функции init_db"""

    def test_init_db_creates_indexes_successfully(self, app, db_session):
        """Тест успешного создания индексов"""
        with app.app_context():
            # Mock execute and commit to track calls
            with patch.object(db_session, 'execute') as mock_execute, \
                 patch.object(db_session, 'commit') as mock_commit:

                init_db(app)

                # Verify all 4 index creation statements were executed
                assert mock_execute.call_count == 4

                # Verify the specific index creation calls
                expected_calls = [
                    call("CREATE INDEX IF NOT EXISTS idx_user_word_status_user ON user_word_status (user_id)"),
                    call("CREATE INDEX IF NOT EXISTS idx_user_word_status_word ON user_word_status (word_id)"),
                    call("CREATE INDEX IF NOT EXISTS idx_word_book_link_book ON word_book_link (book_id)"),
                    call("CREATE INDEX IF NOT EXISTS idx_word_book_link_word ON word_book_link (word_id)")
                ]
                mock_execute.assert_has_calls(expected_calls, any_order=False)

                # Verify commit was called once
                mock_commit.assert_called_once()

    def test_init_db_handles_index_creation_exception(self, app, db_session, caplog):
        """Тест обработки исключения при создании индексов"""
        with app.app_context():
            # Mock execute to raise an exception
            with patch.object(db_session, 'execute') as mock_execute, \
                 patch.object(db_session, 'rollback') as mock_rollback:

                mock_execute.side_effect = Exception("Table does not exist")

                # Should not raise exception, but log warning
                init_db(app)

                # Verify rollback was called
                mock_rollback.assert_called_once()

                # Verify warning was logged
                assert any("Could not create indexes" in record.message for record in caplog.records)

    def test_init_db_gets_database_type(self, app, db_session):
        """Тест что init_db получает тип базы данных"""
        with app.app_context():
            with patch('app.utils.db_config.get_database_type') as mock_get_db_type, \
                 patch.object(db_session, 'execute'), \
                 patch.object(db_session, 'commit'):

                mock_get_db_type.return_value = 'sqlite'

                init_db(app)

                # Verify get_database_type was called with app
                mock_get_db_type.assert_called_once_with(app)

    def test_init_db_index_already_exists_exception(self, app, db_session):
        """Тест что init_db обрабатывает ситуацию когда индексы уже существуют"""
        with app.app_context():
            with patch.object(db_session, 'execute') as mock_execute, \
                 patch.object(db_session, 'rollback') as mock_rollback:

                # Simulate index already exists error
                mock_execute.side_effect = Exception("index already exists")

                # Should not raise, should handle gracefully
                init_db(app)

                # Verify rollback was called
                mock_rollback.assert_called_once()


class TestOptimizeDb:
    """Тесты функции optimize_db"""

    def test_optimize_db_runs_vacuum_and_analyze(self, db_session):
        """Тест что optimize_db выполняет VACUUM и ANALYZE"""
        with patch.object(db_session, 'execute') as mock_execute, \
             patch.object(db_session, 'commit') as mock_commit:

            optimize_db()

            # Verify VACUUM and ANALYZE were executed
            assert mock_execute.call_count == 2
            expected_calls = [
                call("VACUUM"),
                call("ANALYZE")
            ]
            mock_execute.assert_has_calls(expected_calls, any_order=False)

            # Verify commit was called
            mock_commit.assert_called_once()

    def test_optimize_db_commits_changes(self, db_session):
        """Тест что optimize_db коммитит изменения"""
        with patch.object(db_session, 'execute'), \
             patch.object(db_session, 'commit') as mock_commit:

            optimize_db()

            # Verify commit was called exactly once
            mock_commit.assert_called_once()

    def test_optimize_db_executes_in_correct_order(self, db_session):
        """Тест что VACUUM выполняется перед ANALYZE"""
        with patch.object(db_session, 'execute') as mock_execute, \
             patch.object(db_session, 'commit'):

            optimize_db()

            # Get the calls in order
            calls = mock_execute.call_args_list

            # Verify VACUUM is first, ANALYZE is second
            assert str(calls[0]) == "call('VACUUM')"
            assert str(calls[1]) == "call('ANALYZE')"


class TestDatabaseInitIntegration:
    """Интеграционные тесты"""

    def test_init_db_works_with_app_context(self, app):
        """Тест что init_db работает в контексте приложения"""
        with patch('app.utils.db_init.db.session') as mock_session:
            mock_session.execute = MagicMock()
            mock_session.commit = MagicMock()

            # Should not raise any exceptions
            init_db(app)

            # Verify session was used
            assert mock_session.execute.called
            assert mock_session.commit.called

    def test_optimize_db_can_be_called_standalone(self):
        """Тест что optimize_db может быть вызвана без контекста приложения"""
        with patch('app.utils.db_init.db.session') as mock_session:
            mock_session.execute = MagicMock()
            mock_session.commit = MagicMock()

            # Should work without app context
            optimize_db()

            # Verify it executed the optimization commands
            assert mock_session.execute.call_count == 2
            assert mock_session.commit.called
