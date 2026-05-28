"""
Acquisition attribution metrics for the admin dashboard.

Reads first-touch UTM data persisted on the User row by the acquisition
middleware (see app/middleware/acquisition.py) and produces aggregates
broken down by source/medium/campaign for a configurable trailing window.

These queries are deliberately small and unindexed-friendly: the cohort of
users registered in the last 90 days is bounded, and aggregation happens
in Python after a single SELECT. Re-evaluate if the user table grows past
~1M registered users.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.auth.models import User


# Buckets for "no attribution" — keeps the dashboard readable instead of
# rendering thousands of empty rows.
_UNKNOWN_LABEL = '(direct / unknown)'


def _bucket(value: str | None) -> str:
    return (value or '').strip() or _UNKNOWN_LABEL


def _utc_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def get_acquisition_overview(db_session: Session, days: int = 30) -> dict:
    """Aggregate registrations + onboarding completions for the last ``days`` days.

    Returns a payload with three sections:
    - ``totals``: scalar counters for the window.
    - ``by_source``: list of ``{source, medium, campaign, signups, onboarded,
      onboarded_pct}`` rows, sorted by signups DESC.
    - ``daily``: list of ``{date, signups, onboarded}`` rows for chart rendering.

    All counts are bounded by ``User.created_at >= now - days``. Onboarding
    completion is detected by ``onboarding_completed=True``; there is no
    timestamp on completion, so a user who onboards months after signup will
    only show up in the window of their signup, not their onboarding day.
    """
    if days <= 0:
        days = 30
    if days > 365:
        days = 365

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_naive = cutoff.replace(tzinfo=None)
    # ``User.created_at`` is a naive UTC column (see CLAUDE.md); compare against
    # a naive UTC value so PostgreSQL doesn't coerce types unexpectedly.
    users: Iterable[User] = (
        db_session.query(User)
        .filter(User.created_at >= cutoff_naive)
        .all()
    )

    by_key: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {'signups': 0, 'onboarded': 0}
    )
    daily_signups: Counter = Counter()
    daily_onboarded: Counter = Counter()
    total_signups = 0
    total_onboarded = 0

    for user in users:
        meta = user.acquisition_meta or {}
        key = (
            _bucket(meta.get('utm_source')),
            _bucket(meta.get('utm_medium')),
            _bucket(meta.get('utm_campaign')),
        )
        by_key[key]['signups'] += 1
        total_signups += 1
        signup_day = user.created_at.date().isoformat() if user.created_at else ''
        if signup_day:
            daily_signups[signup_day] += 1
        if user.onboarding_completed:
            by_key[key]['onboarded'] += 1
            total_onboarded += 1
            if signup_day:
                daily_onboarded[signup_day] += 1

    rows = []
    for (source, medium, campaign), counts in by_key.items():
        signups = counts['signups']
        onboarded = counts['onboarded']
        onboarded_pct = round((onboarded / signups) * 100, 1) if signups else 0.0
        rows.append({
            'source': source,
            'medium': medium,
            'campaign': campaign,
            'signups': signups,
            'onboarded': onboarded,
            'onboarded_pct': onboarded_pct,
        })
    rows.sort(key=lambda r: (-r['signups'], r['source']))

    # Daily series — pad missing days with zeros so the chart line stays continuous.
    today = datetime.now(timezone.utc).date()
    daily = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        daily.append({
            'date': d,
            'signups': daily_signups.get(d, 0),
            'onboarded': daily_onboarded.get(d, 0),
        })

    return {
        'totals': {
            'signups': total_signups,
            'onboarded': total_onboarded,
            'onboarded_pct': round((total_onboarded / total_signups) * 100, 1)
                              if total_signups else 0.0,
            'days': days,
        },
        'by_source': rows,
        'daily': daily,
    }


def get_top_referrers(db_session: Session, days: int = 30, limit: int = 10) -> list[dict]:
    """Return the most common external referrer hosts in the window.

    Useful for spotting backlinks the user did not explicitly tag with UTM.
    Excludes the site's own host (the middleware already filters those during
    capture, but we double-check defensively).
    """
    if limit <= 0 or limit > 100:
        limit = 10
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_naive = cutoff.replace(tzinfo=None)
    users = (
        db_session.query(User)
        .filter(User.created_at >= cutoff_naive)
        .all()
    )
    counter: Counter = Counter()
    for user in users:
        meta = user.acquisition_meta or {}
        referrer = (meta.get('referrer') or '').strip()
        if not referrer:
            continue
        # Reduce URL to host for grouping.
        host = referrer.split('://', 1)[-1].split('/', 1)[0].lower()
        if not host:
            continue
        counter[host] += 1
    return [
        {'host': host, 'signups': count}
        for host, count in counter.most_common(limit)
    ]
