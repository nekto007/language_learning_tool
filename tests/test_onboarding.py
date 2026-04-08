"""
Tests for onboarding wizard flow.

Tests:
- New user redirect to onboarding after login
- New user redirect to onboarding after registration
- Wizard page renders for unonboarded user
- Completed user redirects to dashboard
- POST /onboarding/complete marks user as onboarded
- After completion, login goes to dashboard
"""
import pytest
import uuid
from unittest.mock import patch

from app.auth.models import User
from app.utils.db import db


@pytest.fixture
def new_user(db_session):
    """Create a user who hasn't completed onboarding."""
    username = f'newuser_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=False
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


class TestOnboardingWizard:
    def test_wizard_page_requires_login(self, client):
        r = client.get('/onboarding', follow_redirects=False)
        assert r.status_code == 302
        assert '/login' in r.headers.get('Location', '')

    def test_wizard_page_renders_for_new_user(self, client, new_user):
        # Login first
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        r = client.get('/onboarding')
        assert r.status_code == 200
        assert 'Какой у вас уровень' in r.data.decode()

    def test_wizard_redirects_if_completed(self, client, test_user):
        """test_user has onboarding_completed=True by default."""
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        r = client.get('/onboarding', follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/onboarding' not in loc


class TestOnboardingRedirect:
    def test_login_redirects_new_user_to_onboarding(self, client, new_user):
        r = client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/onboarding' in r.headers.get('Location', '')

    def test_login_redirects_completed_user_to_dashboard(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/onboarding' not in loc

    @patch('app.auth.routes.email_sender')
    def test_register_redirects_to_onboarding(self, mock_email, client, db_session):
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'reguser_{unique}',
            'email': f'reguser_{unique}@example.com',
            'password': 'Xk9!mWq#Pz',
            'password2': 'Xk9!mWq#Pz',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/onboarding' in r.headers.get('Location', '')


class TestOnboardingBeforeRequest:
    """Test the before_request hook that redirects unonboarded users."""

    def test_unonboarded_user_redirected_from_dashboard(self, client, new_user):
        """Authenticated user with onboarding_completed=False should be redirected to onboarding."""
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        r = client.get('/dashboard', follow_redirects=False)
        assert r.status_code == 302
        assert '/onboarding' in r.headers.get('Location', '')

    def test_unonboarded_user_can_access_public_pages(self, client, new_user):
        """Public pages like /privacy and /grammar-lab should not redirect to onboarding."""
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        r = client.get('/privacy', follow_redirects=False)
        assert r.status_code == 200

    def test_ajax_request_not_redirected(self, client, new_user):
        """AJAX requests should not be redirected to onboarding."""
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        r = client.get('/dashboard', headers={'X-Requested-With': 'XMLHttpRequest'},
                       follow_redirects=False)
        # AJAX requests should not be redirected to onboarding
        assert r.status_code != 302 or '/onboarding' not in r.headers.get('Location', '')
        assert r.status_code in (200, 403)  # 403 is acceptable (CSRF on dashboard)


class TestOnboardingComplete:
    def test_complete_marks_user_onboarded(self, client, db_session, new_user):
        # Login
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)

        # Complete onboarding
        r = client.post('/onboarding/complete', data={
            'level': 'B1',
            'focus': 'grammar,vocabulary',
        }, follow_redirects=False)
        assert r.status_code == 302

        # Verify user is marked completed and choices are saved
        db_session.refresh(new_user)
        assert new_user.onboarding_completed is True
        assert new_user.onboarding_level == 'B1'
        assert new_user.onboarding_focus == 'grammar,vocabulary'

    def test_complete_already_onboarded_redirects(self, client, test_user):
        # Login with completed user
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)

        r = client.post('/onboarding/complete', data={
            'level': 'A1',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/onboarding' not in r.headers.get('Location', '')

    def test_complete_with_next_redirects_to_target(self, client, db_session, new_user):
        """POST /onboarding/complete with next param should redirect to that URL."""
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)

        r = client.post('/onboarding/complete', data={
            'level': 'B2',
            'focus': 'grammar',
            'next': '/study/achievements',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/study/achievements' in r.headers.get('Location', '')

    def test_after_completion_login_goes_to_dashboard(self, client, db_session, new_user):
        # Login and complete onboarding
        client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        client.post('/onboarding/complete', data={
            'level': 'A2',
        }, follow_redirects=True)

        # Logout
        client.get('/logout', follow_redirects=True)

        # Login again - should go to dashboard, not onboarding
        r = client.post('/login', data={
            'username_or_email': new_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/onboarding' not in loc
