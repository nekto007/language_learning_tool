from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.navigation import find_next_lesson
from app.daily_plan.level_utils import get_user_current_cefr_level, _cefr_code_to_order
from app.daily_plan.mission_selector import detect_primary_track
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress
from app.grammar_lab.models import (
    GrammarTopic,
    UserGrammarExercise,
    UserGrammarTopicStatus,
)
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.books.models import Book, Chapter, UserChapterProgress

from app.daily_plan.models import (
    MODE_CATEGORY_MAP,
    Mission,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PhasePreview,
    PrimaryGoal,
    PrimarySource,
    SourceKind,
)
from app.daily_plan.repair_pressure import RepairBreakdown

logger = logging.getLogger(__name__)


# Fallback substitution rules: when a category appears twice,
# replace the second occurrence with an alternative (mode, SourceKind).
_CATEGORY_SUBSTITUTIONS: dict[str, list[tuple[str, SourceKind]]] = {
    'words': [
        ('grammar_practice', SourceKind.grammar_lab),
        ('targeted_quiz', SourceKind.grammar_lab),
        ('book_reading', SourceKind.books),
    ],
    'lesson': [
        ('vocab_drill', SourceKind.vocab),
        ('grammar_practice', SourceKind.grammar_lab),
    ],
    'grammar': [
        ('vocab_drill', SourceKind.vocab),
        ('meaning_prompt', SourceKind.vocab),
        ('book_reading', SourceKind.books),
    ],
    'books': [
        ('vocab_drill', SourceKind.vocab),
        ('grammar_practice', SourceKind.grammar_lab),
    ],
    'book_course': [
        ('vocab_drill', SourceKind.vocab),
        ('grammar_practice', SourceKind.grammar_lab),
    ],
}

_SUBSTITUTE_MODE_TITLES: dict[str, str] = {
    'grammar_practice': 'Практика грамматики',
    'targeted_quiz': 'Грамматический квиз',
    'book_reading': 'Читаем книгу',
    'vocab_drill': 'Тренировка слов',
    'meaning_prompt': 'Угадай значение',
}

# Bonus phase: 20% chance, one of three fun mini-modes.
BONUS_PHASE_CHANCE = 0.20
BONUS_MODES: list[tuple[str, str]] = [
    ('fun_fact_quiz', 'Викторина: факты языка'),
    ('speed_review', 'Спидран: быстрое повторение'),
    ('word_scramble', 'Анаграмма: собери слово'),
]


def _maybe_add_bonus_phase(
    phases: list[MissionPhase],
    rng: Optional[random.Random] = None,
) -> list[MissionPhase]:
    """Append a random bonus phase with BONUS_PHASE_CHANCE probability.

    The bonus phase is always required=False and uses PhaseKind.bonus.
    Callers pass a seeded `rng` in tests for deterministic behaviour.
    """
    _rng = rng or random
    if _rng.random() >= BONUS_PHASE_CHANCE:
        return phases
    mode, title = _rng.choice(BONUS_MODES)
    bonus = MissionPhase(
        phase=PhaseKind.bonus,
        title=title,
        source_kind=SourceKind.vocab,
        mode=mode,
        required=False,
        preview=PhasePreview(
            content_title=title,
            estimated_minutes=3,
        ),
    )
    return phases + [bonus]


def _deduplicate_phases(phases: list[MissionPhase]) -> list[MissionPhase]:
    """Ensure no two phases share the same activity category.

    When a duplicate is detected, the later phase is replaced with an
    alternative mode from ``_CATEGORY_SUBSTITUTIONS`` whose category has
    not been seen yet.  If no viable substitute exists the phase is kept
    as-is (``MissionPlan.__post_init__`` will log a warning).
    """
    seen_categories: set[str] = set()
    used_modes: set[str] = {p.mode for p in phases}
    result: list[MissionPhase] = []

    for phase in phases:
        cat = MODE_CATEGORY_MAP.get(phase.mode)
        if cat is None or cat not in seen_categories:
            if cat is not None:
                seen_categories.add(cat)
            result.append(phase)
            continue

        # Duplicate category — try to substitute.
        substituted = False
        for alt_mode, alt_source in _CATEGORY_SUBSTITUTIONS.get(cat, []):
            alt_cat = MODE_CATEGORY_MAP.get(alt_mode)
            if alt_cat in seen_categories or alt_mode in used_modes:
                continue
            result.append(MissionPhase(
                phase=phase.phase,
                title=_SUBSTITUTE_MODE_TITLES.get(alt_mode, phase.title),
                source_kind=alt_source,
                mode=alt_mode,
                required=phase.required,
                completed=phase.completed,
                preview=None,
            ))
            if alt_cat is not None:
                seen_categories.add(alt_cat)
            used_modes.add(alt_mode)
            substituted = True
            break

        if not substituted:
            # No viable substitute; keep the original.
            result.append(phase)
            seen_categories.add(cat)

    return result


def _count_srs_due(user_id: int) -> int:
    """Count SRS cards due within the daily-plan mix pool.

    Mission-plan allocation only promises cards the ``/study?source=daily_plan_mix``
    endpoint can actually serve, so we filter by the mix word ids. An empty mix
    means zero due cards are plannable.
    """
    from app.srs.counting import count_due_cards

    mix_word_ids = get_daily_plan_mix_word_ids(user_id)
    if not mix_word_ids:
        return 0
    return count_due_cards(user_id, db, word_ids=mix_word_ids)


def _count_grammar_due(user_id: int) -> int:
    # next_review is stored as naive UTC (Column(DateTime)), so now must be naive UTC too
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (
        db.session.query(func.count(UserGrammarExercise.id))
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.state.in_(('review', 'relearning')),
            UserGrammarExercise.next_review <= now,
        )
        .scalar()
    ) or 0



def _get_remaining_card_budget(user_id: int) -> tuple[int, int]:
    """Return (remaining_new, remaining_reviews) the user can still study today.

    Delegates to the canonical `get_new_card_budget` so mission-plan,
    linear-plan and /study all share one adaptive-limit source of truth.
    """
    from app.srs.counting import get_new_card_budget

    return get_new_card_budget(user_id, db)


def _allocate_srs_budget(srs_due: int, remaining_reviews: int) -> tuple[int, int]:
    """Split the daily review budget between recall and micro_check phases.

    Returns (recall_count, check_count). Unique review cards across the plan
    stay within ``remaining_reviews``. About 1/3 of the budget (capped at
    10) is reserved for the final micro_check; the recall phase takes the
    rest. When the pool is tiny (<3), check is skipped so we don't promise
    a phase we can't honor.
    """
    effective = max(0, min(srs_due, remaining_reviews))
    if effective <= 0:
        return 0, 0
    check_count = min(10, effective // 3)
    recall_count = effective - check_count
    return recall_count, check_count


def _has_guided_recall_content(user_id: int) -> bool:
    """Return True when a `guided_recall` phase would have cards to show.

    Used at plan formation to skip the recall phase when there is literally
    nothing for the user to study right now — either because the daily-plan
    mix pool is empty/fully studied today, or because the new-card budget is
    already spent elsewhere. Without this check, a user can land in an empty
    card session and see the daily-limit banner mid-flow.
    """
    from app.study.services.srs_service import SRSService

    mix_word_ids = get_daily_plan_mix_word_ids(user_id)
    if not mix_word_ids:
        return False

    counts = SRSService.get_card_counts(user_id, deck_word_ids=mix_word_ids)
    if counts['due_count'] > 0:
        return True
    return counts['new_count'] > 0 and counts['can_study_new']


def _find_next_lesson(user_id: int) -> Optional[dict[str, Any]]:
    """Return the next lesson for the mission assembler.

    Delegates to the canonical curriculum navigation
    (`app.curriculum.navigation.find_next_lesson`) so the mission assembler,
    the linear daily plan, and other surfaces all surface the same
    next-lesson for a given user. The dict shape is preserved for
    downstream mission-assembly code.
    """
    canonical = find_next_lesson(user_id, db)
    if canonical is None:
        return None
    nl_module = Module.query.get(canonical.module_id)
    return {
        'title': canonical.title,
        'lesson_id': canonical.id,
        'module_id': canonical.module_id,
        'module_number': nl_module.number if nl_module else None,
        'lesson_type': canonical.type,
    }


def _find_next_book_course_lesson(user_id: int) -> Optional[dict[str, Any]]:
    enrollment = BookCourseEnrollment.query.filter_by(
        user_id=user_id, status='active',
    ).first()
    if not enrollment:
        return None

    completed_ids = {
        r[0] for r in db.session.query(UserLessonProgress.daily_lesson_id).filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.enrollment_id == enrollment.id,
            UserLessonProgress.status == 'completed',
        ).all()
    }

    lessons = DailyLesson.query.join(
        BookCourseModule, BookCourseModule.id == DailyLesson.book_course_module_id,
    ).filter(
        BookCourseModule.course_id == enrollment.course_id,
    ).order_by(DailyLesson.day_number).all()

    if not lessons:
        logger.warning(
            "_find_next_book_course_lesson: no lessons found for enrollment %s (user_id=%s)",
            enrollment.id, user_id,
        )
        return None

    for dl in lessons:
        if dl.id not in completed_ids:
            course = BookCourse.query.get(enrollment.course_id)
            return {
                'course_id': enrollment.course_id,
                'course_title': course.title if course else None,
                'module_id': dl.book_course_module_id,
                'lesson_id': dl.id,
                'day_number': dl.day_number,
                'lesson_type': dl.lesson_type,
            }
    return None


