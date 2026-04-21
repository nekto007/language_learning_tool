"""Plan-context helpers for linear daily plan slot URLs.

``LinearSlotKind`` enumerates the four baseline slot kinds. ``build_slot_url``
appends ``from=linear_plan&slot=<kind>`` to any base URL so downstream
lesson pages can detect plan entry and show plan-aware completion CTAs.

The builder preserves any pre-existing query-params (e.g.
``source=linear_plan_card`` on card lessons) and skips fragment-only URLs
like ``#book-select-modal`` where context is meaningless (no real page to
read the param). Empty / ``None`` URLs are returned unchanged.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLAN_CONTEXT_SOURCE = 'linear_plan'
FROM_QUERY_KEY = 'from'
SLOT_QUERY_KEY = 'slot'


class LinearSlotKind(str, Enum):
    """Canonical identifiers for baseline slot kinds on the linear spine."""

    CURRICULUM = 'curriculum'
    SRS = 'srs'
    BOOK = 'book'
    ERROR_REVIEW = 'error_review'


def build_slot_url(base_url: Optional[str], slot_kind: LinearSlotKind) -> Optional[str]:
    """Return ``base_url`` with plan-context query params appended.

    - ``None`` or empty string → returned unchanged.
    - Fragment-only URLs (``#book-select-modal``) → returned unchanged;
      they do not navigate to a page that could read the params.
    - Existing ``from``/``slot`` params are overwritten with plan values so
      callers cannot accidentally smuggle a stale context in.
    - Other existing query params are preserved.
    """
    if not base_url:
        return base_url
    if base_url.startswith('#'):
        return base_url

    parts = urlsplit(base_url)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in (FROM_QUERY_KEY, SLOT_QUERY_KEY)
    ]
    pairs.append((FROM_QUERY_KEY, PLAN_CONTEXT_SOURCE))
    pairs.append((SLOT_QUERY_KEY, slot_kind.value))
    new_query = urlencode(pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
