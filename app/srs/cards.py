"""Card-direction provisioning.

A word is studied in two recall directions (eng-rus and rus-eng), and
``UserWord.recalculate_status`` only calls a word learned once both of them
hold. Several paths used to create just one direction — the graded one — which
left the word permanently short of a real status, or created the sibling later
without recalculating and froze a status that had been derived from a single
row. Creating both up front keeps the word-level status meaningful.
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.srs.constants import DIRECTION_ENG_RUS, DIRECTION_RUS_ENG
from app.study.models import UserCardDirection

BOTH_DIRECTIONS = (DIRECTION_ENG_RUS, DIRECTION_RUS_ENG)


def ensure_card_directions(
    user_word: Any,
    source: Optional[str] = None,
) -> List[UserCardDirection]:
    """Make sure both recall directions exist for ``user_word``.

    Idempotent and race-safe (delegates to the savepoint-guarded
    ``UserCardDirection.get_or_create``). Refreshes the parent word status,
    because adding a direction can change it. Flushes only — the caller
    commits.
    """
    if user_word is None:
        return []

    directions = [
        UserCardDirection.get_or_create(user_word.id, direction, source=source)
        for direction in BOTH_DIRECTIONS
    ]
    user_word.recalculate_status()
    return directions
