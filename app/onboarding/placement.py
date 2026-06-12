"""Placement-тест онбординга: адаптивная лесенка по grammar-lab пулу.

Вопросы — multiple_choice упражнения Grammar Lab (уровень берётся с
``GrammarTopic.level``). Алгоритм — staircase: старт с A2, верный ответ
поднимает уровень следующего вопроса, неверный опускает. Максимум
``MAX_QUESTIONS`` вопросов; рекомендация — высший уровень с >= 2 верными
ответами (без верных — A1).

Состояние живёт в server-side Flask session (правильные ответы клиенту не
уходят, грейдинг — ``GrammarExerciseGrader``). Результат пишется в тот же
``User.onboarding_level``, от которого работает placement floor спайна.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Optional

from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.utils.db import db as _db

logger = logging.getLogger(__name__)

PLACEMENT_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')
MAX_QUESTIONS = 12
MIN_POOL_PER_LEVEL = 3
RECOMMEND_MIN_CORRECT = 2
SESSION_KEY = 'placement_state'

_START_LEVEL_INDEX = 1  # A2


def _mc_pool_query(level: str, db: Any = _db):
    return (
        db.session.query(GrammarExercise)
        .join(GrammarTopic, GrammarExercise.topic_id == GrammarTopic.id)
        .filter(
            GrammarTopic.level == level,
            GrammarExercise.exercise_type == 'multiple_choice',
        )
    )


def placement_available(db: Any = _db) -> bool:
    """Тест доступен, когда на каждом уровне есть минимальный пул вопросов."""
    try:
        for level in PLACEMENT_LEVELS:
            if _mc_pool_query(level, db).count() < MIN_POOL_PER_LEVEL:
                return False
        return True
    except Exception:
        logger.exception("placement availability check failed")
        return False


def _question_payload(exercise: GrammarExercise) -> dict:
    content = exercise.content or {}
    return {
        'id': exercise.id,
        'question': str(content.get('question') or '')[:500],
        'options': [str(o)[:200] for o in (content.get('options') or [])],
    }


def _pick_exercise(level: str, asked_ids: list, db: Any = _db) -> Optional[GrammarExercise]:
    query = _mc_pool_query(level, db)
    if asked_ids:
        query = query.filter(~GrammarExercise.id.in_(asked_ids))
    candidates = query.all()
    candidates = [
        c for c in candidates
        if (c.content or {}).get('question') and len((c.content or {}).get('options') or []) >= 2
    ]
    if not candidates:
        return None
    return random.choice(candidates)


def start_placement(session: dict, db: Any = _db) -> Optional[dict]:
    """Начать тест: положить чистое состояние в session, вернуть первый вопрос."""
    state = {
        'asked': [],          # exercise ids в порядке показа
        'levels': [],         # уровень каждого вопроса
        'results': [],        # bool верно/неверно
        'idx': _START_LEVEL_INDEX,
    }
    exercise = _pick_exercise(PLACEMENT_LEVELS[state['idx']], [], db)
    if exercise is None:
        return None
    state['asked'].append(exercise.id)
    state['levels'].append(PLACEMENT_LEVELS[state['idx']])
    session[SESSION_KEY] = state
    return {
        'question': _question_payload(exercise),
        'number': 1,
        'max': MAX_QUESTIONS,
    }


def _recommend(levels: list, results: list) -> str:
    correct_by_level: dict = {}
    for level, ok in zip(levels, results):
        if ok:
            correct_by_level[level] = correct_by_level.get(level, 0) + 1
    for level in reversed(PLACEMENT_LEVELS):
        if correct_by_level.get(level, 0) >= RECOMMEND_MIN_CORRECT:
            return level
    # Один верный ответ на каком-то уровне — даём этот уровень, иначе A1.
    for level in reversed(PLACEMENT_LEVELS):
        if correct_by_level.get(level, 0) >= 1:
            return level
    return 'A1'


def submit_placement_answer(
    session: dict,
    exercise_id: int,
    answer: Any,
    db: Any = _db,
) -> Optional[dict]:
    """Принять ответ, вернуть следующий вопрос или итоговую рекомендацию.

    None — нет активной сессии или exercise_id не совпадает с последним
    выданным вопросом (защита от перебора).
    """
    state = session.get(SESSION_KEY)
    if not state or not state['asked'] or state['asked'][-1] != exercise_id:
        return None
    if len(state['results']) >= len(state['asked']):
        return None  # на последний вопрос уже отвечали

    exercise = db.session.query(GrammarExercise).get(exercise_id)
    if exercise is None:
        session.pop(SESSION_KEY, None)
        return None

    grade = GrammarExerciseGrader().grade(exercise, answer)
    is_correct = bool(grade.get('is_correct'))
    state['results'].append(is_correct)

    # Staircase: верно → уровень выше, неверно → ниже.
    if is_correct:
        state['idx'] = min(state['idx'] + 1, len(PLACEMENT_LEVELS) - 1)
    else:
        state['idx'] = max(state['idx'] - 1, 0)

    done = len(state['results']) >= MAX_QUESTIONS
    # Ранний выход: два неверных подряд на A1 — ниже некуда.
    if (
        not done
        and state['idx'] == 0
        and len(state['results']) >= 2
        and not state['results'][-1]
        and not state['results'][-2]
        and state['levels'][-1] == 'A1'
    ):
        done = True

    next_payload = None
    if not done:
        exercise_next = _pick_exercise(PLACEMENT_LEVELS[state['idx']], state['asked'], db)
        if exercise_next is None:
            done = True  # пул уровня исчерпан — завершаем с тем, что есть
        else:
            state['asked'].append(exercise_next.id)
            state['levels'].append(PLACEMENT_LEVELS[state['idx']])
            next_payload = {
                'question': _question_payload(exercise_next),
                'number': len(state['asked']),
                'max': MAX_QUESTIONS,
            }

    result: dict = {'correct': is_correct, 'done': done}
    if done:
        result['recommended_level'] = _recommend(state['levels'], state['results'])
        result['correct_count'] = sum(1 for r in state['results'] if r)
        result['total'] = len(state['results'])
        session.pop(SESSION_KEY, None)
    else:
        session[SESSION_KEY] = state
        result['next'] = next_payload
    return result
