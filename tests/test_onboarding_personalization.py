"""Tests for onboarding personalization: dashboard reordering and level pre-selection."""
import pytest
import uuid
from unittest.mock import patch
from app.auth.models import User


@pytest.fixture
def grammar_focus_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'gram_{suffix}',
        email=f'gram_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
        onboarding_focus='grammar',
        onboarding_level='A1',
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def no_focus_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'nofocus_{suffix}',
        email=f'nofocus_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


class TestLearnLevelPreselection:
    """Test that /learn/ redirects to onboarding level for new users."""

    def test_learn_redirects_to_onboarding_level(self, client, grammar_focus_user, app):
        """User with onboarding_level and no progress should be redirected."""
        from app.curriculum.models import CEFRLevel
        level = CEFRLevel.query.filter_by(code='A1').first()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(grammar_focus_user.id)
        response = client.get('/learn/')
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