def _find_next_book(user_id: int) -> Optional[dict[str, Any]]:
    most_recent = db.session.query(Chapter.book_id).join(
        UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id,
    ).filter(
        UserChapterProgress.user_id == user_id,
    ).order_by(UserChapterProgress.updated_at.desc()).first()

    if most_recent:
        book = Book.query.get(most_recent[0])
        if book:
            return {'title': book.title, 'id': book.id}

    book = Book.query.filter(Book.chapters_cnt > 0).order_by(Book.title).first()
    if book:
        return {'title': book.title, 'id': book.id}
    return None


def _find_weak_grammar_topic(user_id: int) -> Optional[dict[str, Any]]:
    weak = UserGrammarTopicStatus.query.join(
        GrammarTopic, GrammarTopic.id == UserGrammarTopicStatus.topic_id,
    ).filter(
        UserGrammarTopicStatus.user_id == user_id,
        UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing']),
    ).order_by(GrammarTopic.order, GrammarTopic.id).first()

    if weak:
        topic = GrammarTopic.query.get(weak.topic_id)
        if topic:
            return {'title': topic.title, 'topic_id': topic.id}

    return None


def _estimate_srs_minutes(count: int) -> int:
    """Estimate minutes for SRS review: ~1 min per 10 cards, min 2."""
    return max(2, (count + 9) // 10)


def _make_recall_phase(source_kind: SourceKind, has_srs: bool, srs_due: int = 0) -> MissionPhase:
    if has_srs:
        return MissionPhase(
            phase=PhaseKind.recall,
            title="Разогрев серии",
            source_kind=SourceKind.srs,
            mode="srs_review",
            preview=PhasePreview(
                item_count=srs_due,
                content_title="Повторение карточек",
                estimated_minutes=_estimate_srs_minutes(srs_due),
            ),
        )
    return MissionPhase(
        phase=PhaseKind.recall,
        title="Вспоминаем главное",
        source_kind=source_kind,
        mode="guided_recall",
        preview=PhasePreview(
            content_title="Быстрый разогрев",
            estimated_minutes=3,
        ),
    )


def _make_close_phase() -> MissionPhase:
    return MissionPhase(
        phase=PhaseKind.close,
        title="Отличная работа!",
        source_kind=SourceKind.vocab,
        mode="success_marker",
        required=False,
        preview=PhasePreview(
            content_title="Завершение миссии",
            estimated_minutes=1,
        ),
    )


def assemble_progress_mission(
    user_id: int,
    primary_source: SourceKind,
    reason_code: str = "primary_track_progress",
    reason_text: str = "Двигаемся вперёд по курсу",
    tz: Optional[str] = None,
) -> Optional[MissionPlan]:
    """Build Progress mission: Recall → Learn (next lesson) → Use (practice) → optional Check."""
    srs_due = _count_srs_due(user_id)
    _, remaining_reviews = _get_remaining_card_budget(user_id)
    recall_count, check_count = _allocate_srs_budget(srs_due, remaining_reviews)
    has_srs_recall = recall_count > 0

    if primary_source == SourceKind.book_course:
        bc_lesson = _find_next_book_course_lesson(user_id)
        if not bc_lesson:
            return None

        bc_title = bc_lesson.get('course_title') or "Книжный курс"
        phases: list[MissionPhase] = []
        if has_srs_recall or _has_guided_recall_content(user_id):
            phases.append(
                _make_recall_phase(SourceKind.book_course, has_srs_recall, recall_count)
            )
        phases.extend([
            MissionPhase(
                phase=PhaseKind.learn,
                title="Главный шаг миссии",
                source_kind=SourceKind.book_course,
                mode="book_course_lesson",
                preview=PhasePreview(
                    content_title=bc_title,
                    estimated_minutes=10,
                ),
            ),
            MissionPhase(
                phase=PhaseKind.use,
                title="Практика без подсказок",
                source_kind=SourceKind.book_course,
                mode="book_course_practice",
                preview=PhasePreview(
                    content_title=bc_title,
                    estimated_minutes=5,
                ),
            ),
        ])

        if check_count > 0:
            phases.append(MissionPhase(
                phase=PhaseKind.check,
                title="Контрольный раунд",
                source_kind=SourceKind.srs,
                mode="micro_check",
                required=False,
                preview=PhasePreview(
                    item_count=check_count,
                    content_title="Мини-проверка",
                    estimated_minutes=3,
                ),
            ))

        # Skipping the recall phase can drop the plan below the 3-phase
        # minimum; bring in a soft close phase so the plan still validates.
        if len(phases) < 3:
            phases.append(_make_close_phase())

        phases = _maybe_add_bonus_phase(phases)
        return MissionPlan(
            plan_version="1",
            mission=Mission(
                type=MissionType.progress,
                title="Продвигаемся по курсу",
                reason_code=reason_code,
                reason_text=reason_text,
            ),
            primary_goal=PrimaryGoal(
                type="advance",
                title="Пройти следующий урок курса",
                success_criterion="lesson_completed",
            ),
            primary_source=PrimarySource(
                kind=SourceKind.book_course,
                id=str(bc_lesson['course_id']),
                label=bc_lesson.get('course_title') or "Книжный курс",
            ),
            phases=phases,
            legacy={'book_course_lesson': bc_lesson},
        )

    next_lesson = _find_next_lesson(user_id)
    if not next_lesson:
        return None

    lesson_title = next_lesson['title']
    lesson_type = next_lesson.get('lesson_type', '')
    lesson_is_card_based = lesson_type in ('card', 'flashcards')

    # When the learn phase is a card-based lesson and there are SRS cards due, both
    # phases would look like identical card sessions to the user. Relabel the recall
    # phase so it's clear these are different activities (SRS review vs. new lesson).
    recall_phase: Optional[MissionPhase]
    if lesson_is_card_based and has_srs_recall:
        recall_phase = MissionPhase(
            phase=PhaseKind.recall,
            title="Карточки SRS: повторение",
            source_kind=SourceKind.srs,
            mode="srs_review",
            preview=PhasePreview(
                item_count=recall_count,
                content_title="Повторение из вашей колоды",
                estimated_minutes=_estimate_srs_minutes(recall_count),
            ),
        )
    elif has_srs_recall or _has_guided_recall_content(user_id):
        recall_phase = _make_recall_phase(
            SourceKind.normal_course, has_srs_recall, recall_count
        )
    else:
        recall_phase = None

    phases = []
    if recall_phase is not None:
        phases.append(recall_phase)
    phases.extend([
        MissionPhase(
            phase=PhaseKind.learn,
            title="Главный шаг миссии",
            source_kind=SourceKind.normal_course,
            mode="curriculum_lesson",
            preview=PhasePreview(
                content_title=lesson_title,
                estimated_minutes=10,
            ),
        ),
        MissionPhase(
            phase=PhaseKind.use,
            title="Практика без подсказок",
            source_kind=SourceKind.normal_course,
            mode="lesson_practice",
            preview=PhasePreview(
                content_title=lesson_title,
                estimated_minutes=5,
            ),
        ),
    ])

    if check_count > 0:
        phases.append(MissionPhase(
            phase=PhaseKind.check,
            title="Контрольный раунд",
            source_kind=SourceKind.srs,
            mode="micro_check",
            required=False,
            preview=PhasePreview(
                item_count=check_count,
                content_title="Мини-проверка",
                estimated_minutes=3,
            ),
        ))

    # Skipping the recall phase can drop the plan below the 3-phase minimum;
    # bring in a soft close phase so the plan still validates.
    if len(phases) < 3:
        phases.append(_make_close_phase())

    phases = _maybe_add_bonus_phase(phases)
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.progress,
            title="Продвигаемся по курсу",
            reason_code=reason_code,
            reason_text=reason_text,
        ),
        primary_goal=PrimaryGoal(
            type="advance",
            title="Пройти следующий урок",
            success_criterion="lesson_completed",
        ),
        primary_source=PrimarySource(
            kind=SourceKind.normal_course,
            id=str(next_lesson['lesson_id']),
            label=next_lesson['title'],
        ),
        phases=phases,
        legacy={'next_lesson': next_lesson},
    )


