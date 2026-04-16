"""Tests for open redirect protection via get_safe_redirect_url."""
import uuid

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

    def test_all_next_params_use_safe_validation(self):
        """Ensure all request.args.get('next') usages are wrapped by get_safe_redirect_url."""
        import os
        import re

        app_dir = os.path.join(os.path.dirname(__file__), '..', 'app')
        raw_next_pattern = re.compile(r"redirect\(\s*request\.(args|form)\.get\(['\"]next['\"]")

        violations = []
        for root, dirs, files in os.walk(app_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                filepath = os.path.join(root, fname)
                with open(filepath) as f:
                    for lineno, line in enumerate(f, 1):
                        if raw_next_pattern.search(line):
                            violations.append(f'{filepath}:{lineno}: {line.strip()}')

        assert violations == [], (
            'Found redirect() using raw next param without get_safe_redirect_url:\n'
            + '\n'.join(violations)
        )


class TestWordsRouteNextParamProtection:
    """Verify that words.update_word_status uses safe redirect for next param."""

    @pytest.fixture
    def words_module_fixture(self, db_session, test_user):
        from app.modules.models import SystemModule, UserModule
        module = SystemModule.query.filter_by(code='words').first()
        if not module:
            module = SystemModule(
                code='words', name='Words', description='Words module',
                is_active=True, is_default=True, order=4,
            )
            db_session.add(module)
            db_session.flush()
        existing = UserModule.query.filter_by(
            user_id=test_user.id, module_id=module.id,
        ).first()
        if not existing:
            db_session.add(UserModule(
                user_id=test_user.id, module_id=module.id, is_enabled=True,
            ))
            db_session.commit()
        return module

    @pytest.fixture
    def sample_word(self, db_session):
        from app.words.models import CollectionWords
        suffix = uuid.uuid4().hex[:8]
        word = CollectionWords(
            english_word=f'testword_{suffix}',
            russian_word='тестовое слово',
            level='A1',
            item_type='word',
        )
        db_session.add(word)
        db_session.commit()
        return word

    def test_external_next_blocked(self, authenticated_client, words_module_fixture, sample_word):
        """next=https://evil.com must not redirect to evil.com."""
        resp = authenticated_client.post(
            f'/update-word-status/{sample_word.id}/1',
            query_string={'next': 'https://evil.com/steal'},
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location

    def test_internal_next_allowed(self, authenticated_client, words_module_fixture, sample_word):
        """next=/words must redirect to /words."""
        resp = authenticated_client.post(
            f'/update-word-status/{sample_word.id}/1',
            query_string={'next': '/words'},
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert '/words' in location

    def test_protocol_relative_next_blocked(self, authenticated_client, words_module_fixture, sample_word):
        """next=//evil.com must not redirect to evil.com."""
        resp = authenticated_client.post(
            f'/update-word-status/{sample_word.id}/1',
            query_string={'next': '//evil.com'},
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get('Location', '')
        assert 'evil.com' not in location
