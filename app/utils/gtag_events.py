"""
Cross-request GA4 event queueing.

Server-side code (e.g. a POST handler that redirects) can call
``queue_gtag_event(name, props)`` to fire a Google Analytics event on the
*next* page the user lands on. The base templates render the queued events
as a JSON literal which a small inline script consumes and pushes through
``gtag('event', ...)``.

The queue lives in the Flask session, so it survives the redirect but
cannot leak between users.
"""
from __future__ import annotations

from flask import session

_SESSION_KEY = '_gtag_events'
_MAX_QUEUED = 8


def queue_gtag_event(name: str, props: dict | None = None) -> None:
    """Schedule a GA4 event for the next page render.

    ``name`` must be a non-empty string (GA event name convention: snake_case,
    <40 chars). ``props`` is an optional dict of event parameters.
    """
    if not name or not isinstance(name, str):
        return
    queue = session.get(_SESSION_KEY, [])
    if not isinstance(queue, list):
        queue = []
    if len(queue) >= _MAX_QUEUED:
        return
    entry: dict = {'name': name[:40]}
    if props:
        # Only allow primitives + short strings to keep the session small.
        clean: dict = {}
        for key, value in props.items():
            if not isinstance(key, str) or len(clean) >= 10:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key[:40]] = value if not isinstance(value, str) else value[:100]
        if clean:
            entry['params'] = clean
    queue.append(entry)
    session[_SESSION_KEY] = queue


def consume_gtag_events() -> list[dict]:
    """Return queued events and clear the session entry.

    Designed to be called once per request by the layout template (via the
    ``pending_gtag_events`` template context).
    """
    queue = session.pop(_SESSION_KEY, None)
    if not queue or not isinstance(queue, list):
        return []
    return queue
