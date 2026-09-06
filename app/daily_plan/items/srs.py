"""SRS review item builder for the unified daily plan.

Returns a ``PlanItem`` for the user's due SRS cards when there is at least
one card due. Returns None when there are no due cards — the orchestrator
then skips SRS in required entirely (no fake «nothing due» placeholder).

Completion is determined out-of-band at API serialization time
(``compute_plan_steps`` checks XP earned today / cards reviewed today).
The builder always emits ``completed=False`` at assembly time.

The deck-quiz / card-lesson reinforcement mode from the legacy slot is
dropped: in the unified plan, freshly learned vocabulary lands in
``UserCardDirection`` and surfaces via normal SRS on subsequent days,
which is the cleaner reinforcement loop. Deck-quizzes for custom decks
remain available via the existing /study/quiz/* routes but are not part
of the daily plan as a dedicated slot.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

logger = logging.getLogger(__name__)

_SRS_ITEM_ETA_MINUTES = 8
_DECK_QUIZ_DEFAULT_LIMIT = 30


def _build_deck_quiz_plan_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'required',
) -> Optional[PlanItem]:
    """Return a deck-quiz ``PlanItem`` when curriculum already serves the
    card session for today.

    Two card-form activities in one day satisfy each other in the user's
    head — they look like duplicates. When the curriculum slot is itself a
    card lesson we swap the regular SRS-card item for a quiz over the
    user's decks instead, so the daily plan still surfaces a vocabulary-
    review activity without literally repeating cards twice.
    """
    from app.daily_plan.linear.slots.srs_slot import (
        _DECK_QUIZ_LIMIT,
        _DECK_QUIZ_SOURCE,
        _count_user_deck_quiz_words,
    )

    # Собственный сигнал квиза (DP-042): общий ключ `linear_srs_global`
    # пишет и обычная /study-сессия, и корректирующая fallback-ветка
    # `is_srs_slot_completed_today` — ни то, ни другое квизом не является.
    from app.daily_plan.linear.xp import is_deck_quiz_completed_today

    completed_today = is_deck_quiz_completed_today(user_id, db)
    deck_word_count = _count_user_deck_quiz_words(user_id, db)
    limit = min(_DECK_QUIZ_LIMIT, max(deck_word_count, 0))

    data: dict[str, Any] = {
        'mode': 'deck_quiz',
        'source': _DECK_QUIZ_SOURCE,
        'deck_word_count': deck_word_count,
        'word_limit': limit,
    }

    if completed_today:
        return PlanItem(
            id='srs:deck_quiz',
            section=section,  # type: ignore[arg-type]
            kind='srs',
            title='Квиз по словам из колод закрыт',
            subtitle=f'{deck_word_count} слов в колодах' if deck_word_count else None,
            lesson_type='quiz',
            eta_minutes=0,
            url=None,
            completed=True,
            completion_signal='srs_xp_earned',
            data=data,
        )

    if deck_word_count <= 0:
        # Nothing to quiz over — surface a no-op completed placeholder.
        return PlanItem(
            id='srs:deck_quiz',
            section=section,  # type: ignore[arg-type]
            kind='srs',
            title='Нет слов для квиза в колодах',
            subtitle=None,
            lesson_type='quiz',
            eta_minutes=0,
            url=None,
            completed=True,
            completion_signal='srs_xp_earned',
            data=data,
        )

    return PlanItem(
        id='srs:deck_quiz',
        section=section,  # type: ignore[arg-type]
        kind='srs',
        title=f'Квиз по словам — {limit}',
        subtitle=f'{deck_word_count} в колодах' if deck_word_count else None,
        lesson_type='quiz',
        eta_minutes=_SRS_ITEM_ETA_MINUTES,
        url=build_slot_url(
            f'/study/quiz/linear-plan?source={_DECK_QUIZ_SOURCE}&limit={limit}',
            LinearSlotKind.SRS,
        ),
        completed=False,
        completion_signal='srs_xp_earned',
        data=data,
    )


def _pause_reason_hint(pause: dict[str, Any], review_show: int = 0) -> str | None:
    """Text for the NEW-card cut, naming the signal that binds (item 12).

    Owner's rule (2026-09-06): everything on the tile must motivate. So the
    hint talks about today's portion and the moment new words come back, not
    about the size of the problem: «13.8 дн. повторений» read as a sentence,
    and a debt that only ever shrinks is shown as such by the badge itself.
    """
    binding = pause.get('binding')
    if binding is None:
        return None
    overdue = int(pause.get('overdue') or 0)
    base = int(pause.get('reviews_per_day') or 0)
    backlog_tier = pause.get('backlog_tier')
    # Backlog tiers: ≤1 day normal, ≤3 low (NEW x0.3), ≤7 critical, >7 collapse
    # (NEW off). New words start coming back below 3 daily norms.
    comeback_at = 3 * base if base > 0 else 0
    if backlog_tier in ('critical', 'collapse'):
        today = f' Сегодня разбираем {review_show}.' if review_show > 0 else ''
        comeback = f' Новые слова начнут возвращаться, когда долг станет меньше {comeback_at}.' if comeback_at else ''
        backlog_text = f'Долг {overdue} карточек.{today}{comeback}'
    else:
        backlog_text = f'Долг {overdue} карточек — новых слов сегодня меньше. Такой долг закрывается за пару дней.'
    accuracy_text = {
        'low':      'Точность 65–80 % — новых слов чуть меньше, чтобы закрепить текущие.',
        'critical': 'Точность 45–65 % — сначала закрепляем то, что уже учили, новых слов меньше.',
        'collapse': 'Точность ниже 45 % — пауза на новые слова, повторения вернут форму.',
    }.get(pause.get('accuracy_tier') or '')
    if binding == 'backlog':
        return backlog_text
    if binding == 'accuracy':
        return accuracy_text
    return f'{backlog_text} {accuracy_text}' if accuracy_text else backlog_text


def _srs_completed_today(user_id: int, db: Any) -> bool:
    """Return True when the SRS slot is done for today.

    Delegates to :func:`is_srs_slot_completed_today` so the primary
    signal (StreakEvent XP entry) and the corrective-award fallback for
    a lost ``complete-session`` write are shared with ``build_srs_slot``.
    """
    from app.daily_plan.linear.xp import is_srs_slot_completed_today

    return is_srs_slot_completed_today(user_id, db)


def build_srs_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'required',
    ignore_daily_budget: bool = False,
    as_deck_quiz: bool = False,
) -> Optional[PlanItem]:
    """Return SRS PlanItem: pending when due>0, done when reviewed today, None otherwise.

    When due_count drops to zero mid-session, returning None would make the
    slot disappear from required and shrink the counter — confusing UX.
    Instead, if the user already earned the SRS-slot XP today, keep the
    item with completed=True so it stays on the «done» list. Only return
    None when due=0 AND no activity today (e.g. brand-new user with no
    cards yet).

    ``as_deck_quiz=True`` swaps the regular card-review item for a deck
    quiz — used when the curriculum slot is itself a card lesson, to
    avoid two cards-form activities crediting each other.
    """
    if as_deck_quiz:
        return _build_deck_quiz_plan_item(user_id, db, section=section)

    from app.daily_plan.linear.slots.srs_slot import count_srs_reviews_today
    from app.srs.constants import CardState
    from app.srs.counting import (
        count_due_by_states,
        count_new_cards_today,
        count_pending_new,
        count_reviews_today,
        count_old_review_debt,
        get_due_card_budget,
        get_new_card_budget,
        old_debt_quota,
        split_due_budget,
    )
    from app.study.services import SRSService

    # Three-bucket model (Раздел 5 of docs/srs-fix-plan.md):
    #   NEW       — capped by new_words_per_day × tier_pct (own budget)
    #   LEARNING/RELEARNING + REVIEW — share one daily ceiling = base
    #   reviews_per_day (get_due_card_budget). Learning/relearning get
    #   priority; the combined cap bounds the session so a struggling user
    #   can't drown in an unbounded learning pile.
    new_pending = count_pending_new(user_id, db)
    learning_due = count_due_by_states(
        user_id, db, states=(CardState.LEARNING.value, CardState.RELEARNING.value),
    )
    review_due = count_due_by_states(user_id, db, states=(CardState.REVIEW.value,))
    overdue_reviews = SRSService.get_overdue_review_count(user_id)

    remaining_new, remaining_reviews = get_new_card_budget(user_id, db)
    due_budget = get_due_card_budget(user_id, db)
    new_show = min(new_pending, remaining_new)
    # One split for tile, queue and completion checks (item 12): a share of
    # the ceiling is reserved for mature reviews, and the review side still
    # goes through the floored batch helper (DP-043).
    learning_show, review_show = split_due_budget(
        user_id, db,
        learning_due=learning_due, review_due=review_due,
        due_budget=due_budget, remaining_reviews=remaining_reviews,
    )
    total_show = new_show + learning_show + review_show
    # Item 13: the review batch is fresh-overdue first plus a quota of old debt;
    # mirror the queue's composition so the subtitle can say «из них N давних».
    old_review_due = min(review_due, count_old_review_debt(user_id, db)) if review_show > 0 else 0
    review_fresh_show, review_old_show = old_debt_quota(
        review_show, old_review_due, max(0, review_due - old_review_due),
    )

    reviews_today_total = count_reviews_today(user_id, db)
    new_today = count_new_cards_today(user_id, db)
    completed_today = _srs_completed_today(user_id, db)

    if total_show <= 0 and not completed_today:
        if not ignore_daily_budget:
            return None
        # Graduated users: even if budget is exhausted, show backlog if any.
        raw_backlog = learning_due + review_due
        if raw_backlog <= 0 and new_pending <= 0:
            return None
        total_show = raw_backlog + new_pending  # ignore budgets

    if section == 'optional' and total_show <= 0 and completed_today and not ignore_daily_budget:
        return None

    pause = SRSService.get_new_card_pause(user_id)
    tier = pause['accuracy_tier']  # one of normal/low/critical/collapse
    reason_hint: Optional[str] = _pause_reason_hint(pause, review_show) if total_show > 0 else None

    data: dict[str, Any] = {
        'new_show': new_show,
        'learning_due': learning_due,
        'learning_show': learning_show,
        'review_show': review_show,
        'total_show': total_show,
        'new_pending': new_pending,
        'review_due': review_due,
        'overdue_reviews': overdue_reviews,
        'review_old_show': review_old_show,
        'review_fresh_show': review_fresh_show,
        'new_today': new_today,
        'reviews_today': reviews_today_total,
        'remaining_new': remaining_new,
        'remaining_reviews': remaining_reviews,
        'srs_tier': tier,
        'reason_hint': reason_hint,
        # item 12: which signal holds NEW back: 'backlog' / 'accuracy' / 'both' / None
        'new_pause_reason': pause['binding'],
    }

    if total_show <= 0 and completed_today:
        title = 'Повторение закрыто'
        subtitle = f'{reviews_today_total} карточек сегодня' if reviews_today_total else 'на сегодня всё'
    else:
        only_learning = learning_show > 0 and new_show == 0 and review_show == 0
        title = (
            f'Карточки в изучении — {total_show}'
            if only_learning else f'Повторение слов — {total_show}'
        )
        subtitle_bits = []
        if new_show > 0:
            subtitle_bits.append(f'{new_show} новых')
        if learning_show > 0:
            subtitle_bits.append(f'{learning_show} в изучении')
        if review_show > 0:
            if 0 < review_old_show < review_show:
                subtitle_bits.append(f'{review_show} на повтор, из них {review_old_show} давних')
            elif review_old_show and review_old_show == review_show:
                subtitle_bits.append(f'{review_show} давних на повтор')
            else:
                subtitle_bits.append(f'{review_show} на повтор')
        subtitle = ' · '.join(subtitle_bits) or 'все типы доступны'

    return PlanItem(
        id='srs:global',
        section=section,  # type: ignore[arg-type]
        kind='srs',
        title=title,
        subtitle=subtitle,
        lesson_type=None,
        eta_minutes=0 if completed_today and total_show <= 0 else _SRS_ITEM_ETA_MINUTES,
        url=build_slot_url('/study/cards?source=linear_plan', LinearSlotKind.SRS),
        completed=completed_today,
        completion_signal='srs_xp_earned',
        data=data,
    )
