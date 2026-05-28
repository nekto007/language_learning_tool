"""Per-request memoization via ``flask.g``.

Use when the same function is called multiple times within one Flask
application context with the same arguments AND the result cannot change
mid-request. Outside of an active application context the cache is a
no-op (function still runs).

``flask.g`` is reset between requests, so cached values never leak
across users or requests. Within one request the cache holds — perfect
for read-only lookups during plan assembly, dashboard rendering, etc.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional


def _get_cache() -> Optional[dict]:
    try:
        from flask import g, has_app_context
    except ImportError:
        return None
    if not has_app_context():
        return None
    if not hasattr(g, '_request_cache'):
        g._request_cache = {}
    return g._request_cache


_MISSING = object()


def request_memoize(key_fn: Optional[Callable[..., Any]] = None) -> Callable:
    """Decorator: cache the function result per Flask app context.

    ``key_fn(*args, **kwargs)`` should return a hashable cache key. When
    omitted, falls back to ``(args, frozenset(kwargs.items()))`` which only
    works if all arguments are themselves hashable (no db sessions, no
    lists). Most callers should pass an explicit ``key_fn`` selecting the
    identifying argument (e.g. ``lambda user_id, *_a, **_k: user_id``).
    """
    def _wrap(func: Callable) -> Callable:
        @wraps(func)
        def _inner(*args, **kwargs):
            cache = _get_cache()
            if cache is None:
                return func(*args, **kwargs)
            if key_fn is not None:
                key = (func.__qualname__, key_fn(*args, **kwargs))
            else:
                key = (func.__qualname__, args, tuple(sorted(kwargs.items())))
            cached = cache.get(key, _MISSING)
            if cached is _MISSING:
                cached = func(*args, **kwargs)
                cache[key] = cached
            return cached
        return _inner
    return _wrap
