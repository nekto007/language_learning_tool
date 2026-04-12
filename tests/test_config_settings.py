"""
Tests for config/settings.py — no import-time side effects.
"""
import importlib
import io
import sys
from unittest.mock import patch

import pytest


class TestNoImportTimeSideEffects:
    """Importing config.settings must not print or raise."""

    def test_import_does_not_print(self):
        captured = io.StringIO()
        with patch('sys.stdout', captured), patch('sys.stderr', captured):
            importlib.reload(importlib.import_module('config.settings'))
        output = captured.getvalue()
        assert output == "", f"config.settings printed on import: {output!r}"

    def test_import_does_not_raise(self):
        importlib.reload(importlib.import_module('config.settings'))


class TestValidateEnvironment:
    """Tests for validate_environment()."""

    def test_returns_empty_when_all_set(self):
        from config.settings import validate_environment
        env = {
            'POSTGRES_USER': 'u', 'POSTGRES_PASSWORD': 'p',
            'POSTGRES_DB': 'db', 'SECRET_KEY': 'sk',
            'FLASK_ENV': 'dev', 'FLASK_APP': 'run.py',
        }
        with patch.dict('os.environ', env, clear=False):
            missing_req, missing_rec = validate_environment()
        assert missing_req == []
        assert missing_rec == []

    def test_raises_on_missing_required(self):
        from config.settings import validate_environment, EnvironmentConfigurationError
        env = {'POSTGRES_USER': '', 'POSTGRES_PASSWORD': '', 'POSTGRES_DB': '', 'SECRET_KEY': ''}
        with patch.dict('os.environ', env):
            with pytest.raises(EnvironmentConfigurationError) as exc_info:
                validate_environment()
            assert len(exc_info.value.missing_required) > 0

    def test_warns_on_missing_recommended(self):
        from config.settings import validate_environment
        env = {
            'POSTGRES_USER': 'u', 'POSTGRES_PASSWORD': 'p',
            'POSTGRES_DB': 'db', 'SECRET_KEY': 'sk',
            'FLASK_ENV': '', 'FLASK_APP': '',
        }
        with patch.dict('os.environ', env):
            missing_req, missing_rec = validate_environment()
        assert missing_req == []
        assert len(missing_rec) > 0


class TestConfigSemantics:
    """Verify Config and TestConfig have correct security semantics."""

    def test_test_config_has_hardcoded_secrets(self):
        from config.settings import TestConfig
        assert TestConfig.SECRET_KEY == 'test-secret-key'
        assert TestConfig.JWT_SECRET_KEY == 'test-jwt-secret-key'

    def test_test_config_insecure_cookies(self):
        from config.settings import TestConfig
        assert TestConfig.SESSION_COOKIE_SECURE is False
        assert TestConfig.REMEMBER_COOKIE_SECURE is False

    def test_test_config_testing_flag(self):
        from config.settings import TestConfig
        assert TestConfig.TESTING is True
