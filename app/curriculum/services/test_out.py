"""Сдача модуля экстерном (test-out).

Тест собирается из multiple_choice / true_false вопросов quiz- и
final_test-уроков модуля. Порог — TEST_OUT_PASSING_SCORE. При сдаче все
уроки модуля получают LessonProgress completed со score теста и пометкой
``data.test_out`` — спайн (`find_next_lesson_linear`) и
`Module.check_prerequisites` видят модуль завершённым штатно, без правок
гейтов. XP не начисляется.

Идентичность вопросов между GET и POST — через индексы в детерминированно
сплющенном списке вопросов модуля (sample-индексы хранятся в Flask session).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.curriculum.grading import process_final_test_submission
from app.curriculum.models import LessonProgress, Lessons, Module, ModuleTestOut
from app.utils.db import db as _db

logger = logging.getLogger(__name__)

TEST_OUT_PASSING_SCORE = 80
TEST_OUT_QUESTION_TARGET = 12
TEST_OUT_MIN_QUESTIONS = 6
TEST_OUT_MAX_ATTEMPTS_PER_DAY = 3
SESSION_KEY_PREFIX = 'module_test_out_'

_QUESTION_LESSON_TYPES = ('quiz', 'final_test')


def _resolve_mc_answer_index(question: dict) -> Optional[int]:
    """Привести правильный ответ multiple_choice к int-индексу опции."""
    options = question.get('options') or []
    if len(options) < 2:
        return None
    for key in ('correct_index', 'correct', 'answer', 'correct_answer'):
        value = question.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and 0 <= value < len(options):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for i, opt in enumerate(options):
                if str(opt).strip().lower() == normalized:
                    return i
    return None


def _resolve_tf_answer(question: dict) -> Optional[bool]:
    for key in ('correct', 'answer', 'correct_answer'):
        value = question.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
            return value.strip().lower() == 'true'
    return None


def _normalize_question(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    qtype = str(raw.get('type') or 'multiple_choice')
    text = raw.get('question') or raw.get('prompt') or raw.get('sentence') or ''
    if not str(text).strip():
        return None
    if qtype == 'multiple_choice':
        answer = _resolve_mc_answer_index(raw)
        if answer is None:
            return None
        return {
            'type': 'multiple_choice',
            'question': str(text)[:600],
            'options': [str(o)[:300] for o in raw.get('options')],
            'answer': answer,
        }
    if qtype in ('true_false', 'tf'):
        answer = _resolve_tf_answer(raw)
        if answer is None:
            return None
        return {
            'type': 'true_false',
            'question': str(text)[:600],
            'options': ['True', 'False'],
            'answer': answer,
        }
    return None


def _raw_questions_from_lesson(lesson: Lessons) -> list:
    content = lesson.content or {}
    raw: list = []
    if lesson.type == 'final_test':
        sections = content.get('test_sections') or content.get('sections') or []
        for section in sections:
            if isinstance(section, dict):
                raw.extend(section.get('exercises') or section.get('questions') or [])
    raw.extend(content.get('questions') or content.get('exercises') or [])
    return raw


def collect_module_questions(module: Module) -> list:
    """Детерминированно сплющенный список нормализованных вопросов модуля.

    Порядок стабилен (уроки по number, вопросы по позиции в контенте) —
    индексы в этом списке служат ссылками между GET и POST.
    """
    lessons = sorted(
        (l for l in module.lessons if l.type in _QUESTION_LESSON_TYPES),
        key=lambda l: (l.number or 0, l.id),
    )
    questions = []
    for lesson in lessons:
        for raw in _raw_questions_from_lesson(lesson):
            normalized = _normalize_question(raw)
            if normalized is not None:
                questions.append(normalized)
    return questions


def _attempts_today(user_id: int, module_id: int, db: Any = _db) -> int:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    return (
        db.session.query(ModuleTestOut)
        .filter(
            ModuleTestOut.user_id == user_id,
            ModuleTestOut.module_id == module_id,
            ModuleTestOut.passed.is_(False),
            ModuleTestOut.created_at >= cutoff,
        )
        .count()
    )


def _module_completed_pct(user_id: int, module: Module, db: Any = _db) -> int:
    total = len(module.lessons)
    if not total:
        return 0
    completed = (
        db.session.query(LessonProgress)
        .join(Lessons, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            Lessons.module_id == module.id,
        )
        .count()
    )
    return round(completed / total * 100)


def test_out_attempts_block(user_id: int, module_id: int, db: Any = _db) -> bool:
    """True, если экстерн заблокирован попытками (уже сдан или лимит за 24ч).

    Одна query — для дешёвой проверки на странице модуля, где completion
    уже посчитан из загруженного прогресса.
    """
    rows = (
        db.session.query(ModuleTestOut.passed, ModuleTestOut.created_at)
        .filter(
            ModuleTestOut.user_id == user_id,
            ModuleTestOut.module_id == module_id,
        )
        .all()
    )
    if any(r.passed for r in rows):
        return True
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    failed_recent = sum(1 for r in rows if not r.passed and r.created_at >= cutoff)
    return failed_recent >= TEST_OUT_MAX_ATTEMPTS_PER_DAY


def get_test_out_state(user_id: int, module: Module, db: Any = _db) -> dict:
    """Доступность экстерна: {'available': bool, 'reason': str|None, ...}."""
    questions = collect_module_questions(module)
    state = {
        'available': False,
        'reason': None,
        'question_count': len(questions),
        'completed_pct': _module_completed_pct(user_id, module, db),
    }
    if state['completed_pct'] >= 100:
        state['reason'] = 'module_completed'
        return state
    already_passed = (
        db.session.query(ModuleTestOut)
        .filter_by(user_id=user_id, module_id=module.id, passed=True)
        .first()
    )
    if already_passed:
        state['reason'] = 'already_passed'
        return state
    if len(questions) < TEST_OUT_MIN_QUESTIONS:
        state['reason'] = 'not_enough_content'
        return state
    if _attempts_today(user_id, module.id, db) >= TEST_OUT_MAX_ATTEMPTS_PER_DAY:
        state['reason'] = 'attempts_exhausted'
        return state
    state['available'] = True
    return state


def sample_test_refs(module: Module) -> list:
    """Выбрать индексы вопросов для попытки (до TEST_OUT_QUESTION_TARGET)."""
    questions = collect_module_questions(module)
    indices = list(range(len(questions)))
    if len(indices) > TEST_OUT_QUESTION_TARGET:
        indices = random.sample(indices, TEST_OUT_QUESTION_TARGET)
        indices.sort()
    return indices


def questions_by_refs(module: Module, refs: list) -> list:
    questions = collect_module_questions(module)
    return [questions[i] for i in refs if isinstance(i, int) and 0 <= i < len(questions)]


def client_questions(questions: list) -> list:
    """Версия вопросов без правильных ответов — для шаблона."""
    return [
        {'type': q['type'], 'question': q['question'], 'options': q['options']}
        for q in questions
    ]


def grade_test_out(questions: list, user_answers: dict) -> dict:
    return process_final_test_submission(
        questions, user_answers, passing_score=TEST_OUT_PASSING_SCORE
    )


def apply_test_out_pass(user_id: int, module: Module, score: float, db: Any = _db) -> int:
    """Mass-complete уроков модуля после сдачи. Flush only, caller commits.

    Существующий completed-прогресс не трогаем (и его score не портим).
    """
    now = datetime.now(timezone.utc)
    touched = 0
    for lesson in module.lessons:
        progress = (
            db.session.query(LessonProgress)
            .filter_by(user_id=user_id, lesson_id=lesson.id)
            .first()
        )
        if progress is not None and progress.status == 'completed':
            continue
        if progress is None:
            progress = LessonProgress(
                user_id=user_id,
                lesson_id=lesson.id,
                started_at=now,
            )
            db.session.add(progress)
        progress.status = 'completed'
        progress.set_score(score)
        progress.completed_at = now
        progress.last_activity = now
        data = dict(progress.data or {})
        data['test_out'] = True
        progress.data = data
        touched += 1
    db.session.flush()
    return touched


def record_test_out_attempt(
    user_id: int, module_id: int, score: float, passed: bool, db: Any = _db
) -> ModuleTestOut:
    attempt = ModuleTestOut(
        user_id=user_id, module_id=module_id, score=score, passed=passed
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt
