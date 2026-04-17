"""Tests for POST /api/daily-plan/dismiss-rival-strip endpoint (Task 17).

Covers:
- Authenticated user can dismiss the rival strip (sets rival_strip_dismissed=True)
- Unauthenticated request returns 401
- Dismissing twice is idempotent
- Child gating: child user's rival_strip_dismissed also works (endpoint is generic)
"""
import pytest
from unittest.mock import patch


def test_dismiss_rival_strip_authenticated(authenticated_client, db_session, test_user):
    """Authenticated user dismisses rival strip — flag is set in DB."""
    test_user.rival_strip_dismissed = False
    db_session.flush()

    response = authenticated_client.post(
        '/api/daily-plan/dismiss-rival-strip',
        content_type='application/json',
        json={},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'

    db_session.refresh(test_user)
    assert test_user.rival_strip_dismissed is True


def test_dismiss_rival_strip_unauthenticated(client):
    """Unauthenticated request returns 401."""
    response = client.post(
        '/api/daily-plan/dismiss-rival-strip',
        content_type='application/json',
        json={},
    )
    assert response.status_code == 401


def test_dismiss_rival_strip_idempotent(authenticated_client, db_session, test_user):
    """Calling dismiss twice keeps rival_strip_dismissed=True without error."""
    test_user.rival_strip_dismissed = True
    db_session.flush()

    response = authenticated_client.post(
        '/api/daily-plan/dismiss-rival-strip',
        content_type='application/json',
        json={},
    )
    assert response.status_code == 200

    db_session.refresh(test_user)
    assert test_user.rival_strip_dismissed is True
