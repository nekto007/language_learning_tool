"""
Loader for curated word_contrasts.json into the WordContrast table.

The seed file lives at ``app/seed_data/word_contrasts.json`` and ships
hand-picked pairs of commonly-confused words. The loader resolves each
entry's ``a`` and ``b`` to ``CollectionWords.english_word``, orders the
two IDs to satisfy the (a<b) uniqueness invariant, and inserts only
missing pairs — so this can run on every deploy without producing
duplicates or noise.

Words that aren't in the dictionary yet are skipped silently and counted
in the return tuple so a deploy log surfaces "12 created, 2 skipped (word
not in DB)" instead of crashing the command.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.utils.db import db
from app.words.models import CollectionWords, WordContrast

logger = logging.getLogger(__name__)


def _seed_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), 'seed_data', 'word_contrasts.json')


def _lookup_word(name: str) -> CollectionWords | None:
    cleaned = (name or '').strip()
    if not cleaned:
        return None
    return (
        CollectionWords.query
        .filter(func.lower(CollectionWords.english_word) == cleaned.lower())
        .first()
    )


def seed_word_contrasts(path: str | None = None) -> Tuple[int, int, int]:
    """Load curated contrast pairs. Returns ``(created, skipped, missing)``.

    - ``created``: rows inserted by this call.
    - ``skipped``: pairs already present (idempotent re-runs).
    - ``missing``: pairs skipped because at least one side wasn't in the
      dictionary yet (logged at warning level so the deploy log surfaces them).
    """
    path = path or _seed_path()
    if not os.path.exists(path):
        logger.warning('word_contrasts.json not found at %s', path)
        return 0, 0, 0

    with open(path, 'r', encoding='utf-8') as fh:
        entries = json.load(fh)

    created = 0
    skipped = 0
    missing = 0

    for entry in entries:
        a_name = entry.get('a')
        b_name = entry.get('b')
        note = (entry.get('note') or '').strip()
        if not a_name or not b_name or not note:
            missing += 1
            continue

        word_a = _lookup_word(a_name)
        word_b = _lookup_word(b_name)
        if not word_a or not word_b or word_a.id == word_b.id:
            logger.info('Skipping contrast %r ↔ %r — word missing in DB', a_name, b_name)
            missing += 1
            continue

        # Enforce (a < b) canonical ordering so dedup works regardless of
        # which side the seed entry put first.
        low_id, high_id = sorted((word_a.id, word_b.id))

        existing = (
            WordContrast.query
            .filter_by(word_a_id=low_id, word_b_id=high_id)
            .first()
        )
        if existing:
            skipped += 1
            continue

        row = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru=note)
        db.session.add(row)
        try:
            db.session.commit()
            created += 1
        except IntegrityError:
            # Race or constraint hit (e.g. retry after a half-rolled-back txn);
            # treat as already present.
            db.session.rollback()
            skipped += 1

    return created, skipped, missing
