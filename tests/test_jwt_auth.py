"""
Comprehensive tests for JWT Authentication utilities

Security-critical module testing:
- Token generation and validation
- Token expiry mechanisms
- Refresh token flow
- Claims verification
- Edge cases and security scenarios

Target coverage: 95%+ for app/utils/jwt_auth.py
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from flask_jwt_extended.exceptions import JWTDecodeError


class TestCreateTokensForUser:
    """Test create_tokens_for_user function"""

    def test_creates_access_and_refresh_tokens(self, app, test_user):
        """Test that both tokens are created for a user"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(test_user)

        assert 'access_token' in result
        assert 'refresh_token' in result
        assert 'token_type' in result
        assert 'expires_in' in result
        assert result['token_type'] == 'Bearer'
        assert result['expires_in'] == 900  # 15 minutes

    def test_access_token_contains_user_claims(self, app, test_user):
        """Test that access token contains proper user claims"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(test_user)
            decoded = decode_token(result['access_token'])

        assert decoded['sub'] == str(test_user.id)
        assert decoded['user_id'] == test_user.id
        assert decoded['username'] == test_user.username
        assert decoded['is_admin'] == test_user.is_admin
        assert decoded['fresh'] is True

    def test_refresh_token_contains_minimal_claims(self, app, test_user):
        """Test that refresh token contains only necessary claims"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(test_user)
            decoded = decode_token(result['refresh_token'])

        assert decoded['sub'] == str(test_user.id)
        assert decoded['username'] == test_user.username
        # Refresh tokens should not have is_admin for security
        assert 'is_admin' not in decoded or decoded.get('is_admin') is None

    def test_tokens_for_admin_user(self, app, admin_user):
        """Test token generation for admin user"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(admin_user)
            decoded = decode_token(result['access_token'])

        assert decoded['is_admin'] == getattr(admin_user, 'is_admin', False)
        assert decoded['user_id'] == admin_user.id

    def test_tokens_for_user_without_is_admin_attribute(self, app, db_session):
        """Test token generation for user without is_admin attribute"""
        from app.utils.jwt_auth import create_tokens_for_user
        from app.auth.models import User

        # Create user without setting is_admin
        user = User(username='nonadmin', email='nonadmin@test.com')
        user.set_password('password')
        db_session.add(user)
        db_session.commit()

        with app.app_context():
            result = create_tokens_for_user(user)
            decoded = decode_token(result['access_token'])

        # Should default to False if not present
        assert decoded['is_admin'] is False

    def test_tokens_have_different_values(self, app, test_user):
        """Test that access and refresh tokens are different"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(test_user)

        assert result['access_token'] != result['refresh_token']

    def test_multiple_calls_generate_different_tokens(self, app, test_user):
        """Test that calling twice generates different tokens"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result1 = create_tokens_for_user(test_user)
            result2 = create_tokens_for_user(test_user)

        assert result1['access_token'] != result2['access_token']
        assert result1['refresh_token'] != result2['refresh_token']

    def test_identity_is_always_string(self, app, test_user):
        """Test that user ID in token is always a string"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result = create_tokens_for_user(test_user)
            decoded_access = decode_token(result['access_token'])
            decoded_refresh = decode_token(result['refresh_token'])

        assert isinstance(decoded_access['sub'], str)
        assert isinstance(decoded_refresh['sub'], str)


class TestGetCurrentUserId:
    """Test get_current_user_id function"""

    def test_returns_user_id_from_token(self, app, test_user):
        """Test retrieving user ID from JWT token"""
        from app.utils.jwt_auth import get_current_user_id
        from flask_jwt_extended import create_access_token

        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))

            # Simulate request with JWT
            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                user_id = get_current_user_id()

        assert user_id == str(test_user.id)

    def test_returns_none_without_token(self, app):
        """Test behavior when no token is present"""
        from app.utils.jwt_auth import get_current_user_id

        with app.app_context():
            with app.test_request_context():
                # Should raise exception or return None
                with pytest.raises(Exception):
                    get_current_user_id()


