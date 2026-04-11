"""Tests for open redirect protection via get_safe_redirect_url."""
import pytest
from app.auth.routes import get_safe_redirect_url


class TestGetSafeRedirectUrl:
    """Test that get_safe_redirect_url blocks external URLs."""

    def test_allows_internal_path(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('/dashboard', fallback='auth.login')
            assert result == '/dashboard'

    def test_allows_internal_path_with_query(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('/lessons?page=2', fallback='auth.login')
            assert result == '/lessons?page=2'

    def test_blocks_absolute_url(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('https://evil.com', fallback='auth.login')
            assert result.startswith('/')
            assert 'evil.com' not in result

    def test_blocks_protocol_relative_url(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('//evil.com', fallback='auth.login')
            assert result.startswith('/')
            assert 'evil.com' not in result

    def test_blocks_backslash_trick(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('/\\evil.com', fallback='auth.login')
            assert result.startswith('/')
            assert 'evil.com' not in result

    def test_blocks_http_scheme(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('http://evil.com/path', fallback='auth.login')
            assert 'evil.com' not in result

    def test_none_returns_fallback(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url(None, fallback='auth.login')
            assert result.startswith('/')

    def test_empty_string_returns_fallback(self, app):
        with app.test_request_context():
            result = get_safe_redirect_url('', fallback='auth.login')
            assert result.startswith('/')


class TestRedirectsUsesSafeValidation:
    """Verify that previously-vulnerable redirect points now use safe validation."""

    def test_no_raw_request_referrer_redirects(self):
        """Ensure no redirect(request.referrer) remains in the codebase."""
        import os
        import re

        app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')
        pattern = re.compile(r'redirect\(request\.referrer')

        violations = []
        for root, dirs, files in os.walk(app_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                filepath = os.path.join(root, fname)
                with open(filepath) as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern.search(line):
                            violations.append(f'{filepath}:{lineno}: {line.strip()}')

        assert violations == [], (
            f'Found raw redirect(request.referrer) without validation:\n'
            + '\n'.join(violations)
        )
