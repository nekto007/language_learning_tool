"""Landing browser-session cohorts, independent of learner activity metrics."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import DBAPIError

from app.landing.analytics import LandingVisit, analytics_table_missing, logger
from app.landing.previews import PREVIEWS_BY_ID


def _percentage(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def _counts(visits):
    total = len(visits)
    started = answered = opened = registered = correct = all_registered = clicks = 0
    for visit in visits:
        all_registered += visit.registered_at is not None
        clicks += visit.registration_clicked_at is not None
        if visit.started_at is None:
            continue
        started += 1
        if visit.answered_at is None or visit.answered_at < visit.started_at:
            continue
        answered += 1
        correct += visit.first_correct is True
        if visit.registration_opened_at is None or visit.registration_opened_at < visit.answered_at:
            continue
        opened += 1
        if visit.registered_at is not None and visit.registered_at >= visit.registration_opened_at:
            registered += 1
    return {
        'visits': total, 'started': started, 'answered': answered, 'opened': opened,
        'registered': registered, 'all_registered': all_registered, 'clicked': clicks,
        'first_correct': correct,
        'started_pct': _percentage(started, total),
        'answered_pct': _percentage(answered, started),
        'opened_pct': _percentage(opened, answered),
        'registered_pct': _percentage(registered, opened),
        'conversion_pct': _percentage(registered, total),
        'correct_pct': _percentage(correct, answered),
    }


def get_landing_overview(db_session, days=30):
    """All steps belong to sessions first seen inside the selected period.

    Registration timestamps outside the period are retained for those cohorts.
    These counts represent signed browser sessions, never unique people.
    """
    days = max(1, min(days, 365))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    try:
        # A rolling deployment may serve the admin before the new migration.
        # Preserve the caller's transaction if only this table is absent.
        with db_session.begin_nested():
            visits = db_session.query(LandingVisit).filter(LandingVisit.created_at >= cutoff).all()
    except DBAPIError as exc:
        if not analytics_table_missing(exc):
            raise
        logger.warning('Landing analytics table is not installed; dashboard unavailable')
        return {'available': False, 'totals': _counts([]), 'variants': [], 'by_source': [], 'days': days}
    variants = defaultdict(list)
    sources = defaultdict(list)
    for visit in visits:
        variants[visit.preview_id].append(visit)
        key = tuple(value or '(direct / unknown)' for value in (visit.source, visit.medium, visit.campaign))
        sources[key].append(visit)
    return {
        'available': True, 'days': days, 'totals': _counts(visits),
        'variants': [dict(preview_id=key, prompt=PREVIEWS_BY_ID.get(key, {}).get('prompt', key),
                          **_counts(rows)) for key, rows in sorted(variants.items())],
        'by_source': [
            dict(source=key[0], medium=key[1], campaign=key[2], **_counts(rows))
            for key, rows in sorted(sources.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
    }
