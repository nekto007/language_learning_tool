"""Normalise authored module prerequisites into the shape the parser reads.

``Module.check_prerequisites`` keeps only entries that are ``dict`` with
``type == 'module'`` and a numeric ``modules.id``. Authored JSON writes them as
level-relative slugs (``"module_3"``), which the parser silently drops — the
module then looks gated but is not (audit CNT-014).

Migration ``20260808_normalize_module_prerequisites`` fixed the rows that
existed. This is the same rule applied at the import boundary, so the next
re-import of a module JSON does not put the slugs straight back.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Matches the level-relative slugs authored content uses: module_3, module-3,
# "Module 3". The number is the module's `number` within the same level.
_SLUG_RE = re.compile(r'^module[_\-\s]*(\d+)$', re.IGNORECASE)

# Same bars the migrations write, and for the same reason: `min_score` must be
# explicit because a missing key defaults to PASSING_SCORE_PERCENT and is
# compared against an average that includes ungraded completions stuck at 0.
MIN_SCORE = 0
MIN_PROGRESS = 80


def normalize_prerequisites(
    prerequisites: Any,
    level_id: Optional[int],
) -> Any:
    """Return ``prerequisites`` with level-relative slugs resolved to module ids.

    Non-list values, dict entries and unresolvable slugs are returned
    unchanged — an authored intent we cannot resolve is better kept visible
    than deleted.
    """
    if not isinstance(prerequisites, list) or not prerequisites or level_id is None:
        return prerequisites

    from app.curriculum.models import Module

    rewritten: list[Any] = []
    for entry in prerequisites:
        match = _SLUG_RE.match(entry.strip()) if isinstance(entry, str) else None
        if match is None:
            rewritten.append(entry)
            continue

        target = Module.query.filter_by(
            level_id=level_id, number=int(match.group(1)),
        ).first()
        if target is None:
            logger.warning(
                "prerequisite slug %r does not resolve inside level %s — kept verbatim",
                entry, level_id,
            )
            rewritten.append(entry)
            continue

        rewritten.append({
            'type': 'module',
            'id': int(target.id),
            'min_score': MIN_SCORE,
            'min_progress': MIN_PROGRESS,
            'legacy_slug': entry,
        })

    return rewritten