def assemble_repair_mission(
    user_id: int,
    repair_breakdown: RepairBreakdown,
    reason_code: str = "repair_pressure_high",
    reason_text: str = "У тебя накопились слабые места — давай укрепим основу",
    tz: Optional[str] = None,
) -> Optional[MissionPlan]:
    """Build Repair mission: Recall (overdue SRS) → Learn (weak grammar/vocab) → Use (quiz) → Close."""
    srs_due = _count_srs_due(user_id)
    grammar_due = _count_grammar_due(user_id)
    _, remaining_reviews = _get_remaining_card_budget(user_id)
    recall_count, _check_reserve = _allocate_srs_budget(srs_due, remaining_reviews)
    has_srs_recall = recall_count > 0

    if srs_due == 0 and grammar_due == 0:
        track = detect_primary_track(user_id)
        logger.warning(
            "assemble_repair_mission: no SRS or grammar due for user_id=%s, degrading to %s mission",
            user_id,
            "reading" if track == SourceKind.books else "progress",
        )
        if track == SourceKind.books:
            reading_plan = assemble_reading_mission(
                user_id,
                reason_code="progress_next_step",
                reason_text="Всё повторено — продолжаем чтение",
                tz=tz,
            )
            if reading_plan is not None:
                return reading_plan
            logger.warning(
                "assemble_repair_mission: reading mission returned None for user_id=%s, degrading to progress",
                user_id,
            )
            track = SourceKind.normal_course
        primary_source = (
            track if track in (SourceKind.normal_course, SourceKind.book_course)
            else SourceKind.normal_course
        )
        return assemble_progress_mission(
            user_id,
            primary_source,
            reason_code="progress_next_step",
            reason_text="Всё повторено — двигаемся дальше по курсу",
            tz=tz,
        )

    grammar_topic = _find_weak_grammar_topic(user_id)

    phases: list[MissionPhase] = []
    if has_srs_recall or _has_guided_recall_content(user_id):
        recall_mode = "srs_review" if has_srs_recall else "guided_recall"
        phases.append(MissionPhase(
            phase=PhaseKind.recall,
            title="Возвращаем забытое",
            source_kind=SourceKind.srs,
            mode=recall_mode,
            preview=PhasePreview(
                item_count=recall_count if has_srs_recall else None,
                content_title="Повторение карточек" if has_srs_recall else "Быстрый разогрев",
                estimated_minutes=_estimate_srs_minutes(recall_count) if has_srs_recall else 3,
            ),
        ))

    if grammar_topic:
        phases.append(MissionPhase(
            phase=PhaseKind.learn,
            title="Разбираем слабое место",
            source_kind=SourceKind.grammar_lab,
            mode="grammar_practice",
            preview=PhasePreview(
                content_title=grammar_topic['title'],
                estimated_minutes=7,
            ),
        ))
    else:
        phases.append(MissionPhase(
            phase=PhaseKind.learn,
            title="Подтягиваем слова",
            source_kind=SourceKind.vocab,
            mode="vocab_drill",
            preview=PhasePreview(
                content_title="Тренировка слов",
                estimated_minutes=5,
            ),
        ))

    phases.append(MissionPhase(
        phase=PhaseKind.use,
        title="Сразу применяем",
        source_kind=SourceKind.grammar_lab if grammar_topic else SourceKind.vocab,
        mode="targeted_quiz" if grammar_topic else "meaning_prompt",
        preview=PhasePreview(
            content_title=grammar_topic['title'] if grammar_topic else "Проверка значений",
            estimated_minutes=5,
        ),
    ))

    phases.append(_make_close_phase())

    phases = _deduplicate_phases(phases)
    phases = _maybe_add_bonus_phase(phases)

    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.repair,
            title="Укрепляем основу",
            reason_code=reason_code,
            reason_text=reason_text,
        ),
        primary_goal=PrimaryGoal(
            type="repair",
            title="Закрыть слабые точки",
            success_criterion="repair_session_done",
        ),
        primary_source=PrimarySource(
            kind=SourceKind.srs if srs_due > 0 else (SourceKind.grammar_lab if grammar_topic else SourceKind.vocab),
            id=str(grammar_topic['topic_id']) if grammar_topic else None,
            label=grammar_topic['title'] if grammar_topic else "Повторение слов",
        ),
        phases=phases,
        legacy={
            'overdue_srs': repair_breakdown.overdue_srs_count,
            'grammar_weak': repair_breakdown.grammar_weak_count,
            'grammar_topic': grammar_topic,
        },
    )


