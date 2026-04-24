"""Smoke tests for the UserXP -> UserStatistics data sync."""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.achievements.models import UserStatistics
from app.auth.models import User
from app.study.models import UserXP
from app.study.xp_sync import sync_user_xp_to_statistics
from app.utils.db import db


@pytest.fixture(autouse=True)
def _ensure_sentinel_column(app):
    """Backfill the sentinel column on pre-existing local test databases.

    Fresh CI databases get the column via ``db.create_all()``; dev boxes that
    created the schema before this column existed need a one-shot ALTER.
    """
    with app.app_context():
        db.session.execute(sa.text(
            "ALTER TABLE user_xp ADD COLUMN IF NOT EXISTS "
            "synced_to_stats BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        db.session.commit()


def _make_user(db_session) -> User:
    username = f'xpsync_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('x')
    db_session.add(user)
    db_session.flush()
    return user


def _run_sync(db_session):
    db_session.flush()
    sync_user_xp_to_statistics(db_session)
    db_session.expire_all()


def test_sync_creates_missing_statistics_row(db_session):
    user = _make_user(db_session)
    db_session.add(UserXP(user_id=user.id, total_xp=120))

    _run_sync(db_session)

    stats = UserStatistics.query.filter_by(user_id=user.id).one()
    assert stats.total_xp == 120


def test_sync_adds_legacy_xp_on_top_of_existing_stats(db_session):
    user = _make_user(db_session)
    db_session.add(UserXP(user_id=user.id, total_xp=50))
    db_session.add(UserStatistics(user_id=user.id, total_xp=200))

    _run_sync(db_session)

    stats = UserStatistics.query.filter_by(user_id=user.id).one()
    assert stats.total_xp == 250


def test_sync_is_idempotent(db_session):
    user = _make_user(db_session)
    db_session.add(UserXP(user_id=user.id, total_xp=30))

    _run_sync(db_session)
    _run_sync(db_session)
    _run_sync(db_session)

    stats = UserStatistics.query.filter_by(user_id=user.id).one()
    assert stats.total_xp == 30

    ux = UserXP.query.filter_by(user_id=user.id).one()
    assert ux.synced_to_stats is True


def test_sync_skips_rows_already_marked(db_session):
    user = _make_user(db_session)
    db_session.add(UserXP(user_id=user.id, total_xp=999, synced_to_stats=True))
    db_session.add(UserStatistics(user_id=user.id, total_xp=10))

    _run_sync(db_session)

    stats = UserStatistics.query.filter_by(user_id=user.id).one()
    assert stats.total_xp == 10


def test_sync_handles_multiple_users(db_session):
    u1 = _make_user(db_session)
    u2 = _make_user(db_session)
    u3 = _make_user(db_session)
    db_session.add(UserXP(user_id=u1.id, total_xp=100))
    db_session.add(UserXP(user_id=u2.id, total_xp=0))
    db_session.add(UserXP(user_id=u3.id, total_xp=75))
    db_session.add(UserStatistics(user_id=u2.id, total_xp=5))

    _run_sync(db_session)

    totals = {
        s.user_id: s.total_xp
        for s in UserStatistics.query.filter(
            UserStatistics.user_id.in_([u1.id, u2.id, u3.id])
        ).all()
    }
    assert totals[u1.id] == 100
    assert totals[u2.id] == 5   # zero legacy -> no-op
    assert totals[u3.id] == 75

    assert all(
        ux.synced_to_stats
        for ux in UserXP.query.filter(
            UserXP.user_id.in_([u1.id, u2.id, u3.id])
        ).all()
    )
