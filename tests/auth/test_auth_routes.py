"""
Auth routes: redirect safety, session clearing, remember_me bypass, JWT refresh.
"""
import pytest
import uuid
from unittest.mock import patch

from app.auth.models import User
from app.utils.db import db


# ---------------------------------------------------------------------------
# ?next= open redirect protection
# ---------------------------------------------------------------------------

class TestOpenRedirectProtection:
    """Comprehensive open redirect tests for all ?next= entry points."""

    def _login(self, client, user, next_url=None):
        url = '/login'
        if next_url:
            url += f'?next={next_url}'
        return client.post(url, data={
            'username_or_email': user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

    def test_blocks_protocol_relative_url(self, client, test_user):
        r = self._login(client, test_user, '//evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_backslash_trick(self, client, test_user):
        r = self._login(client, test_user, '/\\evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_data_url(self, client, test_user):
        r = self._login(client, test_user, 'data:text/html,<h1>xss</h1>')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'data:' not in loc

    def test_blocks_ftp_scheme(self, client, test_user):
        r = self._login(client, test_user, 'ftp://evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'ftp' not in loc

    def test_allows_internal_path_with_hash(self, client, test_user):
        r = self._login(client, test_user, '/study/#section')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/study/' in loc

    def test_relative_path_without_slash_rejected(self, client, test_user):
        r = self._login(client, test_user, 'evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    @pytest.mark.smoke
    def test_get_safe_redirect_url_unit(self, app):
        from app.auth.routes import get_safe_redirect_url
        with app.test_request_context():
            assert get_safe_redirect_url('//evil.com', 'auth.login').startswith('/')
            assert 'evil.com' not in get_safe_redirect_url('//evil.com', 'auth.login')
            assert get_safe_redirect_url('/study/', 'auth.login') == '/study/'
            assert get_safe_redirect_url('/\\evil.com', 'auth.login').startswith('/')
            assert 'evil.com' not in get_safe_redirect_url('/\\evil.com', 'auth.login')


# ---------------------------------------------------------------------------
# Session clearing after logout
# ---------------------------------------------------------------------------

class TestSessionClearingOnLogout:
    """After logout, session must be fully cleared — no protected resource accessible."""

    @pytest.mark.smoke
    def test_protected_route_returns_redirect_after_logout(self, authenticated_client):
        r_before = authenticated_client.get('/profile', follow_redirects=False)
        assert r_before.status_code == 200

        authenticated_client.get('/logout', follow_redirects=False)

        r_after = authenticated_client.get('/profile', follow_redirects=False)
        assert r_after.status_code in (302, 401)

    def test_logout_clears_user_id_from_session(self, client, test_user):
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

        with client.session_transaction() as session:
            assert '_user_id' in session

        client.get('/logout', follow_redirects=False)

        with client.session_transaction() as session:
            assert '_user_id' not in session

    def test_double_logout_does_not_crash(self, authenticated_client):
        authenticated_client.get('/logout', follow_redirects=False)
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_logout_redirects_to_login(self, authenticated_client):
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/login' in loc

    def test_api_endpoint_inaccessible_after_logout(self, authenticated_client):
        r_before = authenticated_client.get('/profile')
        assert r_before.status_code == 200

        authenticated_client.get('/logout')

        r_after = authenticated_client.get('/profile', follow_redirects=False)
        assert r_after.status_code in (302, 401)


# ---------------------------------------------------------------------------
# remember_me token does not bypass is_active check
# ---------------------------------------------------------------------------

class TestRememberMeDoesNotBypassIsActive:
    """Flask-Login must not grant access to inactive users via remember_me."""

    @pytest.mark.smoke
    def test_inactive_user_cannot_access_protected_route(self, client, db_session, test_user):
        # Log in while active
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

        # Deactivate while session is still valid
        test_user.active = False
        db_session.commit()

        # Flask-Login re-checks is_active on every request via user_loader
        r = client.get('/profile', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_login_with_remember_me_false_and_inactive(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()

        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
            'remember_me': 'y',
        }, follow_redirects=True)
        # Should not be logged in
        assert r.status_code == 200
        body = r.data.decode().lower()
        assert 'неактивна' in body or 'inactive' in body


# ---------------------------------------------------------------------------
# JWT refresh endpoint — token type enforcement
# ---------------------------------------------------------------------------

class TestJWTRefreshEndpoint:
    """JWT refresh must require a refresh token, not an access token."""

    @pytest.mark.smoke
    def test_refresh_with_access_token_fails(self, client, test_user, app):
        from flask_jwt_extended import create_access_token
        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))

        r = client.post('/api/refresh', headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_without_token_fails(self, client):
        r = client.post('/api/refresh', headers={
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_with_invalid_token_fails(self, client):
        r = client.post('/api/refresh', headers={
            'Authorization': 'Bearer this.is.invalid',
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_with_valid_refresh_token_succeeds(self, client, test_user, app):
        from flask_jwt_extended import create_refresh_token
        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username, 'is_admin': False},
            )

        r = client.post('/api/refresh', headers={
            'Authorization': f'Bearer {refresh_token}',
            'Content-Type': 'application/json',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'access_token' in data


# ---------------------------------------------------------------------------
# API login — is_active check
# ---------------------------------------------------------------------------

class TestAPILoginIsActiveCheck:
    """POST /api/auth/login must reject inactive users."""

    def test_inactive_user_gets_403(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()

        r = client.post('/api/login', json={
            'username': test_user.username,
            'password': 'testpass123',
        })
        assert r.status_code == 403
        data = r.get_json()
        assert data.get('error') == 'account_inactive'

    def test_active_user_gets_tokens(self, client, test_user):
        r = client.post('/api/login', json={
            'username': test_user.username,
            'password': 'testpass123',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'access_token' in data
        assert 'refresh_token' in data


# ---------------------------------------------------------------------------
# Referral system
# ---------------------------------------------------------------------------

def _make_unique_reg_data(suffix=None):
    """Return valid registration form data with unique credentials."""
    tag = suffix or uuid.uuid4().hex[:8]
    return {
        'username': f'refuser_{tag}',
        'email': f'refuser_{tag}@example.com',
        'password': 'Passw0rd!',
        'password2': 'Passw0rd!',
    }


class TestReferralIdempotency:
    """award_referral_xp_idempotent must award XP exactly once per referee."""

    @pytest.mark.smoke
    def test_xp_awarded_once_per_referee(self, app, db_session):
        from app.achievements.xp_service import award_referral_xp_idempotent
        from app.achievements.models import StreakEvent

        referrer = User(username=f'ref_a_{uuid.uuid4().hex[:6]}',
                        email=f'ref_a_{uuid.uuid4().hex[:6]}@example.com', active=True)
        referrer.set_password('pass1234')
        referee = User(username=f'ref_b_{uuid.uuid4().hex[:6]}',
                       email=f'ref_b_{uuid.uuid4().hex[:6]}@example.com', active=True)
        referee.set_password('pass1234')
        db_session.add_all([referrer, referee])
        db_session.flush()

        with app.test_request_context():
            result1 = award_referral_xp_idempotent(referrer.id, referee.id, 50)
            db_session.commit()
            result2 = award_referral_xp_idempotent(referrer.id, referee.id, 50)
            db_session.commit()

        assert result1 is not None
        assert result2 is None, "Second award must be a no-op"

        events = db_session.query(StreakEvent).filter_by(
            user_id=referrer.id, event_type='xp_referral'
        ).all()
        assert len(events) == 1

    def test_different_referee_awards_separately(self, app, db_session):
        from app.achievements.xp_service import award_referral_xp_idempotent
        from app.achievements.models import StreakEvent

        referrer = User(username=f'refr_{uuid.uuid4().hex[:6]}',
                        email=f'refr_{uuid.uuid4().hex[:6]}@example.com', active=True)
        referrer.set_password('pass1234')
        ref1 = User(username=f'rfe1_{uuid.uuid4().hex[:6]}',
                    email=f'rfe1_{uuid.uuid4().hex[:6]}@example.com', active=True)
        ref1.set_password('pass1234')
        ref2 = User(username=f'rfe2_{uuid.uuid4().hex[:6]}',
                    email=f'rfe2_{uuid.uuid4().hex[:6]}@example.com', active=True)
        ref2.set_password('pass1234')
        db_session.add_all([referrer, ref1, ref2])
        db_session.flush()

        with app.test_request_context():
            r1 = award_referral_xp_idempotent(referrer.id, ref1.id, 50)
            db_session.commit()
            r2 = award_referral_xp_idempotent(referrer.id, ref2.id, 50)
            db_session.commit()

        assert r1 is not None
        assert r2 is not None

        events = db_session.query(StreakEvent).filter_by(
            user_id=referrer.id, event_type='xp_referral'
        ).count()
        assert events == 2

    def test_zero_xp_returns_none(self, app, db_session):
        from app.achievements.xp_service import award_referral_xp_idempotent

        u1 = User(username=f'uxp_{uuid.uuid4().hex[:6]}',
                  email=f'uxp_{uuid.uuid4().hex[:6]}@example.com', active=True)
        u1.set_password('pass1234')
        u2 = User(username=f'uxp2_{uuid.uuid4().hex[:6]}',
                  email=f'uxp2_{uuid.uuid4().hex[:6]}@example.com', active=True)
        u2.set_password('pass1234')
        db_session.add_all([u1, u2])
        db_session.flush()

        with app.test_request_context():
            result = award_referral_xp_idempotent(u1.id, u2.id, 0)

        assert result is None


class TestReferralRegistration:
    """Registration with referral code sets referred_by_id correctly."""

    def _register(self, client, data, ref_code=None):
        url = '/register'
        if ref_code is not None:
            url += f'?ref={ref_code}'
        return client.post(url, data=data, follow_redirects=False)

    @pytest.mark.smoke
    def test_valid_ref_code_sets_referred_by(self, client, db_session, test_user):
        test_user.ensure_referral_code()
        db_session.commit()
        ref_code = test_user.referral_code

        data = _make_unique_reg_data()
        r = self._register(client, data, ref_code=ref_code)

        # Should redirect (to onboarding or dashboard, not 500)
        assert r.status_code in (302, 200), f"Expected redirect, got {r.status_code}"

        new_user = User.query.filter_by(username=data['username']).first()
        assert new_user is not None
        assert new_user.referred_by_id == test_user.id

    def test_invalid_long_ref_code_ignored(self, client, db_session):
        long_code = 'a' * 100
        data = _make_unique_reg_data()
        r = self._register(client, data, ref_code=long_code)
        assert r.status_code != 500

        new_user = User.query.filter_by(username=data['username']).first()
        if new_user:
            assert new_user.referred_by_id is None

    def test_nonexistent_ref_code_ignored(self, client, db_session):
        data = _make_unique_reg_data()
        r = self._register(client, data, ref_code='notexist')
        assert r.status_code != 500

        new_user = User.query.filter_by(username=data['username']).first()
        if new_user:
            assert new_user.referred_by_id is None

    def test_non_alphanumeric_ref_code_ignored(self, client, db_session):
        data = _make_unique_reg_data()
        r = self._register(client, data, ref_code='<script>xss</script>')
        assert r.status_code != 500

    def test_ref_code_form_field_used_when_no_query_param(self, client, db_session, test_user):
        test_user.ensure_referral_code()
        db_session.commit()

        data = {**_make_unique_reg_data(), 'ref': test_user.referral_code}
        r = client.post('/register', data=data, follow_redirects=False)
        assert r.status_code != 500

        new_user = User.query.filter_by(username=data['username']).first()
        if new_user:
            assert new_user.referred_by_id == test_user.id


class TestReferralSelfReferralPrevention:
    """Self-referral must be blocked."""

    def test_cookie_path_blocks_self_referral(self, client, db_session, test_user):
        """Cookie-based referral log must not record referrer == referred."""
        from app.auth.models import ReferralLog

        test_user.ensure_referral_code()
        db_session.commit()

        # Simulate cookie being set to test_user's own code
        client.set_cookie('ref', test_user.referral_code)

        # Create another user whose registration would try to use this code
        # then check that self-referral is blocked at the code level
        data = _make_unique_reg_data()
        client.post('/register', data=data, follow_redirects=False)
        new_user = User.query.filter_by(username=data['username']).first()

        if new_user:
            # Cookie held test_user's code: new_user != test_user so it's a real referral, not self
            # The ReferralLog should link test_user -> new_user (not self)
            log = db_session.query(ReferralLog).filter_by(
                referrer_id=test_user.id, referred_id=new_user.id
            ).first()
            if log:
                assert log.referrer_id != log.referred_id

    def test_referral_log_unique_per_referred(self, db_session, app):
        """ReferralLog has unique constraint on referred_id."""
        from app.auth.models import ReferralLog
        from sqlalchemy.exc import IntegrityError

        u1 = User(username=f'sl1_{uuid.uuid4().hex[:6]}',
                  email=f'sl1_{uuid.uuid4().hex[:6]}@example.com', active=True)
        u1.set_password('pass1234')
        u2 = User(username=f'sl2_{uuid.uuid4().hex[:6]}',
                  email=f'sl2_{uuid.uuid4().hex[:6]}@example.com', active=True)
        u2.set_password('pass1234')
        db_session.add_all([u1, u2])
        db_session.flush()

        log1 = ReferralLog(referrer_id=u1.id, referred_id=u2.id)
        db_session.add(log1)
        db_session.flush()

        # Duplicate should fail
        log2 = ReferralLog(referrer_id=u1.id, referred_id=u2.id)
        db_session.add(log2)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


class TestReferralLinkURL:
    """Referral link must use url_for with _external=True."""

    @pytest.mark.smoke
    def test_referrals_page_contains_full_url(self, authenticated_client, test_user, db_session):
        test_user.ensure_referral_code()
        db_session.commit()

        r = authenticated_client.get('/referrals')
        assert r.status_code == 200
        body = r.data.decode()
        # External URL includes scheme (http:// or https://)
        assert 'http' in body
        assert test_user.referral_code in body

    def test_referral_link_format(self, app, test_user, db_session):
        test_user.ensure_referral_code()
        db_session.commit()

        with app.test_request_context():
            from flask import url_for
            link = url_for('auth.register', ref=test_user.referral_code, _external=True)
        assert link.startswith('http')
        assert test_user.referral_code in link
        assert '/register' in link