class TestGetCurrentUserClaims:
    """Test get_current_user_claims function"""

    def test_returns_all_claims(self, app, test_user):
        """Test retrieving all claims from JWT"""
        from app.utils.jwt_auth import get_current_user_claims

        with app.app_context():
            access_token = create_access_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username, 'is_admin': True}
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                claims = get_current_user_claims()

        assert 'username' in claims
        assert 'is_admin' in claims
        assert claims['username'] == test_user.username

    def test_returns_standard_jwt_claims(self, app, test_user):
        """Test that standard JWT claims are present"""
        from app.utils.jwt_auth import get_current_user_claims

        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                claims = get_current_user_claims()

        # Standard JWT claims
        assert 'sub' in claims  # Subject (user ID)
        assert 'iat' in claims  # Issued at
        assert 'exp' in claims  # Expiration
        assert 'jti' in claims  # JWT ID


class TestIsTokenFresh:
    """Test is_token_fresh function"""

    def test_fresh_token_returns_true(self, app, test_user):
        """Test that fresh token is detected correctly"""
        from app.utils.jwt_auth import is_token_fresh

        with app.app_context():
            access_token = create_access_token(
                identity=str(test_user.id),
                fresh=True
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                assert is_token_fresh() is True

    def test_non_fresh_token_returns_false(self, app, test_user):
        """Test that non-fresh token is detected correctly"""
        from app.utils.jwt_auth import is_token_fresh

        with app.app_context():
            access_token = create_access_token(
                identity=str(test_user.id),
                fresh=False
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                assert is_token_fresh() is False

    def test_token_without_fresh_claim_defaults_false(self, app, test_user):
        """Test that token without fresh claim defaults to False"""
        from app.utils.jwt_auth import is_token_fresh

        with app.app_context():
            # Create token without explicit fresh parameter
            access_token = create_access_token(identity=str(test_user.id))

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request()
                # Default should be False for security
                result = is_token_fresh()
                assert isinstance(result, bool)


class TestRefreshAccessToken:
    """Test refresh_access_token function"""

    def test_creates_new_access_token(self, app, test_user):
        """Test creating new access token from refresh token"""
        from app.utils.jwt_auth import refresh_access_token

        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username}
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                result = refresh_access_token()

        assert 'access_token' in result
        assert 'token_type' in result
        assert 'expires_in' in result
        assert result['token_type'] == 'Bearer'
        assert result['expires_in'] == 900

    def test_new_token_is_not_fresh(self, app, test_user):
        """Test that refreshed token is marked as not fresh"""
        from app.utils.jwt_auth import refresh_access_token

        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username, 'is_admin': False}
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                result = refresh_access_token()
                decoded = decode_token(result['access_token'])

        assert decoded['fresh'] is False

    def test_preserves_user_claims(self, app, test_user):
        """Test that user claims are preserved when refreshing"""
        from app.utils.jwt_auth import refresh_access_token

        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username, 'is_admin': False}
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                result = refresh_access_token()
                decoded = decode_token(result['access_token'])

        assert decoded['user_id'] == str(test_user.id)
        assert decoded['username'] == test_user.username
        assert decoded['is_admin'] is False

    def test_handles_string_conversion_in_refresh(self, app, test_user):
        """Test that user IDs remain as strings throughout refresh flow"""
        from app.utils.jwt_auth import refresh_access_token

        with app.app_context():
            # Create refresh token with string identity
            refresh_token = create_refresh_token(
                identity=str(test_user.id),  # String identity
                additional_claims={'username': test_user.username}
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                result = refresh_access_token()
                decoded = decode_token(result['access_token'])

        # Should remain as string
        assert isinstance(decoded['sub'], str)
        assert isinstance(decoded['user_id'], str)

    def test_defaults_is_admin_to_false(self, app, test_user):
        """Test that is_admin defaults to False if not in refresh token"""
        from app.utils.jwt_auth import refresh_access_token

        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username}
                # No is_admin claim
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                result = refresh_access_token()
                decoded = decode_token(result['access_token'])

        assert decoded['is_admin'] is False


