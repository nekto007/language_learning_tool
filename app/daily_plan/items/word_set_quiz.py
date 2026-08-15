"""Optional plan item: a themed quiz over one curated word set.

Optional by design. ``day_secured`` is computed from the required section only
(see ``compute_plan_steps``), and a themed quiz is bonus practice — it must
never be what stands between a learner and closing their day.
"""
from __future__ import annotations

from typing import Any, Optional

from app.daily_plan.items import PlanItem

_WORD_SET_QUIZ_ETA_MINUTES = 4


def build_word_set_quiz_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    """Return a word_set_quiz PlanItem, or None when there is nothing to offer.

    Picks a set the user has never played, else their weakest one, so the card
    keeps pointing somewhere useful instead of repeating a set already aced.
    """
    from app.study.services import WordSetService
    from app.utils.time_utils import get_user_local_date

    suggestion = WordSetService.suggest_for_user(user_id)
    if suggestion is None:
        return None

    word_set = suggestion['set']

    # Completion is per-day and set-agnostic: playing any themed quiz today
    # settles this card. Tying it to one specific set would leave the card
    # unfinishable the moment the suggestion moved on to another set.
    completed = WordSetService.completed_on(user_id, get_user_local_date(user_id, db))

    best = suggestion['best_score']
    if suggestion['attempts']:
        subtitle = f'{suggestion["word_count"]} слов · лучший результат {round(best or 0)}%'
    else:
        subtitle = f'{suggestion["word_count"]} слов · ещё не проходили'

    return PlanItem(
        id=f'word_set_quiz:{word_set.slug}',
        section=section,  # type: ignore[arg-type]
        kind='word_set_quiz',
        title=f'Квиз: {word_set.name}',
        subtitle=subtitle,
        lesson_type=None,
        eta_minutes=0 if completed else _WORD_SET_QUIZ_ETA_MINUTES,
        url=f'/study/quiz/set/{word_set.slug}',
        completed=completed,
        completion_signal='word_set_quiz_done',
        data={
            'set_id': word_set.id,
            'set_slug': word_set.slug,
            'set_name': word_set.name,
            'set_icon': word_set.icon,
            'set_accent': word_set.accent,
            'word_count': suggestion['word_count'],
            'best_score': best,
        },
    )
