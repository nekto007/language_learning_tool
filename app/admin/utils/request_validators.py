"""Request-argument validators for admin routes.

Centralizes parsing of query-string parameters with strict validation:
unparseable integers, out-of-range values, or invalid enum members raise
HTTP 400 instead of silently degrading.
"""
from enum import Enum
from typing import Optional, Sequence, Type

from flask import abort, request

from app.utils.validators import validate_enum


def get_int_arg(
    name: str,
    default: Optional[int] = None,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
) -> Optional[int]:
    """Parse a query-string integer or abort(400).

    Empty/missing values return *default* (no error). Non-empty values must
    parse as int and fall within [min_val, max_val] when provided.
    """
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        abort(400, description=f"Invalid integer value for '{name}': {raw!r}")
    if min_val is not None and value < min_val:
        abort(400, description=f"'{name}' must be >= {min_val} (got {value})")
    if max_val is not None and value > max_val:
        abort(400, description=f"'{name}' must be <= {max_val} (got {value})")
    return value


def get_enum_arg(
    name: str,
    enum_cls: Type[Enum],
    default: Optional[str] = None,
) -> Optional[str]:
    """Return the raw string if it is a valid member of *enum_cls*; else 400."""
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    if not validate_enum(raw, enum_cls):
        allowed = ", ".join(member.value for member in enum_cls)
        abort(
            400,
            description=f"Invalid value for '{name}': {raw!r}. Allowed: {allowed}",
        )
    return raw


def get_choice_arg(
    name: str,
    choices: Sequence[str],
    default: Optional[str] = None,
) -> Optional[str]:
    """Return *raw* if in *choices*, else 400. Empty/missing returns *default*."""
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    if raw not in choices:
        allowed = ", ".join(choices)
        abort(
            400,
            description=f"Invalid value for '{name}': {raw!r}. Allowed: {allowed}",
        )
    return raw
