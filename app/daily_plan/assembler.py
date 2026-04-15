from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress
from app.grammar_lab.models import (
    GrammarTopic,
    UserGrammarExercise,
    UserGrammarTopicStatus,
)
from app.study.deck_utils import get_daily_plan_mix_word_ids
from app.study.models import UserWord, UserCardDirection
from app.books.models import Book, Chapter, UserChapterProgress

from app.daily_plan.models import (
    Mission,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PrimaryGoal,
    PrimarySource,
    SourceKind,
)
from app.daily_plan.repair_pressure import RepairBreakdown

def _count_srs_due(user_id: int) -> int:
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

    return query.scalar() or 0


def _count_grammar_due(user_id: int) -> int:
    now = datetime.now(timezone.utc)
    return (
        db.session.query(func.count(UserGrammarExercise.id))
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.state.in_(('review', 'relearning')),
            UserGrammarExercise.next_review <= now,
        )
        .scalar()
    ) or 0


def _find_next_lesson(user_id: int) -> Optional[dict[str, Any]]:
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).order_by(LessonProgress.completed_at.desc()).first()

    if last_completed:
        lesson = Lessons.query.get(last_completed.lesson_id)
        if lesson:
            module = Module.query.get(lesson.module_id)
            if module:
                next_l = Lessons.query.filter(
                    Lessons.module_id == module.id,
                    Lessons.number > lesson.number,
                ).order_by(Lessons.number).first()

                if not next_l:
                    next_module = Module.query.filter(
                        Module.level_id == module.level_id,
                        Module.number == module.number + 1,
                    ).first()
                    if next_module:
                        next_l = Lessons.query.filter(
                            Lessons.module_id == next_module.id,
                        ).order_by(Lessons.number).first()

                if not next_l:
                    current_level = CEFRLevel.query.get(module.level_id)
                    if current_level:
                        next_level = CEFRLevel.query.filter(
                            CEFRLevel.order > current_level.order,
                        ).order_by(CEFRLevel.order).first()
                        if next_level:
                            next_lvl_module = Module.query.filter_by(
                                level_id=next_level.id,
                            ).order_by(Module.number).first()
                            if next_lvl_module:
                                next_l = Lessons.query.filter_by(
                                    module_id=next_lvl_module.id,
                                ).order_by(Lessons.number).first()

                if next_l:
                    nl_module = Module.query.get(next_l.module_id)
                    return {
                        'title': next_l.title,
                        'lesson_id': next_l.id,
                        'module_id': next_l.module_id,
                        'module_number': nl_module.number if nl_module else None,
                        'lesson_type': next_l.type,
                    }

    first_module = Module.query.join(CEFRLevel).order_by(
        CEFRLevel.order, Module.number,
    ).first()
    if first_module:
        first_lesson = Lessons.query.filter_by(
            module_id=first_module.id,
        ).order_by(Lessons.number).first()
        if first_lesson:
            return {
                'title': first_lesson.title,
                'lesson_id': first_lesson.id,
                'module_id': first_lesson.module_id,
                'module_number': first_module.number,
                'lesson_type': first_lesson.type,
            }
    return None


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
    ).order_by(GrammarTopic.order).first()

    if weak:
        topic = GrammarTopic.query.get(weak.topic_id)
        if topic:
            return {'title': topic.title, 'topic_id': topic.id}

    return None


def _make_recall_phase(source_kind: SourceKind, has_srs: bool) -> MissionPhase:
    if has_srs:
        return MissionPhase(
            phase=PhaseKind.recall,
            title="Разогрев серии",
            source_kind=SourceKind.srs,
            mode="srs_review",
        )
    return MissionPhase(
        phase=PhaseKind.recall,
        title="Вспоминаем главное",
        source_kind=source_kind,
        mode="guided_recall",
    )


def _make_close_phase() -> MissionPhase:
    return MissionPhase(
        phase=PhaseKind.close,
        title="Отличная работа!",
        source_kind=SourceKind.vocab,
        mode="success_marker",
        required=False,
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

    if primary_source == SourceKind.book_course:
        bc_lesson = _find_next_book_course_lesson(user_id)
        if not bc_lesson:
            return None

        phases = [
            _make_recall_phase(SourceKind.book_course, srs_due > 0),
            MissionPhase(
                phase=PhaseKind.learn,
                title="Главный шаг миссии",
                source_kind=SourceKind.book_course,
                mode="book_course_lesson",
            ),
            MissionPhase(
                phase=PhaseKind.use,
                title="Практика без подсказок",
                source_kind=SourceKind.book_course,
                mode="book_course_practice",
            ),
        ]

        if srs_due > 0:
            phases.append(MissionPhase(
                phase=PhaseKind.check,
                title="Контрольный раунд",
                source_kind=SourceKind.srs,
                mode="micro_check",
                required=False,
            ))

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

    phases = [
        _make_recall_phase(SourceKind.normal_course, srs_due > 0),
        MissionPhase(
            phase=PhaseKind.learn,
            title="Главный шаг миссии",
            source_kind=SourceKind.normal_course,
            mode="curriculum_lesson",
        ),
        MissionPhase(
            phase=PhaseKind.use,
            title="Практика без подсказок",
            source_kind=SourceKind.normal_course,
            mode="lesson_practice",
        ),
    ]

    if srs_due > 0:
            phases.append(MissionPhase(
                phase=PhaseKind.check,
                title="Контрольный раунд",
                source_kind=SourceKind.srs,
                mode="micro_check",
                required=False,
            ))

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

    if srs_due == 0 and grammar_due == 0:
        return None

    grammar_topic = _find_weak_grammar_topic(user_id)

    phases: list[MissionPhase] = [
        MissionPhase(
            phase=PhaseKind.recall,
            title="Возвращаем забытое",
            source_kind=SourceKind.srs,
            mode="srs_review" if srs_due > 0 else "guided_recall",
        ),
    ]

    if grammar_topic:
        phases.append(MissionPhase(
            phase=PhaseKind.learn,
            title="Разбираем слабое место",
            source_kind=SourceKind.grammar_lab,
            mode="grammar_practice",
        ))
    else:
        phases.append(MissionPhase(
            phase=PhaseKind.learn,
            title="Подтягиваем слова",
            source_kind=SourceKind.vocab,
            mode="vocab_drill",
        ))

    phases.append(MissionPhase(
        phase=PhaseKind.use,
        title="Сразу применяем",
        source_kind=SourceKind.grammar_lab if grammar_topic else SourceKind.vocab,
        mode="targeted_quiz" if grammar_topic else "meaning_prompt",
    ))

    phases.append(_make_close_phase())

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
            kind=SourceKind.srs if srs_due > 0 else SourceKind.grammar_lab,
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

    phases = [
        MissionPhase(
            phase=PhaseKind.recall,
            title="Входим в контекст",
            source_kind=SourceKind.vocab,
            mode="book_vocab_recall" if srs_due > 0 else "guided_recall",
        ),
        MissionPhase(
            phase=PhaseKind.read,
            title="Читаем следующий фрагмент",
            source_kind=SourceKind.books,
            mode="book_reading",
        ),
        MissionPhase(
            phase=PhaseKind.use,
            title="Вытаскиваем язык из текста",
            source_kind=SourceKind.vocab,
            mode="reading_vocab_extract",
        ),
    ]

    if srs_due > 0:
        phases.append(MissionPhase(
            phase=PhaseKind.check,
            title="Закрываем чтение короткой проверкой",
            source_kind=SourceKind.vocab,
            mode="meaning_prompt",
            required=False,
        ))

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
