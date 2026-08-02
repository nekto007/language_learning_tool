"""Three-phrase retrieval practice for the unified daily plan.

The activity is deliberately optional: it reinforces recently learned A1/A2
phrases without making a child's daily streak depend on typed free-text.
Unresolved quiz errors take priority; the remaining places are filled from
translation tasks in modules whose final test the learner has completed.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.daily_plan.items import PlanItem

PHRASE_REVIEW_SIZE = 3
_A1_A2 = ('A1', 'A2')


def _normalise(value: Any) -> str:
    value = re.sub(r"[^\\w\\s']", '', str(value or '').casefold())
    return ' '.join(value.strip().split())


def _is_usable_phrase(value: Any) -> bool:
    phrase = str(value or '').strip()
    words = phrase.split()
    return (
        2 <= len(words) <= 14
        and len(phrase) <= 160
        and '→' not in phrase
        and bool(re.search(r'[A-Za-z]', phrase))
    )


def _candidate(
    *,
    identifier: str,
    prompt: Any,
    answer: Any,
    source: str,
    module_title: Optional[str] = None,
    error_id: Optional[int] = None,
    alternatives: Optional[list[Any]] = None,
) -> Optional[dict[str, Any]]:
    if not _is_usable_phrase(answer):
        return None
    answer_text = str(answer).strip()
    accepted = [answer_text]
    for alternative in alternatives or []:
        if _is_usable_phrase(alternative):
            text = str(alternative).strip()
            if _normalise(text) not in {_normalise(item) for item in accepted}:
                accepted.append(text)
    return {
        'id': identifier,
        'prompt': str(prompt or 'Напишите фразу по-английски.').strip(),
        'answer': answer_text,
        'accepted_answers': accepted,
        'source': source,
        'module_title': module_title,
        'error_id': error_id,
    }


def _error_candidates(user_id: int, db: Any) -> list[dict[str, Any]]:
    """Return phrase-sized unresolved A1/A2 errors, newest first."""
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.daily_plan.linear.models import QuizErrorLog

    rows = (
        db.session.query(QuizErrorLog)
        .join(Lessons, Lessons.id == QuizErrorLog.lesson_id)
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(
            QuizErrorLog.user_id == user_id,
            QuizErrorLog.resolved_at.is_(None),
            CEFRLevel.code.in_(_A1_A2),
        )
        .order_by(QuizErrorLog.answered_wrong_at.desc(), QuizErrorLog.id.desc())
        .limit(20)
        .all()
    )
    items: list[dict[str, Any]] = []
    seen_answers: set[str] = set()
    for row in rows:
        payload = row.question_payload if isinstance(row.question_payload, dict) else {}
        item = _candidate(
            identifier=f'error:{row.id}',
            prompt=payload.get('question_text'),
            answer=payload.get('correct_answer'),
            source='error',
            module_title=getattr(getattr(row.lesson, 'module', None), 'title', None),
            error_id=row.id,
        )
        if item is None or _normalise(item['answer']) in seen_answers:
            continue
        items.append(item)
        seen_answers.add(_normalise(item['answer']))
        if len(items) >= PHRASE_REVIEW_SIZE:
            break
    return items


def _recent_module_candidates(user_id: int, db: Any) -> list[dict[str, Any]]:
    """Return translation phrases from the latest completed A1/A2 modules."""
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

    completed_modules = (
        db.session.query(Module)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .join(Lessons, Lessons.module_id == Module.id)
        .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            Lessons.type == 'final_test',
            CEFRLevel.code.in_(_A1_A2),
        )
        .order_by(LessonProgress.completed_at.desc(), Module.id.desc())
        .limit(3)
        .all()
    )

    items: list[dict[str, Any]] = []
    seen_answers: set[str] = set()
    for module in completed_modules:
        lessons = (
            db.session.query(Lessons)
            .filter(Lessons.module_id == module.id, Lessons.type == 'translation_quiz')
            .order_by(Lessons.number.desc())
            .all()
        )
        for lesson in lessons:
            exercises = (lesson.content or {}).get('exercises') or []
            for index, exercise in enumerate(exercises):
                if not isinstance(exercise, dict):
                    continue
                item = _candidate(
                    identifier=f'recent:{lesson.id}:{index}',
                    prompt=exercise.get('question'),
                    answer=exercise.get('correct'),
                    alternatives=exercise.get('acceptable_answers'),
                    source='recent_module',
                    module_title=module.title,
                )
                if item is None or _normalise(item['answer']) in seen_answers:
                    continue
                items.append(item)
                seen_answers.add(_normalise(item['answer']))
                if len(items) >= PHRASE_REVIEW_SIZE:
                    return items
    return items


def get_phrase_review_items(user_id: int, db: Any) -> list[dict[str, Any]]:
    """Build up to three recall prompts, prioritising unresolved mistakes."""
    selected = _error_candidates(user_id, db)
    if len(selected) >= PHRASE_REVIEW_SIZE:
        return selected

    seen = {_normalise(item['answer']) for item in selected}
    for item in _recent_module_candidates(user_id, db):
        if _normalise(item['answer']) in seen:
            continue
        selected.append(item)
        seen.add(_normalise(item['answer']))
        if len(selected) >= PHRASE_REVIEW_SIZE:
            break
    return selected


def phrase_review_completed_today(user_id: int, db: Any) -> bool:
    from app.daily_plan.models import DailyPlanEvent
    from app.utils.time_utils import get_user_local_date

    today = get_user_local_date(user_id, db)
    return bool(
        db.session.query(DailyPlanEvent.id)
        .filter_by(
            user_id=user_id,
            event_type='phrase_review_completed',
            plan_date=today,
        )
        .first()
    )


def build_phrase_review_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    items = get_phrase_review_items(user_id, db)
    if not items:
        return None
    completed = phrase_review_completed_today(user_id, db)
    return PlanItem(
        id='phrase_review:daily',
        section=section,  # type: ignore[arg-type]
        kind='phrase_review',  # type: ignore[arg-type]
        title='Повтори 3 фразы',
        subtitle='Ошибки и недавно пройденные темы',
        lesson_type=None,
        eta_minutes=3 if not completed else 0,
        url=None if completed else '/learn/phrase-review/?from=daily_plan',
        completed=completed,
        completion_signal='phrase_review_done',  # type: ignore[arg-type]
        data={
            'phrase_count': len(items),
            'error_count': sum(1 for item in items if item['source'] == 'error'),
            'recent_count': sum(1 for item in items if item['source'] == 'recent_module'),
        },
    )


__all__ = [
    'PHRASE_REVIEW_SIZE',
    'build_phrase_review_item',
    'get_phrase_review_items',
    'phrase_review_completed_today',
]
