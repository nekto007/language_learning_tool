"""Curated themed word sets — «Цвета», «Одежда», «Еда».

A set is the editorially controlled group a learner browses and quizzes. It is
deliberately not :class:`~app.words.models.Topic`: topics are an open,
machine-populated space where the vast majority of rows hold a single word, so
they can carry vocabulary but cannot be shown as a catalogue.

Browsing and progress live here, plus the one learner-initiated write (adding
a set's words to the study list). Editing a set's identity or membership is an
admin action and lives in the admin section.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func

from app.study.models import WordSet, WordSetQuizResult, WordSetWord
from app.utils.db import db
from app.words.models import CollectionWords


class WordSetService:
    """Read-side queries for curated word sets."""

    @staticmethod
    def get_set(slug: str, *, include_unpublished: bool = False) -> Optional[WordSet]:
        """Return a set by slug, or None.

        Unpublished sets are drafts: invisible to learners, reachable by admins
        so a set can be reviewed before it goes live.
        """
        query = WordSet.query.filter(WordSet.slug == slug)
        if not include_unpublished:
            query = query.filter(WordSet.is_published.is_(True))
        return query.first()

    @staticmethod
    def get_words(set_id: int) -> List[CollectionWords]:
        """Words of a set in curated order, ready for the quiz generator.

        Words without a translation are dropped here rather than downstream:
        they cannot become a question *or* a distractor, and letting them
        through would silently shrink the quiz.
        """
        rows = (
            db.session.query(CollectionWords)
            .join(WordSetWord, WordSetWord.word_id == CollectionWords.id)
            .filter(
                WordSetWord.set_id == set_id,
                CollectionWords.russian_word.isnot(None),
                CollectionWords.russian_word != '',
            )
            .order_by(WordSetWord.order_index, CollectionWords.english_word)
            .all()
        )
        return rows

    @staticmethod
    def list_published(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """All published sets with their word count and the user's best score.

        Counts come from two grouped queries, not from ``len(set.entries)`` per
        row: the page this feeds replaces one that issued a query per group and
        became unusable once the underlying table grew.
        """
        sets = (
            WordSet.query
            .filter(WordSet.is_published.is_(True))
            .order_by(WordSet.sort_order, WordSet.name)
            .all()
        )
        if not sets:
            return []

        set_ids = [word_set.id for word_set in sets]

        counts = dict(
            db.session.query(WordSetWord.set_id, func.count(WordSetWord.id))
            .filter(WordSetWord.set_id.in_(set_ids))
            .group_by(WordSetWord.set_id)
            .all()
        )

        best_scores: Dict[int, float] = {}
        attempts: Dict[int, int] = {}
        if user_id is not None:
            rows = (
                db.session.query(
                    WordSetQuizResult.set_id,
                    func.max(WordSetQuizResult.score_percentage),
                    func.count(WordSetQuizResult.id),
                )
                .filter(
                    WordSetQuizResult.user_id == user_id,
                    WordSetQuizResult.set_id.in_(set_ids),
                )
                .group_by(WordSetQuizResult.set_id)
                .all()
            )
            for set_id, best, played in rows:
                best_scores[set_id] = float(best or 0)
                attempts[set_id] = int(played or 0)

        return [
            {
                'set': word_set,
                'word_count': int(counts.get(word_set.id, 0)),
                'best_score': best_scores.get(word_set.id),
                'attempts': attempts.get(word_set.id, 0),
            }
            for word_set in sets
        ]

    @staticmethod
    def get_progress(user_id: int, set_id: int) -> Dict[str, Any]:
        """Best score and attempt count for one set."""
        best, played = (
            db.session.query(
                func.max(WordSetQuizResult.score_percentage),
                func.count(WordSetQuizResult.id),
            )
            .filter(
                WordSetQuizResult.user_id == user_id,
                WordSetQuizResult.set_id == set_id,
            )
            .first()
        ) or (None, 0)
        return {
            'best_score': float(best) if best is not None else None,
            'attempts': int(played or 0),
        }

    @staticmethod
    def completed_on(user_id: int, day) -> bool:
        """True when the user finished any themed quiz on the given local day.

        ``day`` is a user-local date; callers resolve it through
        ``get_user_local_date`` so the daily plan and XP agree on where the day
        boundary sits.
        """
        from datetime import datetime, time

        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        return db.session.query(
            db.session.query(WordSetQuizResult.id)
            .filter(
                WordSetQuizResult.user_id == user_id,
                WordSetQuizResult.completed_at >= start,
                WordSetQuizResult.completed_at <= end,
            )
            .exists()
        ).scalar()

    @staticmethod
    def add_to_study(set_id: int, user_id: int) -> int:
        """Add every word of a set to the user's study list. Returns how many.

        Mirrors ``CollectionTopicService.add_topic_to_study`` — same default
        deck bookkeeping — so a word added from a set behaves exactly like one
        added from a topic.
        """
        from app.study.deck_utils import ensure_word_in_default_deck
        from app.study.models import UserWord
        from app.study.services.srs_service import get_user_word_ids

        words = WordSetService.get_words(set_id)
        if not words:
            return 0

        existing = get_user_word_ids(user_id, [word.id for word in words])

        added = 0
        for word in words:
            if word.id in existing:
                continue
            user_word = UserWord(user_id=user_id, word_id=word.id)
            db.session.add(user_word)
            db.session.flush()
            ensure_word_in_default_deck(user_id, word.id, user_word.id)
            added += 1

        if added:
            db.session.commit()
        return added

    @staticmethod
    def suggest_for_user(user_id: int) -> Optional[Dict[str, Any]]:
        """One set worth offering: never played first, then lowest best score.

        Returns None when no published set holds any words — an empty set has
        nothing to quiz, and offering it would dead-end the learner.
        """
        candidates = [
            entry for entry in WordSetService.list_published(user_id)
            if entry['word_count'] > 0
        ]
        if not candidates:
            return None

        unplayed = [entry for entry in candidates if not entry['attempts']]
        if unplayed:
            return unplayed[0]
        return min(candidates, key=lambda entry: entry['best_score'] or 0)
