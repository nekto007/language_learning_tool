# app/admin/services/activity_feed_service.py

"""Activity feed service — aggregates events from multiple sources for the admin activity view."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


EVENT_TYPE_LABELS = {
    'registered': 'Регистрация',
    'lesson_opened': 'Первое открытие урока',
    'lesson_attempt': 'Проверка работы',
    'listening_submitted': 'Аудиозадание отправлено',
    'writing_submitted': 'Письменная работа отправлена',
    'pronunciation_attempt': 'Проверка произношения',
    'lesson_completed': 'Урок завершён',
    'achievement_granted': 'Достижение получено',
    'xp_awarded': 'XP начислен',
    'day_secured': 'День закрыт',
    'admin_action': 'Действие администратора',
}

ALL_EVENT_TYPES = list(EVENT_TYPE_LABELS.keys())

_GRADED_LESSON_TYPES = frozenset((
    'dictation', 'audio_fill_blank', 'translation', 'sentence_correction',
    'sentence_completion', 'collocation_matching', 'quiz', 'ordering_quiz',
    'translation_quiz', 'listening_quiz', 'dialogue_completion_quiz',
    'grammar', 'matching', 'final_test', 'listening_immersion',
))


@dataclass
class ActivityEvent:
    timestamp: datetime
    user_id: int | None
    user_email: str | None
    event_type: str
    description: str
    detail_url: str | None = None
    user_name: str | None = None
    lesson_id: int | None = None
    lesson_type: str | None = None
    module_title: str | None = None
    score: float | None = None
    attempt_number: int | None = None
    source: str | None = None
    event_id: int | None = None
    content_version: int | None = None
    passed: bool | None = None


def get_recent_events(
    db_session,
    limit: int = 50,
    offset: int = 0,
    user_id: int | None = None,
    event_types: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_errors: list[str] | None = None,
) -> list[ActivityEvent]:
    """Aggregate recent events from multiple tables, newest first.

    Fetches from each applicable source up to (offset + limit) rows,
    merges in Python, and applies final offset/limit slice.
    """
    if event_types is None:
        event_types = ALL_EVENT_TYPES

    # Fetch enough from each source to satisfy offset + limit after merge
    max_per_source = offset + limit

    all_events: list[ActivityEvent] = []
    fetchers = {
        'registered': _fetch_registered,
        'lesson_opened': _fetch_lesson_opened,
        'lesson_attempt': _fetch_lesson_attempts,
        'listening_submitted': _fetch_listening_submissions,
        'writing_submitted': _fetch_writing_submissions,
        'pronunciation_attempt': _fetch_pronunciation_attempts,
        'lesson_completed': _fetch_lesson_completed,
        'achievement_granted': _fetch_achievements,
        'xp_awarded': _fetch_xp_events,
        'day_secured': _fetch_day_secured,
        'admin_action': _fetch_admin_actions,
    }
    for event_type in dict.fromkeys(event_types):
        fetcher = fetchers.get(event_type)
        if fetcher is None:
            continue
        try:
            # Each source gets an isolated savepoint. A missing/outdated table
            # must not leave PostgreSQL's outer transaction aborted and make
            # every subsequent source disappear. Callers use a clean read-only
            # session; begin_nested may flush unrelated pending ORM writes.
            with db_session.begin_nested():
                source_events = fetcher(db_session, user_id, date_from, date_to, max_per_source)
            all_events.extend(source_events)
        except Exception:
            logger.exception('Failed to fetch %s events', event_type)
            if source_errors is not None:
                source_errors.append(event_type)

    for event in all_events:
        # ORM timestamps are historically naive UTC, but imported events may
        # carry an offset. Keep the public list uniform and sort safely.
        if event.timestamp is not None and event.timestamp.tzinfo is not None:
            event.timestamp = event.timestamp.astimezone(UTC).replace(tzinfo=None)
    all_events.sort(key=lambda event: (
        event.timestamp or datetime.min, event.source or event.event_type,
        event.event_id or 0, event.user_id or 0,
    ), reverse=True)
    return all_events[offset: offset + limit]


# ---------------------------------------------------------------------------
# Private fetch helpers
# ---------------------------------------------------------------------------

def _student_url(user_id, lesson_id=None):
    suffix = f'#lesson-{lesson_id}' if lesson_id is not None else ''
    return f'/admin/activity/students/{user_id}{suffix}'


def _filtered(query, user_column, timestamp_column, user_id, date_from, date_to, limit, id_column):
    if user_id is not None:
        query = query.filter(user_column == user_id)
    if date_from:
        query = query.filter(timestamp_column >= date_from)
    if date_to:
        query = query.filter(timestamp_column < date_to + timedelta(days=1))
    return query.order_by(timestamp_column.desc(), id_column.desc()).limit(limit)


def _fetch_registered(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User

    query = db_session.query(User).filter(User.created_at.isnot(None))
    query = _filtered(query, User.id, User.created_at, user_id, date_from, date_to, limit, User.id)
    return [ActivityEvent(
        timestamp=user.created_at, user_id=user.id, user_email=user.email,
        event_type='registered', description='Зарегистрировался',
        detail_url=_student_url(user.id), user_name=user.username,
        source='users', event_id=user.id,
    ) for user in query]


def _fetch_lesson_opened(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User
    from app.curriculum.models import LessonProgress, Lessons, Module
    from sqlalchemy import or_

    query = (db_session.query(LessonProgress, User, Lessons, Module)
             .join(User, User.id == LessonProgress.user_id)
             .outerjoin(Lessons, Lessons.id == LessonProgress.lesson_id)
             .outerjoin(Module, Module.id == Lessons.module_id)
             .filter(LessonProgress.started_at.isnot(None),
                     or_(LessonProgress.data.is_(None),
                         LessonProgress.data['test_out'].as_boolean().isnot(True))))
    query = _filtered(query, LessonProgress.user_id, LessonProgress.started_at,
                      user_id, date_from, date_to, limit, LessonProgress.id)
    return [ActivityEvent(
        timestamp=progress.started_at, user_id=user.id, user_email=user.email,
        event_type='lesson_opened',
        description=f'Первое записанное открытие «{lesson.title if lesson else "Удалённый урок"}»',
        detail_url=_student_url(user.id, progress.lesson_id), user_name=user.username,
        lesson_id=progress.lesson_id, lesson_type=lesson.type if lesson else None,
        module_title=module.title if module else None, source='lesson_progress', event_id=progress.id,
    ) for progress, user, lesson, module in query]


def _fetch_lesson_attempts(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User
    from app.curriculum.models import LessonAttempt, Lessons, Module
    from sqlalchemy import or_

    # Some real graders historically stored zero total_questions. Do not
    # discard them, but exclude passive reading and theory-only attempts.
    query = (db_session.query(LessonAttempt, User, Lessons, Module)
             .join(User, User.id == LessonAttempt.user_id)
             .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
             .outerjoin(Module, Module.id == Lessons.module_id)
             .filter(LessonAttempt.completed_at.isnot(None), LessonAttempt.score.isnot(None),
                     Lessons.type.in_(_GRADED_LESSON_TYPES),
                     or_(Lessons.type.notin_(('grammar', 'listening_immersion')), LessonAttempt.total_questions > 0)))
    query = _filtered(query, LessonAttempt.user_id, LessonAttempt.completed_at,
                      user_id, date_from, date_to, limit, LessonAttempt.id)
    events = []
    for attempt, user, lesson, module in query:
        outcome = 'пройдено' if attempt.passed is True else 'не пройдено' if attempt.passed is False else 'результат'
        events.append(ActivityEvent(
            timestamp=attempt.completed_at, user_id=user.id, user_email=user.email,
            event_type='lesson_attempt',
            description=f'Проверка «{lesson.title}»: попытка {attempt.attempt_number}, {outcome}, {attempt.score:g}%',
            detail_url=_student_url(user.id, lesson.id), user_name=user.username,
            lesson_id=lesson.id, lesson_type=lesson.type, module_title=module.title if module else None,
            score=attempt.score, attempt_number=attempt.attempt_number,
            source='lesson_attempts', event_id=attempt.id, passed=attempt.passed,
        ))
    return events


def _fetch_listening_submissions(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User
    from app.curriculum.models import ListeningAttempt, Lessons, Module

    query = (db_session.query(ListeningAttempt, User, Lessons, Module)
             .join(User, User.id == ListeningAttempt.user_id)
             .outerjoin(Lessons, Lessons.id == ListeningAttempt.lesson_id)
             .outerjoin(Module, Module.id == Lessons.module_id))
    query = _filtered(query, ListeningAttempt.user_id, ListeningAttempt.created_at,
                      user_id, date_from, date_to, limit, ListeningAttempt.id)
    events = []
    for attempt, user, lesson, module in query:
        # Legacy immersion wrote 100 after a checkbox; this table alone cannot
        # distinguish it from comprehension. Actual immersion grades now have
        # a separate positive-question LessonAttempt, displayed above.
        score = attempt.score if lesson and lesson.type in ('dictation', 'audio_fill_blank') else None
        percentage = f': {score:g}%' if score is not None else ''
        replay_detail = ('повторы не измерялись' if lesson and lesson.type == 'listening_immersion'
                         else f'повторов аудио: {attempt.replay_count}')
        events.append(ActivityEvent(
            timestamp=attempt.created_at, user_id=user.id, user_email=user.email,
            event_type='listening_submitted',
            description=f'Аудиоотправка «{lesson.title if lesson else "Удалённый урок"}»{percentage}, '
                        f'{replay_detail}',
            detail_url=_student_url(user.id, attempt.lesson_id), user_name=user.username,
            lesson_id=attempt.lesson_id, lesson_type=lesson.type if lesson else None,
            module_title=module.title if module else None, score=score,
            source='listening_attempts', event_id=attempt.id,
        ))
    return events


def _fetch_writing_submissions(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User
    from app.curriculum.models import UserWritingAttempt, Lessons, Module

    # Do not select response_text or grammar_matches.
    query = (db_session.query(UserWritingAttempt.id, UserWritingAttempt.created_at,
                             UserWritingAttempt.lesson_id, UserWritingAttempt.word_count,
                             User.id, User.username, User.email, Lessons.title, Lessons.type, Module.title)
             .join(User, User.id == UserWritingAttempt.user_id)
             .outerjoin(Lessons, Lessons.id == UserWritingAttempt.lesson_id)
             .outerjoin(Module, Module.id == Lessons.module_id)
             .filter(UserWritingAttempt.word_count > 0))
    query = _filtered(query, UserWritingAttempt.user_id, UserWritingAttempt.created_at,
                      user_id, date_from, date_to, limit, UserWritingAttempt.id)
    return [ActivityEvent(
        timestamp=at, user_id=uid, user_email=email, event_type='writing_submitted',
        description=f'«{title or "Удалённый урок"}»: отправлен текст, {words} слов',
        detail_url=_student_url(uid, lesson_id), user_name=username,
        lesson_id=lesson_id, lesson_type=lesson_type, module_title=module_title,
        source='user_writing_attempts', event_id=event_id,
    ) for event_id, at, lesson_id, words, uid, username, email, title, lesson_type, module_title in query]


def _fetch_pronunciation_attempts(db_session, user_id, date_from, date_to, limit):
    from app.auth.models import User
    from app.curriculum.models import PronunciationAttempt

    # Word and recognized_text are unnecessary for the activity timeline.
    query = (db_session.query(PronunciationAttempt.id, PronunciationAttempt.created_at,
                             PronunciationAttempt.matched, User.id, User.username, User.email)
             .join(User, User.id == PronunciationAttempt.user_id))
    query = _filtered(query, PronunciationAttempt.user_id, PronunciationAttempt.created_at,
                      user_id, date_from, date_to, limit, PronunciationAttempt.id)
    return [ActivityEvent(
        timestamp=at, user_id=uid, user_email=email, event_type='pronunciation_attempt',
        description='Проверка произношения: ' + ('совпадение найдено' if matched else 'совпадение не найдено'),
        detail_url=_student_url(uid), user_name=username,
        source='pronunciation_attempts', event_id=event_id,
    ) for event_id, at, matched, uid, username, email in query]


def _completion_score(progress, lesson):
    """Return only a graded result, never a synthetic completion percentage."""
    data = progress.data if isinstance(progress.data, dict) else {}
    if data.get('test_out') is True or data.get('assessment') == 'self_review' or lesson is None or lesson.type not in _GRADED_LESSON_TYPES:
        return None
    if lesson.type in ('grammar', 'listening_immersion'):
        count = data.get('total_questions') or data.get('total_exercises') or 0
        if not isinstance(count, (int, float)) or count <= 0:
            return None
    return progress.score


def _fetch_lesson_completed(db_session, user_id, date_from, date_to, limit) -> list[ActivityEvent]:
    from app.auth.models import User
    from app.curriculum.models import LessonProgress, Lessons

    q = (
        db_session.query(LessonProgress, User, Lessons)
        .join(User, User.id == LessonProgress.user_id)
        .outerjoin(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(LessonProgress.status == 'completed')
        .filter(LessonProgress.completed_at.isnot(None))
    )
    if user_id is not None:
        q = q.filter(LessonProgress.user_id == user_id)
    if date_from:
        q = q.filter(LessonProgress.completed_at >= date_from)
    if date_to:
        q = q.filter(LessonProgress.completed_at < date_to + timedelta(days=1))
    q = q.order_by(LessonProgress.completed_at.desc(), LessonProgress.id.desc()).limit(limit)

    events = []
    for lp, user, lesson in q:
        score = _completion_score(lp, lesson)
        score_str = f', {round(score)}%' if score is not None else ''
        lesson_title = lesson.title if lesson else f'#{lp.lesson_id} (удалён)'
        test_out = isinstance(lp.data, dict) and lp.data.get('test_out') is True
        events.append(ActivityEvent(
            timestamp=lp.completed_at,
            user_id=user.id,
            user_email=user.email,
            event_type='lesson_completed',
            description=f'Завершил урок «{lesson_title}»{score_str}' + (' (экстерном)' if test_out else ''),
            detail_url=_student_url(user.id, lp.lesson_id), user_name=user.username,
            lesson_id=lp.lesson_id, lesson_type=lesson.type if lesson else None,
            score=score, source='lesson_progress', event_id=lp.id,
        ))
    return events


def _fetch_achievements(db_session, user_id, date_from, date_to, limit) -> list[ActivityEvent]:
    from app.auth.models import User
    from app.study.models import Achievement, UserAchievement

    q = (
        db_session.query(UserAchievement, User, Achievement)
        .join(User, User.id == UserAchievement.user_id)
        .outerjoin(Achievement, Achievement.id == UserAchievement.achievement_id)
    )
    if user_id is not None:
        q = q.filter(UserAchievement.user_id == user_id)
    if date_from:
        q = q.filter(UserAchievement.earned_at >= date_from)
    if date_to:
        q = q.filter(UserAchievement.earned_at < date_to + timedelta(days=1))
    q = q.order_by(UserAchievement.earned_at.desc(), UserAchievement.id.desc()).limit(limit)

    events = []
    for ua, user, ach in q:
        ach_name = ach.name if ach else f'#{ua.achievement_id} (удалён)'
        events.append(ActivityEvent(
            timestamp=ua.earned_at,
            user_id=user.id,
            user_email=user.email,
            event_type='achievement_granted',
            description=f'Получил достижение «{ach_name}»',
            detail_url=_student_url(user.id), user_name=user.username,
            source='user_achievements', event_id=ua.id,
        ))
    return events


def _fetch_xp_events(db_session, user_id, date_from, date_to, limit) -> list[ActivityEvent]:
    from app.achievements.models import StreakEvent
    from app.auth.models import User

    q = (
        db_session.query(StreakEvent, User)
        .join(User, User.id == StreakEvent.user_id)
        .filter(StreakEvent.event_type.like('xp_%'))
    )
    if user_id is not None:
        q = q.filter(StreakEvent.user_id == user_id)
    if date_from:
        q = q.filter(StreakEvent.created_at >= date_from)
    if date_to:
        q = q.filter(StreakEvent.created_at < date_to + timedelta(days=1))
    q = q.order_by(StreakEvent.created_at.desc(), StreakEvent.id.desc()).limit(limit)

    events = []
    for se, user in q:
        # Unified XP write-paths store the awarded amount in details['xp'];
        # coins_delta is always 0 for xp_* events.
        details = se.details or {}
        xp_amount = details.get('xp') or se.coins_delta or 0
        label = se.event_type.replace('xp_', '').replace('_', ' ')
        events.append(ActivityEvent(
            timestamp=se.created_at,
            user_id=user.id,
            user_email=user.email,
            event_type='xp_awarded',
            description=f'+{xp_amount} XP ({label})',
            detail_url=_student_url(user.id), user_name=user.username,
            source='streak_events', event_id=se.id,
        ))
    return events


def _fetch_day_secured(db_session, user_id, date_from, date_to, limit) -> list[ActivityEvent]:
    from app.auth.models import User
    from app.daily_plan.models import DailyPlanLog

    q = (
        db_session.query(DailyPlanLog, User)
        .join(User, User.id == DailyPlanLog.user_id)
        .filter(DailyPlanLog.secured_at.isnot(None))
    )
    if user_id is not None:
        q = q.filter(DailyPlanLog.user_id == user_id)
    if date_from:
        q = q.filter(DailyPlanLog.secured_at >= date_from)
    if date_to:
        q = q.filter(DailyPlanLog.secured_at < date_to + timedelta(days=1))
    q = q.order_by(DailyPlanLog.secured_at.desc(), DailyPlanLog.id.desc()).limit(limit)

    events = []
    for log, user in q:
        mission_str = f' ({log.mission_type})' if log.mission_type else ''
        events.append(ActivityEvent(
            timestamp=log.secured_at,
            user_id=user.id,
            user_email=user.email,
            event_type='day_secured',
            description=f'День закрыт{mission_str} ({log.plan_date})',
            detail_url=_student_url(user.id), user_name=user.username,
            source='daily_plan_log', event_id=log.id,
        ))
    return events


def _fetch_admin_actions(db_session, user_id, date_from, date_to, limit) -> list[ActivityEvent]:
    from app.admin.audit import AdminAuditLog
    from app.auth.models import User

    q = (
        db_session.query(AdminAuditLog, User)
        .join(User, User.id == AdminAuditLog.admin_id, isouter=True)
    )
    # user_id filter applies to admin_id for admin_action events
    if user_id is not None:
        q = q.filter(AdminAuditLog.admin_id == user_id)
    if date_from:
        q = q.filter(AdminAuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(AdminAuditLog.created_at < date_to + timedelta(days=1))
    q = q.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).limit(limit)

    events = []
    for log, admin_user in q:
        email = admin_user.email if admin_user else f'admin#{log.admin_id}'
        target_str = ''
        if log.target_type:
            target_str = f' → {log.target_type}'
            if log.target_id:
                target_str += f'#{log.target_id}'
        events.append(ActivityEvent(
            timestamp=log.created_at,
            user_id=log.admin_id,
            user_email=email,
            event_type='admin_action',
            description=f'{log.action}{target_str}',
            detail_url=_student_url(log.admin_id) if admin_user else None,
            user_name=admin_user.username if admin_user else None,
            source='admin_audit_log', event_id=log.id,
        ))
    return events
