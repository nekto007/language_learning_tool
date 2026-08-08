"""Regression tests for UI-001 (cross-zone audit 2026-08-08).

``/auth/change-password`` rendered ``auth/change_password.html``, which did not
exist. GET 500'd; POST with a valid password **committed the change** and then
also 500'd, so the user could not tell whether it had applied.
"""
from __future__ import annotations

import pytest


class TestChangePasswordPage:
    @pytest.mark.smoke
    def test_get_renders(self, authenticated_client):
        response = authenticated_client.get('/change-password')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'name="current_password"' in html
        assert 'name="new_password"' in html
        assert 'name="confirm_password"' in html
        assert 'name="csrf_token"' in html

    def test_profile_link_is_reachable(self, authenticated_client):
        profile = authenticated_client.get('/profile')

        assert profile.status_code == 200
        assert '/change-password' in profile.get_data(as_text=True)


class TestChangePasswordSubmission:
    def test_valid_change_redirects_to_profile_and_applies(
        self, authenticated_client, db_session, test_user,
    ):
        response = authenticated_client.post('/change-password', data={
            'current_password': 'testpass123',
            'new_password': 'Brand-New-Pass9',
            'confirm_password': 'Brand-New-Pass9',
        })

        assert response.status_code == 302
        assert response.headers['Location'].endswith('/profile')
        db_session.refresh(test_user)
        assert test_user.check_password('Brand-New-Pass9')

    def test_wrong_current_password_keeps_the_old_one(
        self, authenticated_client, db_session, test_user,
    ):
        response = authenticated_client.post('/change-password', data={
            'current_password': 'not-the-password',
            'new_password': 'Brand-New-Pass9',
            'confirm_password': 'Brand-New-Pass9',
        })

        assert response.status_code == 200
        db_session.refresh(test_user)
        assert test_user.check_password('testpass123')

    def test_mismatched_confirmation_keeps_the_old_one(
        self, authenticated_client, db_session, test_user,
    ):
        response = authenticated_client.post('/change-password', data={
            'current_password': 'testpass123',
            'new_password': 'Brand-New-Pass9',
            'confirm_password': 'Different-Pass9',
        })

        assert response.status_code == 200
        db_session.refresh(test_user)
        assert test_user.check_password('testpass123')

    def test_weak_password_is_rejected(self, authenticated_client, db_session, test_user):
        response = authenticated_client.post('/change-password', data={
            'current_password': 'testpass123',
            'new_password': 'abc',
            'confirm_password': 'abc',
        })

        assert response.status_code == 200
        db_session.refresh(test_user)
        assert test_user.check_password('testpass123')
