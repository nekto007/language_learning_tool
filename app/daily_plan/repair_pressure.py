from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func

from app.utils.db import db
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.study.models import UserWord, UserCardDirection
from app.grammar_lab.models import GrammarAttempt, UserGrammarExercise


REPAIR_THRESHOLD = 0.6

OVERDUE_SRS_SOFT = 15
OVERDUE_SRS_HARD = 50

GRAMMAR_WEAK_SOFT = 3
GRAMMAR_WEAK_HARD = 10

FAILURE_CLUSTER_SOFT = 5
FAILURE_CLUSTER_HARD = 15

FAILURE_CLUSTER_WINDOW_DAYS = 3

WEIGHT_OVERDUE = 0.50
WEIGHT_GRAMMAR = 0.30
WEIGHT_FAILURES = 0.20


@dataclass
class RepairBreakdown:
    overdue_srs_count: int
    overdue_srs_score: float
    grammar_weak_count: int
    grammar_weak_score: float
    failure_cluster_count: int
    failure_cluster_score: float
    total_score: float


def _normalize(value: int, soft: int, hard: int) -> float:
    if value <= 0:
        return 0.0
    if value >= hard:
        return 1.0
    if value <= soft:
        return value / soft * 0.5
    return 0.5 + (value - soft) / (hard - soft) * 0.5


def _count_overdue_srs(user_id: int) -> int:
    now = datetime.now(timezone.utc)
    mix_word_ids = get_daily_plan_mix_word_ids(user_id)

    query = (
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state.in_(('review', 'relearning')),
            UserCardDirection.next_review <= now,
        )
    )

    if mix_word_ids:
        query = query.filter(UserWord.word_id.in_(mix_word_ids))

    overdue_cards = query.scalar() or 0

    overdue_grammar = (
        db.session.query(func.count(UserGrammarExercise.id))
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.state.in_(('review', 'relearning')),
            UserGrammarExercise.next_review <= now,
        )
        .scalar()
    ) or 0

    return overdue_cards + overdue_grammar


def _count_grammar_weak_points(user_id: int) -> int:
    return (
        db.session.query(func.count(UserGrammarExercise.id))
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.state == 'relearning',
        )
        .scalar()
    ) or 0


def _count_failure_clusters(user_id: int, tz: Optional[str] = None) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=FAILURE_CLUSTER_WINDOW_DAYS)

    return (
        db.session.query(func.count(GrammarAttempt.id))
        .filter(
            GrammarAttempt.user_id == user_id,
            GrammarAttempt.is_correct.is_(False),
            GrammarAttempt.created_at >= cutoff,
        )
        .scalar()
    ) or 0


def calculate_repair_pressure(
    user_id: int, tz: Optional[str] = None
) -> RepairBreakdown:
    """Weighted score (0-1): 50% overdue SRS + 30% grammar weak points + 20% recent failure clusters."""
    overdue = _count_overdue_srs(user_id)
    weak = _count_grammar_weak_points(user_id)
    failures = _count_failure_clusters(user_id, tz)

    overdue_score = _normalize(overdue, OVERDUE_SRS_SOFT, OVERDUE_SRS_HARD)
    grammar_score = _normalize(weak, GRAMMAR_WEAK_SOFT, GRAMMAR_WEAK_HARD)
    failure_score = _normalize(failures, FAILURE_CLUSTER_SOFT, FAILURE_CLUSTER_HARD)

    total = round(
        WEIGHT_OVERDUE * overdue_score
        + WEIGHT_GRAMMAR * grammar_score
        + WEIGHT_FAILURES * failure_score,
        4,
    )
    total = min(total, 1.0)

    return RepairBreakdown(
        overdue_srs_count=overdue,
        overdue_srs_score=overdue_score,
        grammar_weak_count=weak,
        grammar_weak_score=grammar_score,
        failure_cluster_count=failures,
        failure_cluster_score=failure_score,
        total_score=total,
    )
