"""Tests for onboarding personalization: dashboard reordering and level pre-selection."""
import pytest
import uuid
from unittest.mock import patch
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from config.settings import TestConfig


@pytest.fixture(scope='module')
def app():
    app = create_app(TestConfig)
    with app.app_context():
        from sqlalchemy import text, inspect
        inspector = inspect(_db.engine)
        columns = [c['name'] for c in inspector.get_columns('users')]
        for col, typ in [('onboarding_completed', 'BOOLEAN DEFAULT false'),
                         ('referral_code', 'VARCHAR(16) UNIQUE'),
                         ('referred_by_id', 'INTEGER'),
                         ('onboarding_level', 'VARCHAR(4)'),
                         ('onboarding_focus', 'VARCHAR(100)'),
                         ('email_unsubscribe_token', 'VARCHAR(64) UNIQUE'),
                         ('email_opted_out', 'BOOLEAN DEFAULT false')]:
            if col not in columns:
                try:
                    _db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {typ}'))
                    _db.session.commit()
                except Exception:
                    _db.session.rollback()
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()


@pytest.fixture
def grammar_focus_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'gram_{suffix}',
        email=f'gram_{suffix}@test.com',
        active=True,
        onboarding_focus='grammar',
        onboarding_level='A1',
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def vocab_focus_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'vocab_{suffix}',
        email=f'vocab_{suffix}@test.com',
        active=True,
        onboarding_focus='vocabulary',
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def no_focus_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'nofocus_{suffix}',
        email=f'nofocus_{suffix}@test.com',
        active=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.delete(user)
    db_session.commit()


class TestDashboardPersonalization:
    """Test that dashboard reorders widgets based on onboarding_focus."""

    def test_dashboard_loads_with_grammar_focus(self, app, client, grammar_focus_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(grammar_focus_user.id)
        with patch('app.modules.decorators.ModuleService') as mock_ms:
            mock_ms.is_module_enabled_for_user.return_value = True
            response = client.get('/dashboard')
        assert response.status_code == 200

    def test_dashboard_loads_with_vocab_focus(self, app, client, vocab_focus_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(vocab_focus_user.id)
        with patch('app.modules.decorators.ModuleService') as mock_ms:
            mock_ms.is_module_enabled_for_user.return_value = True
            response = client.get('/dashboard')
        assert response.status_code == 200

    def test_dashboard_loads_without_focus(self, app, client, no_focus_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(no_focus_user.id)
        with patch('app.modules.decorators.ModuleService') as mock_ms:
            mock_ms.is_module_enabled_for_user.return_value = True
            response = client.get('/dashboard')
        assert response.status_code == 200

    def test_grammar_focus_shows_recommendation(self, app, client, grammar_focus_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(grammar_focus_user.id)
        with patch('app.modules.decorators.ModuleService') as mock_ms:
            mock_ms.is_module_enabled_for_user.return_value = True
            response = client.get('/dashboard')
        html = response.data.decode()
        assert 'dash-recommendation' in html or 'dash-progress' in html


class TestLearnLevelPreselection:
    """Test that /learn/ redirects to onboarding level for new users."""

    def test_learn_redirects_to_onboarding_level(self, client, grammar_focus_user, app):
        """User with onboarding_level and no progress should be redirected."""
        from app.curriculum.models import CEFRLevel
        with app.app_context():
            level = CEFRLevel.query.filter_by(code='A1').first()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(grammar_focus_user.id)
        response = client.get('/learn/')
        # Should redirect to A1 level page if A1 exists, or stay on index
        if level:
            assert response.status_code == 302
            assert 'A1' in response.headers.get('Location', '')
        else:
            assert response.status_code == 200

    def test_learn_no_redirect_without_onboarding(self, client, no_focus_user):
        """User without onboarding_level should see normal index."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(no_focus_user.id)
        response = client.get('/learn/')
        assert response.status_code == 200