def assemble_reading_mission(
    user_id: int,
    reason_code: str = "primary_track_reading",
    reason_text: str = "Продолжим чтение — это твой основной трек",
    tz: Optional[str] = None,
) -> Optional[MissionPlan]:
    """Build Reading mission: Recall (book vocab) → Read (next chapter) → Use (new words) → optional Check."""
    book = _find_next_book(user_id)
    if not book:
        return None

    srs_due = _count_srs_due(user_id)
    _, remaining_reviews = _get_remaining_card_budget(user_id)
    recall_count, check_count = _allocate_srs_budget(srs_due, remaining_reviews)
    has_srs_recall = recall_count > 0
    book_title = book['title']

    phases: list[MissionPhase] = []
    if has_srs_recall or _has_guided_recall_content(user_id):
        phases.append(MissionPhase(
            phase=PhaseKind.recall,
            title="Входим в контекст",
            source_kind=SourceKind.vocab,
            mode="book_vocab_recall" if has_srs_recall else "guided_recall",
            preview=PhasePreview(
                item_count=recall_count if has_srs_recall else None,
                content_title="Слова из книги" if has_srs_recall else "Быстрый разогрев",
                estimated_minutes=_estimate_srs_minutes(recall_count) if has_srs_recall else 3,
            ),
        ))
    phases.extend([
        MissionPhase(
            phase=PhaseKind.read,
            title="Читаем следующий фрагмент",
            source_kind=SourceKind.books,
            mode="book_reading",
            preview=PhasePreview(
                content_title=book_title,
                estimated_minutes=10,
            ),
        ),
        MissionPhase(
            phase=PhaseKind.use,
            title="Вытаскиваем язык из текста",
            source_kind=SourceKind.vocab,
            mode="reading_vocab_extract",
            preview=PhasePreview(
                content_title=book_title,
                estimated_minutes=5,
            ),
        ),
    ])

    if check_count > 0:
        phases.append(MissionPhase(
            phase=PhaseKind.check,
            title="Закрываем чтение короткой проверкой",
            source_kind=SourceKind.vocab,
            mode="meaning_prompt",
            required=False,
            preview=PhasePreview(
                item_count=check_count,
                content_title="Мини-проверка",
                estimated_minutes=3,
            ),
        ))

    # Skipping the recall phase can drop the plan below the 3-phase minimum;
    # bring in a soft close phase so the plan still validates.
    if len(phases) < 3:
        phases.append(_make_close_phase())

    phases = _maybe_add_bonus_phase(phases)
    return MissionPlan(
        plan_version="1",
        mission=Mission(
            type=MissionType.reading,
            title="Читаем и учимся",
            reason_code=reason_code,
            reason_text=reason_text,
        ),
        primary_goal=PrimaryGoal(
            type="read",
            title="Прочитать следующий отрывок",
            success_criterion="reading_completed",
        ),
        primary_source=PrimarySource(
            kind=SourceKind.books,
            id=str(book['id']),
            label=book['title'],
        ),
        phases=phases,
        legacy={'book_to_read': book},
    )
