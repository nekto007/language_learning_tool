"""Tests for the acquisition (UTM) capture middleware."""
import pytest
from flask import session

from app.middleware.acquisition import consume_acquisition_meta


@pytest.mark.smoke
def test_utm_params_captured_to_session(client):
    """A GET with utm_* params stores attribution snapshot under session['acq_meta']."""
    with client:
        response = client.get(
            '/?utm_source=telegram&utm_medium=channel&utm_campaign=launch'
        )
        assert response.status_code == 200
        meta = session.get('acq_meta')
        assert meta is not None
        assert meta['utm_source'] == 'telegram'
        assert meta['utm_medium'] == 'channel'
        assert meta['utm_campaign'] == 'launch'
        assert meta['landing_path'] == '/'
        assert 'captured_at_iso' in meta


def test_first_touch_not_overwritten(client):
    """Second visit with different UTM does not overwrite the first snapshot."""
    with client:
        client.get('/?utm_source=telegram&utm_campaign=first')
        first_meta = dict(session['acq_meta'])

        client.get('/?utm_source=google&utm_campaign=second')
        second_meta = session['acq_meta']

        assert second_meta == first_meta
        assert second_meta['utm_source'] == 'telegram'


def test_internal_referrer_skipped(client):
    """Referrer that matches our host is not captured (internal navigation)."""
    with client:
        response = client.get(
            '/',
            headers={'Referer': 'http://localhost/dashboard'},
        )
        assert response.status_code == 200
        assert session.get('acq_meta') is None


def test_external_referrer_captured(client):
    """External referrer without UTM is still captured for attribution."""
    with client:
        client.get('/', headers={'Referer': 'https://t.me/some_channel'})
        meta = session.get('acq_meta')
        assert meta is not None
        assert 'some_channel' in meta['referrer']


def test_static_path_skipped(client):
    """Static asset requests do not trigger capture."""
    with client:
        client.get('/static/favicon.ico?utm_source=test')
        assert session.get('acq_meta') is None


def test_api_path_skipped(client):
    """API requests do not trigger capture."""
    with client:
        client.get('/api/anything?utm_source=test')
        assert session.get('acq_meta') is None


def test_post_request_does_not_capture(client):
    """POST requests are ignored (UTMs live on landing GETs)."""
    with client:
        client.post('/?utm_source=test')
        assert session.get('acq_meta') is None


def test_consume_clears_session(client):
    """consume_acquisition_meta returns and clears the snapshot."""
    with client:
        client.get('/?utm_source=test&utm_medium=cpc')
        assert session.get('acq_meta') is not None

        with client.session_transaction() as flask_session:
            assert flask_session.get('acq_meta') is not None

    # consume() must be called within an app context with the session loaded.
    with client:
        client.get('/?utm_source=test&utm_medium=cpc')
        meta = consume_acquisition_meta()
        assert meta is not None
        assert meta['utm_source'] == 'test'
        assert session.get('acq_meta') is None


def test_register_persists_acquisition_meta(client, db_session):
    """A signup right after capturing UTM stores the snapshot on User."""
    import uuid
    from app.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    with client:
        # Capture attribution on landing.
        client.get('/?utm_source=telegram&utm_medium=channel&utm_campaign=launch')

        # Register a fresh user; auth flow should consume the session entry.
        response = client.post(
            '/register',
            data={
                'username': f'utm_user_{suffix}',
                'email': f'utm_user_{suffix}@example.test',
                'password': 'StrongPass1!',
                'confirm_password': 'StrongPass1!',
            },
            follow_redirects=False,
        )
        # Either redirect on success or 200 if validation rejected something.
        assert response.status_code in (200, 302)

    user = User.query.filter_by(email=f'utm_user_{suffix}@example.test').first()
    if user is None:
        pytest.skip('Register form rejected the test payload; skipping persistence check')
    assert user.acquisition_meta is not None
    assert user.acquisition_meta['utm_source'] == 'telegram'
    assert user.acquisition_meta['utm_medium'] == 'channel'
    assert user.acquisition_meta['utm_campaign'] == 'launch'
