"""Next-best-step recommender for post-minimum continuation.

Returns up to 3 continuation tasks with human-readable reason strings.
Priority: unfinished lesson > SRS due > grammar weak > reading > vocab.
Quality filters: no same category back-to-back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func

logger = logging.getLogger(__name__)

_STEP_KINDS = ('lesson', 'srs', 'grammar', 'reading', 'vocab')


@dataclass
class NextStep:
    kind: str          # one of _STEP_KINDS
    reason: str        # human-readable 1-sentence string
    data: dict         # kind-specific payload (lesson_id, topic_id, words_due, book_id, …)
    estimated_minutes: Optional[int] = None


def get_next_best_step(user_id: int, db, max_steps: int = 3) -> list[NextStep]:
    """Return up to max_steps continuation tasks for user_id, in priority order.

    Applies quality filters: no same category back-to-back (covers both
    "no exact duplicate back-to-back" and "no same category twice in a row").
    Returns an empty list when all sources are genuinely exhausted.
    """
    candidates = [s for s in [
        _check_unfinished_lesson(user_id, db),
        _check_srs_due(user_id, db),
        _check_grammar_weak(user_id, db),
        _check_reading_progress(user_id, db),
        _check_vocab(user_id, db),
    ] if s is not None]

    return _apply_queue_filters(candidates, max_steps)


def _apply_queue_filters(candidates: list[NextStep], max_steps: int) -> list[NextStep]:
    """Build a queue applying quality filters: no same category back-to-back."""
    queue: list[NextStep] = []
    for step in candidates:
        if len(queue) >= max_steps:
            break
        if queue and queue[-1].kind == step.kind:
            continue
        queue.append(step)
    return queue


# ── Priority 1: unfinished lesson ──────────────────────────────────────────

def _check_unfinished_lesson(user_id: int, db) -> Optional[NextStep]:
    from app.curriculum.models import LessonProgress, Lessons, Module

    in_progress = (
        LessonProgress.query
        .filter_by(user_id=user_id, status='in_progress')
        .order_by(LessonProgress.started_at.desc())
        .first()
    )

    if in_progress:
        lesson = Lessons.query.get(in_progress.lesson_id)
        if lesson:
            module = Module.query.get(lesson.module_id)
            module_num = module.number if module else None
            reason = f'You have an unfinished lesson: "{lesson.title}"'
            return NextStep(
                kind='lesson',
                reason=reason,
                data={
                    'lesson_id': lesson.id,
                    'lesson_title': lesson.title,
                    'lesson_type': lesson.type,
                    'module_number': module_num,
                    'status': 'in_progress',
                },
                estimated_minutes=_lesson_minutes(lesson.type),
            )

    # No in_progress lesson — check for the next available lesson
    last_completed = (
        LessonProgress.query
        .filter_by(user_id=user_id, status='completed')
        .order_by(LessonProgress.completed_at.desc())
        .first()
    )
    if not last_completed:
        # Cold-start: suggest first lesson
        first_module = Module.query.order_by(Module.number).first()
        if first_module:
            first_lesson = (
                Lessons.query
                .filter_by(module_id=first_module.id)
                .order_by(Lessons.number)
                .first()
            )
            if first_lesson:
                reason = f'Start your first lesson: "{first_lesson.title}"'
                return NextStep(
                    kind='lesson',
                    reason=reason,
                    data={
                        'lesson_id': first_lesson.id,
                        'lesson_title': first_lesson.title,
                        'lesson_type': first_lesson.type,
                        'module_number': first_module.number,
                        'status': 'not_started',
                    },
                    estimated_minutes=_lesson_minutes(first_lesson.type),
                )
        return None

    lesson = Lessons.query.get(last_completed.lesson_id)
    if not lesson:
        return None

    module = Module.query.get(lesson.module_id)
    if not module:
        return None

    next_l = (
        Lessons.query
        .filter(Lessons.module_id == module.id, Lessons.number > lesson.number)
        .order_by(Lessons.number)
        .first()
    )
    if not next_l:
        next_module = Module.query.filter(
            Module.level_id == module.level_id,
            Module.number == module.number + 1,
        ).first()
        if next_module:
            next_l = (
                Lessons.query
                .filter_by(module_id=next_module.id)
                .order_by(Lessons.number)
                .first()
            )

    if next_l:
        next_module = Module.query.get(next_l.module_id)
        reason = f'Continue with the next lesson: "{next_l.title}"'
        return NextStep(
            kind='lesson',
            reason=reason,
            data={
                'lesson_id': next_l.id,
                'lesson_title': next_l.title,
                'lesson_type': next_l.type,
                'module_number': next_module.number if next_module else None,
                'status': 'not_started',
            },
            estimated_minutes=_lesson_minutes(next_l.type),
        )
    return None


# ── Priority 2: SRS due ─────────────────────────────────────────────────────

def _check_srs_due(user_id: int, db) -> Optional[NextStep]:
    from app.study.models import UserWord, UserCardDirection, StudySettings, QuizDeckWord
    from app.auth.models import User

    user = User.query.get(user_id)
    default_deck_id = user.default_study_deck_id if user else None
    now = datetime.now(timezone.utc)

    if default_deck_id:
        user_word_subq = (
            db.session.query(QuizDeckWord.user_word_id)
            .filter(
                QuizDeckWord.deck_id == default_deck_id,
                QuizDeckWord.user_word_id.isnot(None),
            )
        )
    else:
        user_word_subq = db.session.query(UserWord.id).filter(UserWord.user_id == user_id)

    raw_due = (
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(user_word_subq),
            UserCardDirection.next_review <= now,
        )
        .scalar() or 0
    )

    if raw_due <= 0:
        return None

    settings = StudySettings.get_settings(user_id)
    reason = f'You have {raw_due} card{"s" if raw_due != 1 else ""} due for review'
    estimated = max(raw_due // 8, 1)
    return NextStep(
        kind='srs',
        reason=reason,
        data={
            'words_due': raw_due,
            'daily_limit': settings.reviews_per_day,
        },
        estimated_minutes=estimated,
    )


# ── Priority 3: grammar weak ────────────────────────────────────────────────

def _check_grammar_weak(user_id: int, db) -> Optional[NextStep]:
    from app.grammar_lab.models import (
        GrammarTopic,
        UserGrammarTopicStatus,
        UserGrammarExercise,
        GrammarExercise,
    )
    now = datetime.now(timezone.utc)

    # Find active topic with due exercises
    active_statuses = (
        UserGrammarTopicStatus.query
        .filter(
            UserGrammarTopicStatus.user_id == user_id,
            UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing']),
        )
        .all()
    )

    best_topic = None
    best_due = 0

    for uts in active_statuses:
        due = (
            UserGrammarExercise.query
            .join(GrammarExercise, GrammarExercise.id == UserGrammarExercise.exercise_id)
            .filter(
                UserGrammarExercise.user_id == user_id,
                UserGrammarExercise.next_review <= now,
                GrammarExercise.topic_id == uts.topic_id,
            )
            .count()
        )
        if due > best_due:
            best_due = due
            best_topic = uts

    if best_topic and best_due > 0:
        topic = GrammarTopic.query.get(best_topic.topic_id)
        if topic:
            reason = f'You have {best_due} grammar exercise{"s" if best_due != 1 else ""} due in "{topic.title}"'
            return NextStep(
                kind='grammar',
                reason=reason,
                data={
                    'topic_id': topic.id,
                    'topic_title': topic.title,
                    'due_exercises': min(best_due, 12),
                    'status': best_topic.status,
                },
                estimated_minutes=max(best_due // 3, 2),
            )

    return None


# ── Priority 4: reading progress ────────────────────────────────────────────

def _check_reading_progress(user_id: int, db) -> Optional[NextStep]:
    from app.books.models import Book, Chapter, UserChapterProgress

    started_book_ids = [
        r[0]
        for r in db.session.query(Chapter.book_id)
        .join(UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id)
        .filter(UserChapterProgress.user_id == user_id)
        .group_by(Chapter.book_id)
        .order_by(func.max(UserChapterProgress.updated_at).desc())
        .all()
    ]

    if not started_book_ids:
        return None

    book = Book.query.get(started_book_ids[0])
    if not book:
        return None

    reason = f'Continue reading "{book.title}"'
    return NextStep(
        kind='reading',
        reason=reason,
        data={
            'book_id': book.id,
            'book_title': book.title,
        },
        estimated_minutes=10,
    )


# ── Priority 5: vocab ───────────────────────────────────────────────────────

def _check_vocab(user_id: int, db) -> Optional[NextStep]:
    from app.study.models import UserWord

    has_words = UserWord.query.filter_by(user_id=user_id).first() is not None
    if not has_words:
        return None

    reason = 'Review your vocabulary to strengthen retention'
    return NextStep(
        kind='vocab',
        reason=reason,
        data={'has_words': True},
        estimated_minutes=5,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────

_LESSON_TIMES = {
    'grammar': 12,
    'vocabulary': 8,
    'quiz': 6,
    'text': 15,
    'matching': 5,
}


def _lesson_minutes(lesson_type: Optional[str]) -> int:
    return _LESSON_TIMES.get(lesson_type or '', 10)
