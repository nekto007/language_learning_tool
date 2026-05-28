"""Tests for acquisition_metrics service."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.admin.services.acquisition_metrics import (
    _UNKNOWN_LABEL,
    get_acquisition_overview,
    get_top_referrers,
)
from app.auth.models import User


def _make_user(db_session, *, acq=None, onboarded=False, days_ago=0):
    """Create a user with the given acquisition_meta and signup age."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'acq_{suffix}',
        email=f'acq_{suffix}@example.test',
        active=True,
        onboarding_completed=onboarded,
        acquisition_meta=acq,
    )
    user.set_password('pwd')
    db_session.add(user)
    db_session.flush()
    if days_ago:
        user.created_at = datetime.utcnow() - timedelta(days=days_ago)
    db_session.commit()
    return user


def test_overview_empty(db_session):
    overview = get_acquisition_overview(db_session, days=30)
    assert overview['totals']['signups'] >= 0
    assert overview['totals']['days'] == 30
    assert isinstance(overview['by_source'], list)
    assert len(overview['daily']) == 30


def test_overview_groups_by_utm(db_session):
    _make_user(db_session, acq={'utm_source': 'telegram', 'utm_medium': 'channel', 'utm_campaign': 'launch'})
    _make_user(db_session, acq={'utm_source': 'telegram', 'utm_medium': 'channel', 'utm_campaign': 'launch'})
    _make_user(db_session, acq={'utm_source': 'google', 'utm_medium': 'organic'}, onboarded=True)

    overview = get_acquisition_overview(db_session, days=30)
    tg_row = next((r for r in overview['by_source']
                   if r['source'] == 'telegram' and r['campaign'] == 'launch'), None)
    assert tg_row is not None
    assert tg_row['signups'] >= 2
    google_row = next((r for r in overview['by_source'] if r['source'] == 'google'), None)
    assert google_row is not None
    assert google_row['onboarded'] >= 1


def test_overview_unknown_bucket(db_session):
    _make_user(db_session, acq=None)
    _make_user(db_session, acq={})
    overview = get_acquisition_overview(db_session, days=30)
    unknown_rows = [r for r in overview['by_source'] if r['source'] == _UNKNOWN_LABEL]
    assert unknown_rows, 'rows without utm_source must be bucketed under unknown'


def test_overview_clamps_days(db_session):
    assert get_acquisition_overview(db_session, days=0)['totals']['days'] == 30
    assert get_acquisition_overview(db_session, days=10_000)['totals']['days'] == 365


def test_top_referrers_groups_by_host(db_session):
    _make_user(db_session, acq={'referrer': 'https://t.me/some_channel'})
    _make_user(db_session, acq={'referrer': 'https://t.me/some_channel/123'})
    _make_user(db_session, acq={'referrer': 'https://reddit.com/r/russian'})

    referrers = get_top_referrers(db_session, days=30, limit=10)
    hosts = {r['host'] for r in referrers}
    assert 't.me' in hosts
    assert 'reddit.com' in hosts


@pytest.mark.smoke
def test_admin_route_returns_200(admin_client, db_session):
    _make_user(db_session, acq={'utm_source': 'telegram', 'utm_medium': 'channel'})
    response = admin_client.get('/admin/acquisition')
    assert response.status_code == 200
    assert b'Acquisition' in response.data


def test_admin_route_rejects_non_admin(client):
    response = client.get('/admin/acquisition')
    # Either 302 redirect to login or 403 — both prove the endpoint is gated.
    assert response.status_code in (302, 401, 403)
