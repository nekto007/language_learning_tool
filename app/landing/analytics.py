"""Small first-party landing funnel; stores browser sessions, never answer text."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from flask import jsonify, request, session
from sqlalchemy.exc import DBAPIError

from app import limiter
from app.landing import landing_bp
from app.landing.previews import PREVIEWS_BY_ID
from app.utils.db import db

logger = logging.getLogger(__name__)

PREVIEW_IDS = frozenset(PREVIEWS_BY_ID)
_SESSION_KEY = 'landing_visit_id'
_EVENTS = frozenset({'preview_started', 'preview_answered', 'registration_clicked'})


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LandingVisit(db.Model):
    __tablename__ = 'landing_visits'

    id = db.Column(db.String(43), primary_key=True)
    preview_id = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now, index=True)
    started_at = db.Column(db.DateTime)
    answered_at = db.Column(db.DateTime)
    registration_clicked_at = db.Column(db.DateTime)
    registration_opened_at = db.Column(db.DateTime)
    registered_at = db.Column(db.DateTime)
    first_correct = db.Column(db.Boolean)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), index=True)
    source = db.Column(db.String(200))
    medium = db.Column(db.String(200))
    campaign = db.Column(db.String(200))


def analytics_table_missing(exc: DBAPIError) -> bool:
    """Only a missing *analytics* table may degrade during a rolling deploy."""
    original = exc.orig
    code = getattr(original, 'pgcode', None) or getattr(original, 'sqlstate', None)
    if code == '42P01':
        diagnostic = getattr(original, 'diag', None)
        table = getattr(diagnostic, 'table_name', None)
        return table == 'landing_visits' or 'landing_visits' in str(original)
    return 'no such table: landing_visits' in str(original).lower()


def _current_visit(*, lock=False):
    visit_id = session.get(_SESSION_KEY)
    if not isinstance(visit_id, str) or len(visit_id) != 43:
        return None
    query = LandingVisit.query.filter_by(id=visit_id)
    if lock:
        query = query.with_for_update()
    return query.first()


def get_or_create_visit(preview_id: str) -> LandingVisit | None:
    """Keep one variant across reloads; a logged-out, already-linked visit restarts.

    This is called from the landing GET, before any registration transaction.
    The signed Flask session is the only authority for the random visit id.
    """
    if preview_id not in PREVIEW_IDS:
        raise ValueError('Unknown landing preview')
    try:
        visit = _current_visit()
        if visit is not None and visit.registered_at is None:
            return visit
        meta = session.get('acq_meta')
        meta = meta if isinstance(meta, dict) else {}

        def attribution(key):
            value = meta.get(key)
            return value.strip()[:200] or None if isinstance(value, str) else None

        visit = LandingVisit(
            id=secrets.token_urlsafe(32), preview_id=preview_id,
            source=attribution('utm_source'), medium=attribution('utm_medium'),
            campaign=attribution('utm_campaign'),
        )
        db.session.add(visit)
        db.session.commit()
        session[_SESSION_KEY] = visit.id
        return visit
    except DBAPIError as exc:
        if not analytics_table_missing(exc):
            raise
        db.session.rollback()
        logger.warning('Landing analytics table is not installed; serving landing without tracking')
        return None


def record_registration_open() -> None:
    """Record an actual signup GET from the preview CTA, once per session."""
    try:
        visit = _current_visit(lock=True)
        if visit is not None and visit.registered_at is None and (
            visit.registration_opened_at is None
            or (visit.answered_at is not None and visit.registration_opened_at < visit.answered_at)
        ):
            visit.registration_opened_at = _now()
            db.session.commit()
    except DBAPIError as exc:
        if not analytics_table_missing(exc):
            raise
        db.session.rollback()
        logger.warning('Landing analytics table is not installed; signup remains available')


def link_registration(user) -> None:
    """Join the pending signup transaction without committing it.

    A savepoint contains a missing-table error so it cannot roll back the User.
    Keep the session id for requests already sent with fetch(keepalive=True).
    Ordinary signup from a landing session is recorded too, separately from the
    ordered preview funnel. A row can be linked to only its first registration.
    """
    if not session.get(_SESSION_KEY):
        return
    try:
        with db.session.begin_nested():
            visit = _current_visit(lock=True)
            if visit is not None and visit.registered_at is None:
                visit.user_id = user.id
                visit.registered_at = _now()
                db.session.flush()
    except DBAPIError as exc:
        if not analytics_table_missing(exc):
            raise
        logger.warning('Landing analytics table is not installed; signup link omitted')


@landing_bp.route('/landing/events', methods=['POST'])
@limiter.limit('30 per minute')
def preview_event():
    """Accept only the three bounded events for this session's rendered variant."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {'event', 'preview_id', 'correct'}:
        return jsonify(error='Invalid event'), 400
    event = payload.get('event')
    preview_id = payload.get('preview_id')
    if not isinstance(event, str) or event not in _EVENTS:
        return jsonify(error='Invalid event'), 400
    if not isinstance(preview_id, str) or preview_id not in PREVIEW_IDS:
        return jsonify(error='Invalid preview'), 400
    if event == 'preview_answered':
        if type(payload.get('correct')) is not bool:
            return jsonify(error='Answer correctness must be boolean'), 400
    elif 'correct' in payload:
        return jsonify(error='Unexpected correctness'), 400
    try:
        visit = _current_visit(lock=True)
        if visit is None or visit.preview_id != preview_id:
            return jsonify(error='Unknown visit'), 403
        now = _now()
        if event == 'preview_started' and visit.started_at is None:
            visit.started_at = now
        elif event == 'preview_answered' and visit.answered_at is None:
            # An answer proves interaction started. The answer request may beat
            # the focus request over the network; do not lose that valid start.
            visit.started_at = visit.started_at or now
            visit.answered_at = now
            visit.first_correct = payload['correct']
        elif event == 'registration_clicked' and visit.registration_clicked_at is None:
            visit.registration_clicked_at = now
        db.session.commit()
    except DBAPIError as exc:
        if not analytics_table_missing(exc):
            raise
        db.session.rollback()
        logger.warning('Landing analytics table is not installed; event omitted')
        return '', 204
    return '', 204
