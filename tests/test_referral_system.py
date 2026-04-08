"""
Tests for referral system:
- referral_code generation on User creation
- ReferralLog creation on registration with ?ref= param
- Share URL formation
"""
import uuid
from unittest.mock import patch

import pytest

from app.auth.models import ReferralLog, User
from app.utils.db import db


class TestReferralCodeGeneration:
    def test_user_gets_referral_code_on_create(self, db_session):
        """New user should get a referral code automatically."""
        unique = uuid.uuid4().hex[:8]
        user = User(username=f'reftest_{unique}', email=f'reftest_{unique}@example.com', active=True)
        user.set_password('TestPass123!')
        db_session.add(user)
        db_session.commit()

        assert user.referral_code is not None
        assert len(user.referral_code) == 8

    def test_referral_codes_are_unique(self, db_session):
        """Two users should have different referral codes."""
        users = []
        for i in range(3):
            unique = uuid.uuid4().hex[:8]
            u = User(username=f'refuniq_{unique}', email=f'refuniq_{unique}@example.com', active=True)
            u.set_password('TestPass123!')
            db_session.add(u)
            users.append(u)
        db_session.commit()

        codes = [u.referral_code for u in users]
        assert len(set(codes)) == len(codes), "Referral codes must be unique"


class TestReferralRegistration:
    @patch('app.auth.routes.email_sender')
    def test_register_with_ref_creates_referral_log(self, mock_email, client, db_session, test_user):
        """Registration with ?ref= should create a ReferralLog entry."""
        mock_email.send_email.return_value = True

        # Ensure referrer has a code
        if not test_user.referral_code:
            test_user.referral_code = uuid.uuid4().hex[:8]
            db_session.commit()

        ref_code = test_user.referral_code

        # First GET with ?ref= to set the cookie
        client.get(f'/register?ref={ref_code}')

        # Then POST to register
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'referred_{unique}',
            'email': f'referred_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

        # Check ReferralLog was created
        new_user = User.query.filter_by(username=f'referred_{unique}').first()
        assert new_user is not None

        log = ReferralLog.query.filter_by(referred_id=new_user.id).first()
        assert log is not None
        assert log.referrer_id == test_user.id

    @patch('app.auth.routes.email_sender')
    def test_register_without_ref_no_referral_log(self, mock_email, client, db_session):
        """Normal registration without ?ref= should not create ReferralLog."""
        mock_email.send_email.return_value = True

        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'noreg_{unique}',
            'email': f'noreg_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

        new_user = User.query.filter_by(username=f'noreg_{unique}').first()
        assert new_user is not None

        log = ReferralLog.query.filter_by(referred_id=new_user.id).first()
        assert log is None

    @patch('app.auth.routes.email_sender')
    def test_register_with_invalid_ref_no_referral_log(self, mock_email, client, db_session):
        """Registration with an invalid ref code should not create ReferralLog."""
        mock_email.send_email.return_value = True

        client.get('/register?ref=nonexistent_code')

        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'badref_{unique}',
            'email': f'badref_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

        new_user = User.query.filter_by(username=f'badref_{unique}').first()
        assert new_user is not None

        log = ReferralLog.query.filter_by(referred_id=new_user.id).first()
        assert log is None

    @patch('app.auth.routes.email_sender')
    def test_ref_cookie_is_set_on_get(self, mock_email, client, db_session, test_user):
        """GET /register?ref=CODE should set a ref cookie."""
        if not test_user.referral_code:
            test_user.referral_code = uuid.uuid4().hex[:8]
            db_session.commit()

        r = client.get(f'/register?ref={test_user.referral_code}')
        assert r.status_code == 200
        # The cookie should be set in the response
        set_cookie_headers = [h for h in r.headers.getlist('Set-Cookie') if 'ref=' in h]
        assert len(set_cookie_headers) > 0
        assert test_user.referral_code in set_cookie_headers[0]


class TestReferralLogModel:
    def test_referral_log_relationships(self, db_session, test_user):
        """ReferralLog should have referrer and referred relationships."""
        unique = uuid.uuid4().hex[:8]
        referred_user = User(username=f'refrel_{unique}', email=f'refrel_{unique}@example.com', active=True)
        referred_user.set_password('TestPass123!')
        db_session.add(referred_user)
        db_session.commit()

        log = ReferralLog(referrer_id=test_user.id, referred_id=referred_user.id)
        db_session.add(log)
        db_session.commit()

        assert log.referrer.id == test_user.id
        assert log.referred.id == referred_user.id
        assert log in test_user.referrals_made

    def test_referral_log_unique_referred(self, db_session, test_user):
        """Each user can only be referred once."""
        unique = uuid.uuid4().hex[:8]
        referred_user = User(username=f'refdup_{unique}', email=f'refdup_{unique}@example.com', active=True)
        referred_user.set_password('TestPass123!')
        db_session.add(referred_user)
        db_session.commit()

        log1 = ReferralLog(referrer_id=test_user.id, referred_id=referred_user.id)
        db_session.add(log1)
        db_session.commit()

        # Create a second referrer
        unique2 = uuid.uuid4().hex[:8]
        referrer2 = User(username=f'ref2_{unique2}', email=f'ref2_{unique2}@example.com', active=True)
        referrer2.set_password('TestPass123!')
        db_session.add(referrer2)
        db_session.commit()

        log2 = ReferralLog(referrer_id=referrer2.id, referred_id=referred_user.id)
        db_session.add(log2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()
        db_session.rollback()


class TestShareURL:
    def test_share_buttons_on_achievements(self, authenticated_client):
        """Achievements page should contain share buttons."""
        r = authenticated_client.get('/study/achievements', follow_redirects=True)
        assert r.status_code == 200
        html = r.data.decode()
        assert 'share-buttons' in html or 'shareVia' in html

    def test_share_js_loaded_on_achievements(self, authenticated_client):
        """Achievements page should load share.js."""
        r = authenticated_client.get('/study/achievements', follow_redirects=True)
        assert r.status_code == 200
        html = r.data.decode()
        assert 'share.js' in html
