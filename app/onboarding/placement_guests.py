"""Short-lived anonymous ownership, independent of registration credentials."""

from __future__ import annotations

from datetime import timedelta
import json

import click
from flask.cli import with_appcontext
import hashlib
import secrets

from flask import current_app, request, session
from flask_login import current_user
from flask_limiter.util import get_remote_address

from app.onboarding.placement_engine import PlacementError
from app.onboarding.placement_models import PlacementAttempt, PlacementGuest, utcnow
from app.utils.db import db


def guest_actor(create: bool = True) -> str | None:
    token = session.get("placement_guest") or request.cookies.get("llt_placement_guest")
    key = hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) and len(token) <= 80 else None
    guest = db.session.get(PlacementGuest, key) if key else None
    if guest is not None and guest.expires_at > utcnow():
        session["placement_guest"] = token
        return key
    if not create:
        return None
    token = secrets.token_urlsafe(32)
    key = hashlib.sha256(token.encode()).hexdigest()
    db.session.add(PlacementGuest(key=key, expires_at=utcnow() + timedelta(days=7)))
    db.session.commit()
    session["placement_guest"] = token
    session.pop("placement_handoff", None)
    return key


def web_actor() -> int | str:
    if current_user.is_authenticated:
        if request.headers.get("X-LLT-Placement-Guest") == "1":
            raise PlacementError("access_denied", 403)
        return current_user.id
    if request.headers.get("X-LLT-Account-ID"):
        raise PlacementError("access_denied", 403)
    # API calls never manufacture a new anonymous identity on expired/stale pages.
    key = guest_actor(create=False)
    if key is None:
        raise PlacementError("guest_expired", 409)
    return key


def web_rate_key() -> str:
    return (
        f"placement:user:{current_user.id}" if current_user.is_authenticated else f"placement:ip:{get_remote_address()}"
    )


def claim_after_login(sender: object, user: object, **extra: object) -> None:
    """Explicit pre-login handoff transfers ownership, never silently changes level."""
    expected = session.get("placement_handoff")
    key = guest_actor(create=False)
    if not expected or expected != key or not getattr(user, "id", None):
        return
    try:
        from app.onboarding.placement_engine import _owner

        _owner(user.id)
        guest = db.session.query(PlacementGuest).filter_by(key=key).with_for_update().one_or_none()
        if guest is None:
            return
        rows = db.session.query(PlacementAttempt).filter_by(guest_key=key).with_for_update().all()
        has_active = db.session.query(PlacementAttempt.id).filter_by(user_id=user.id, status="active").first()
        for row in rows:
            if row.status == "active" and has_active:
                row.status = "abandoned"
            row.user_id = user.id
            row.guest_key = None
        db.session.flush()
        db.session.delete(guest)
        db.session.commit()
        session.pop("placement_guest", None)
        session.pop("placement_handoff", None)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Placement handoff failed for account %s", user.id)


def cleanup_guests(limit: int = 500) -> int:
    """Bounded cleanup; caller commits. Claimed attempts have no guest FK."""
    rows = (
        db.session.query(PlacementGuest)
        .filter(PlacementGuest.expires_at <= utcnow())
        .order_by(PlacementGuest.expires_at)
        .limit(limit)
        .all()
    )
    for row in rows:
        db.session.delete(row)
    db.session.flush()
    return len(rows)


@click.command('placement-guests-cleanup')
@click.option('--apply', is_flag=True)
@click.option('--limit', type=click.IntRange(1, 5000), default=500)
@with_appcontext
def cleanup_command(apply: bool, limit: int) -> None:
    """Remove expired anonymous attempts in bounded batches; dry-run by default."""
    count = PlacementGuest.query.filter(PlacementGuest.expires_at <= utcnow()).count()
    removed = cleanup_guests(limit) if apply else 0
    if apply:
        db.session.commit()
    click.echo(json.dumps({'applied': apply, 'expired': count, 'removed': removed}))