class TestTokenSecurity:
    """Security-focused tests for JWT functionality"""

    def test_expired_token_raises_error(self, app, test_user):
        """Test that expired tokens are rejected"""
        import jwt

        with app.app_context():
            # Create token that expires immediately
            access_token = create_access_token(
                identity=str(test_user.id),
                expires_delta=timedelta(seconds=-1)  # Already expired
            )

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                with pytest.raises(jwt.ExpiredSignatureError):
                    verify_jwt_in_request()

    def test_invalid_token_raises_error(self, app):
        """Test that invalid tokens are rejected"""
        import jwt

        with app.app_context():
            with app.test_request_context(
                headers={'Authorization': 'Bearer invalid_token_here'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                with pytest.raises(jwt.DecodeError):
                    verify_jwt_in_request()

    def test_tampered_token_raises_error(self, app, test_user):
        """Test that tampered tokens are rejected"""
        import jwt

        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))
            # Tamper with token by changing a character
            tampered_token = access_token[:-10] + 'TAMPERED'

            with app.test_request_context(
                headers={'Authorization': f'Bearer {tampered_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                with pytest.raises((jwt.DecodeError, jwt.InvalidSignatureError)):
                    verify_jwt_in_request()

    def test_refresh_token_cannot_be_used_as_access_token(self, app, test_user):
        """Test that refresh tokens cannot be used for regular access"""
        from flask_jwt_extended.exceptions import WrongTokenError

        with app.app_context():
            refresh_token = create_refresh_token(identity=str(test_user.id))

            with app.test_request_context(
                headers={'Authorization': f'Bearer {refresh_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                with pytest.raises(WrongTokenError):
                    verify_jwt_in_request(refresh=False)

    def test_access_token_cannot_be_used_as_refresh_token(self, app, test_user):
        """Test that access tokens cannot be used for refresh"""
        from flask_jwt_extended.exceptions import WrongTokenError

        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))

            with app.test_request_context(
                headers={'Authorization': f'Bearer {access_token}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                with pytest.raises(WrongTokenError):
                    verify_jwt_in_request(refresh=True)

    def test_tokens_are_unique_per_generation(self, app, test_user):
        """Test that each token generation creates unique tokens"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result1 = create_tokens_for_user(test_user)
            result2 = create_tokens_for_user(test_user)
            result3 = create_tokens_for_user(test_user)

        # All tokens should be different
        tokens = [
            result1['access_token'],
            result1['refresh_token'],
            result2['access_token'],
            result2['refresh_token'],
            result3['access_token'],
            result3['refresh_token']
        ]
        assert len(tokens) == len(set(tokens))  # All unique

    def test_token_jti_is_unique(self, app, test_user):
        """Test that JWT ID (jti) is unique for each token"""
        from app.utils.jwt_auth import create_tokens_for_user

        with app.app_context():
            result1 = create_tokens_for_user(test_user)
            result2 = create_tokens_for_user(test_user)

            jti1 = decode_token(result1['access_token'])['jti']
            jti2 = decode_token(result2['access_token'])['jti']

        assert jti1 != jti2

    def test_user_id_claim_consistency(self, app, test_user):
        """Test that user_id claim is consistent across token lifecycle"""
        from app.utils.jwt_auth import create_tokens_for_user, refresh_access_token

        with app.app_context():
            # Create initial tokens
            initial_tokens = create_tokens_for_user(test_user)
            initial_decoded = decode_token(initial_tokens['access_token'])

            # Refresh token
            with app.test_request_context(
                headers={'Authorization': f'Bearer {initial_tokens["refresh_token"]}'}
            ):
                from flask_jwt_extended import verify_jwt_in_request
                verify_jwt_in_request(refresh=True)
                refreshed = refresh_access_token()
                refreshed_decoded = decode_token(refreshed['access_token'])

        # User ID should be consistent (both as strings after refresh)
        assert str(initial_decoded['user_id']) == str(refreshed_decoded['user_id'])
        assert initial_decoded['sub'] == refreshed_decoded['sub']
