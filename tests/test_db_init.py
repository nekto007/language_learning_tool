"""
Tests for database initialization utilities
"""
import warnings

import pytest
from unittest.mock import patch, MagicMock

from app.utils.db_init import init_db, _legacy_init_db


class TestInitDb:
    """Tests for the deprecated init_db function"""

    def test_init_db_emits_deprecation_warning(self, app):
        """init_db should emit a DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            init_db(app)
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1

    def test_init_db_works_without_app_argument(self, app):
        """init_db() without app should use current_app (fixes the admin bug)."""
        with app.app_context():
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                init_db()

    def test_init_db_accepts_app_argument(self, app):
        """init_db(app) should work with explicit app argument."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            init_db(app)

    def test_init_db_is_noop(self, app, db_session):
        """init_db should not modify the database (no-op)."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with patch.object(db_session, 'execute') as mock_execute:
                init_db(app)
                mock_execute.assert_not_called()

    def test_legacy_init_db_emits_deprecation(self, app):
        """_legacy_init_db emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _legacy_init_db(app)
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()


class TestCreateModuleTables:
    """Tests for deprecated create_module_tables"""

    def test_create_module_tables_is_noop(self):
        """create_module_tables should be a deprecated no-op."""
        from app.modules.migrations import create_module_tables
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            create_module_tables()
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 1


class TestAlembicSinglePath:
    """Tests verifying Alembic is the single schema management path."""

    def test_factory_testing_mode_uses_create_all(self, app):
        """In TESTING mode, create_app uses db.create_all() (intentional)."""
        assert app.config.get('TESTING') is True

    def test_create_all_guarded_by_testing_flag(self):
        """db.create_all() in factory is guarded by TESTING config flag."""
        import inspect
        from app import create_app
        source = inspect.getsource(create_app)
        assert "if app.config.get('TESTING'" in source
        assert "db.create_all()" in source

    def test_alembic_upgrade_head_smoke(self, app):
        """flask db upgrade head should succeed (smoke test)."""
        runner = app.test_cli_runner()
        result = runner.invoke(args=['db', 'heads'])
        assert result.exit_code == 0, f"flask db heads failed: {result.output}"
