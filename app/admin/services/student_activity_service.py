"""Read-only, bounded student diagnostics for the protected admin interface.

Progress timestamps describe recorded openings, not active time. Submission
timestamps come from attempt tables; score statistics use graded attempts only.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import and_, case, func, literal, or_, union_all

STATUS_LABELS = {
    'no_lesson': 'Не открывал урок',  # noqa: RUF001
    'opened_no_submission': 'Открыл без отправки',
    'failed_attempts': 'Повторные ошибки',
    'idle_3d': 'Нет действий 3 дня',
    'progressing': 'Проходит обучение',
    'completed_no_next': 'Завершил, не продолжил',
}
STATUS_CLASSES = {
    'no_lesson': 'bg-secondary', 'opened_no_submission': 'bg-warning text-dark',
    'failed_attempts': 'bg-danger', 'idle_3d': 'bg-warning text-dark',
    'progressing': 'bg-success', 'completed_no_next': 'bg-info text-dark',
}
_GRADED_TYPES = (
    'dictation', 'audio_fill_blank', 'translation', 'sentence_correction',
    'sentence_completion', 'collocation_matching', 'quiz', 'ordering_quiz',
    'translation_quiz', 'listening_quiz', 'dialogue_completion_quiz',
    'grammar', 'matching', 'final_test', 'listening_immersion',
)


def _graded_condition(lesson, attempt):
    """Dual-mode theory/listening needs actual questions; self-review is ungraded."""
    return and_(lesson.type.in_(_GRADED_TYPES), attempt.score.isnot(None),
                or_(lesson.type.notin_(('grammar', 'listening_immersion')), attempt.total_questions > 0))


def _now(value=None):
    value = value or datetime.now(UTC)
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _models():
    from app.auth.models import User
    from app.curriculum.models import (
        CEFRLevel, LessonAttempt, LessonProgress, Lessons, ListeningAttempt,
        Module, PronunciationAttempt, UserWritingAttempt,
    )
    return User, CEFRLevel, LessonAttempt, LessonProgress, Lessons, ListeningAttempt, Module, PronunciationAttempt, UserWritingAttempt


def _real_progress(progress_model):
    """A test-out synthetic row records attainment, not a lesson visit."""
    return func.coalesce(progress_model.data['test_out'].as_boolean(), False).is_(False)


def _progress_activity(progress_model, now):
    """Ignore future clock artifacts, falling back to a valid earlier timestamp."""
    return func.coalesce(
        case((progress_model.last_activity <= now, progress_model.last_activity)),
        case((progress_model.completed_at <= now, progress_model.completed_at)),
        case((progress_model.started_at <= now, progress_model.started_at)),
    )


def _module_progress(session, now):
    """Current catalogue attainment, including explicitly marked test-out rows."""
    _, _, _, Progress, Lesson, _, _, _, _ = _models()
    totals = session.query(Lesson.module_id, func.count(Lesson.id).label('lessons_total'))
    totals = totals.group_by(Lesson.module_id).subquery('module_lesson_totals')
    completed = session.query(
        Progress.user_id, Lesson.module_id,
        func.count(func.distinct(case((and_(Progress.status == 'completed', Progress.completed_at <= now),
                                       Progress.lesson_id)))).label('lessons_completed'),
    ).join(Lesson, Lesson.id == Progress.lesson_id).filter(Progress.started_at <= now)
    completed = completed.group_by(Progress.user_id, Lesson.module_id).subquery('user_module_completed_lessons')
    return session.query(
        completed.c.user_id, completed.c.module_id, totals.c.lessons_total, completed.c.lessons_completed,
    ).join(totals, totals.c.module_id == completed.c.module_id).subquery('user_module_attainment')


def _saved_position(data):
    """Expose indexes only; progress.data also contains private answer content."""
    if not isinstance(data, dict):
        return {}
    result = {}
    for key in ('current_question', 'current_index', 'current_page', 'item_index',
                'question_index', 'current_card', 'current_item', 'page', 'current_sentence'):
        value = data.get(key)
        if isinstance(value, str) and len(value) <= 6 and value.isascii() and value.isdigit():
            value = int(value)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000:
            result[key] = value
    return result


def _submission_rows(session, now):
    """Union evidence, used only for max/time/day or distinct-user counts.

    The same dictation can occur in two tables; do not count union rows as
    independent attempts. Zero-question legacy attempts remain visible because
    some graders persisted total_items under a different key.
    """
    _, _, Attempt, _, Lesson, Listening, _, Pronunciation, Writing = _models()
    queries = [
        session.query(Attempt.user_id.label('user_id'), Attempt.lesson_id.label('lesson_id'),
                      Attempt.completed_at.label('at'))
        .join(Lesson, Lesson.id == Attempt.lesson_id)
        .filter(Attempt.completed_at.isnot(None), Attempt.completed_at <= now, _graded_condition(Lesson, Attempt)),
        session.query(Listening.user_id, Listening.lesson_id, Listening.created_at)
        .filter(Listening.created_at <= now),
        session.query(Writing.user_id, Writing.lesson_id, Writing.created_at)
        .filter(Writing.created_at <= now, Writing.word_count > 0),
        session.query(Pronunciation.user_id, literal(None).label('lesson_id'), Pronunciation.created_at)
        .filter(Pronunciation.created_at <= now),
    ]
    return union_all(*(q.statement for q in queries)).subquery('student_submission_events')


def _base_query(session, now, *, include_admin=False):
    User, Level, Attempt, Progress, Lesson, _, Module, _, _ = _models()
    real = _real_progress(Progress)
    activity = _progress_activity(Progress, now)
    opened = and_(real, Progress.status.in_(('in_progress', 'completed')), Progress.started_at <= now)
    pstats = session.query(
        Progress.user_id.label('user_id'),
        func.sum(case((opened, 1), else_=0)).label('lessons_opened'),
        func.sum(case((and_(Progress.status == 'completed', Progress.completed_at <= now), 1), else_=0))
        .label('lessons_completed'),
        func.sum(case((and_(~real, Progress.status == 'completed', Progress.completed_at <= now), 1), else_=0))
        .label('lessons_tested_out'),
        func.max(case((real, activity))).label('last_progress_at'),
    ).filter(Progress.started_at <= now).group_by(Progress.user_id).subquery()
    astats = session.query(
        Attempt.user_id.label('user_id'),
        func.count(Attempt.id).label('graded_attempts'),
        func.sum(case((Attempt.passed.is_(False), 1), else_=0)).label('failed_attempts'),
        func.avg(Attempt.score).label('avg_score'),
    ).join(Lesson, Lesson.id == Attempt.lesson_id).filter(
        Attempt.completed_at.isnot(None), Attempt.completed_at <= now, _graded_condition(Lesson, Attempt),
    ).group_by(Attempt.user_id).subquery()
    module_progress = _module_progress(session, now)
    module_stats = session.query(
        module_progress.c.user_id,
        func.sum(case((and_(module_progress.c.lessons_total > 0,
                            module_progress.c.lessons_completed == module_progress.c.lessons_total), 1),
                      else_=0)).label('modules_completed'),
    ).group_by(module_progress.c.user_id).subquery('student_module_counts')
    events = _submission_rows(session, now)
    sstats = session.query(
        events.c.user_id,
        func.max(events.c.at).label('last_submission_at'),
        func.count(func.distinct(func.date(events.c.at))).label('submission_days'),
    ).group_by(events.c.user_id).subquery()
    latest = session.query(
        Progress.user_id.label('user_id'), Progress.lesson_id.label('lesson_id'),
        Progress.status.label('lesson_status'), activity.label('last_activity'),
        Progress.started_at.label('started_at'), Progress.completed_at.label('completed_at'),
        Progress.score.label('score'), Progress.best_score.label('best_score'),
        Progress.last_score.label('last_score'),
        func.row_number().over(partition_by=Progress.user_id,
                               order_by=(activity.desc(), Progress.id.desc()))
        .label('rank'),
    ).filter(Progress.started_at <= now, real, Progress.status.in_(('in_progress', 'completed'))).subquery()
    latest_attempts = session.query(
        Attempt.user_id, Attempt.lesson_id,
        func.count(Attempt.id).label('attempts'),
        func.sum(case((Attempt.passed.is_(False), 1), else_=0)).label('failed_attempts'),
    ).join(Lesson, Lesson.id == Attempt.lesson_id).filter(
        Attempt.completed_at.isnot(None), Attempt.completed_at <= now, _graded_condition(Lesson, Attempt))
    latest_attempts = latest_attempts.group_by(Attempt.user_id, Attempt.lesson_id).subquery()
    last_progress = pstats.c.last_progress_at
    last_activity = case((or_(last_progress.is_(None), sstats.c.last_submission_at > last_progress),
                          sstats.c.last_submission_at),
                         else_=last_progress)
    n_opened = func.coalesce(pstats.c.lessons_opened, 0)
    status = case(
        (and_(n_opened == 0, sstats.c.last_submission_at.is_(None)), 'no_lesson'),
        (last_activity <= now - timedelta(days=3), 'idle_3d'),
        (and_(latest.c.lesson_status != 'completed', latest_attempts.c.failed_attempts >= 2), 'failed_attempts'),
        (and_(latest.c.lesson_status == 'completed', last_activity <= now - timedelta(days=1)),
         'completed_no_next'),
        (and_(n_opened > 0, sstats.c.last_submission_at.is_(None), latest.c.lesson_status != 'completed',
              func.coalesce(pstats.c.lessons_completed, 0) - func.coalesce(pstats.c.lessons_tested_out, 0) == 0),
         'opened_no_submission'),
        else_='progressing',
    )
    query = session.query(
        User.id.label('user_id'), User.username, User.email, User.created_at,
        User.onboarding_level.label('level'), User.onboarding_completed, User.is_admin, User.acquisition_meta,
        n_opened.label('lessons_opened'),
        func.coalesce(pstats.c.lessons_completed, 0).label('lessons_completed'),
        func.coalesce(pstats.c.lessons_tested_out, 0).label('lessons_tested_out'),
        func.coalesce(module_stats.c.modules_completed, 0).label('modules_completed'),
        func.coalesce(astats.c.graded_attempts, 0).label('graded_attempts'),
        func.coalesce(astats.c.failed_attempts, 0).label('failed_attempts'), astats.c.avg_score,
        sstats.c.last_submission_at, func.coalesce(sstats.c.submission_days, 0).label('submission_days'),
        last_activity.label('last_activity_at'), status.label('status'),
        latest.c.lesson_id, latest.c.lesson_status, latest.c.last_activity,
        latest.c.started_at, latest.c.completed_at, latest.c.score, latest.c.best_score, latest.c.last_score,
        Lesson.title.label('lesson_title'), Lesson.type.label('lesson_type'), Lesson.number.label('lesson_number'),
        Module.id.label('module_id'), Module.number.label('module_number'), Module.title.label('module_title'),
        Level.code.label('lesson_level'),
        module_progress.c.lessons_total.label('module_lessons_total'),
        module_progress.c.lessons_completed.label('module_lessons_completed'),
        func.coalesce(latest_attempts.c.attempts, 0).label('latest_attempts'),
        func.coalesce(latest_attempts.c.failed_attempts, 0).label('latest_failed_attempts'),
    ).select_from(User).outerjoin(pstats, pstats.c.user_id == User.id).outerjoin(astats, astats.c.user_id == User.id)
    query = query.outerjoin(sstats, sstats.c.user_id == User.id)
    query = query.outerjoin(latest, and_(latest.c.user_id == User.id, latest.c.rank == 1))
    query = query.outerjoin(Lesson, Lesson.id == latest.c.lesson_id)
    query = query.outerjoin(Module, Module.id == Lesson.module_id).outerjoin(Level, Level.id == Module.level_id)
    query = query.outerjoin(module_stats, module_stats.c.user_id == User.id)
    query = query.outerjoin(module_progress, and_(module_progress.c.user_id == User.id,
                                                module_progress.c.module_id == Module.id))
    query = query.outerjoin(latest_attempts, and_(latest_attempts.c.user_id == User.id,
                                               latest_attempts.c.lesson_id == latest.c.lesson_id))
    query = query.filter(User.created_at <= now)
    if not include_admin:
        query = query.filter(User.is_admin.is_(False))
    return query, status, last_activity


def _student(row):
    data = dict(row._mapping)
    meta = data.pop('acquisition_meta') or {}
    data['source'] = meta.get('utm_source') if isinstance(meta, dict) else None
    data['status_label'] = STATUS_LABELS[data['status']]
    data['status_class'] = STATUS_CLASSES[data['status']]
    data['avg_score'] = round(data['avg_score'], 1) if data['avg_score'] is not None else None
    data['latest_lesson'] = None
    if data['lesson_id'] is not None:
        data['latest_lesson'] = {
            'lesson_id': data['lesson_id'], 'title': data['lesson_title'], 'type': data['lesson_type'],
            'number': data['lesson_number'], 'module_id': data['module_id'],
            'module_number': data['module_number'], 'module_title': data['module_title'],
            'level': data['lesson_level'], 'status': data['lesson_status'],
            'score': data['score'], 'best_score': data['best_score'], 'last_score': data['last_score'],
            'started_at': data['started_at'], 'completed_at': data['completed_at'],
            'last_activity': data['last_activity'], 'attempts': data['latest_attempts'],
            'failed_attempts': data['latest_failed_attempts'],
            'module_lessons_total': data['module_lessons_total'],
            'module_lessons_completed': data['module_lessons_completed'],
        }
    return data


def get_students(db_session, *, search='', days=None, level='', status='', lesson_id=None,
                 lesson_state='', user_ids=None, source='', last_activity_days=None,
                 page=1, per_page=25, now=None):
    """Paginated current diagnostics; `days` filters registration, not activity."""
    User, _, _, Progress, _, _, _, _, _ = _models()
    now = _now(now)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    query, status_expression, last_activity = _base_query(db_session, now)
    if search := search.strip()[:200]:
        conditions = [func.lower(User.username).contains(search.lower(), autoescape=True),
                      func.lower(User.email).contains(search.lower(), autoescape=True)]
        if search.isdigit():
            conditions.append(User.id == int(search))
        query = query.filter(or_(*conditions))
    if days is not None:
        days = max(1, min(3650, int(days)))
        query = query.filter(User.created_at >= now - timedelta(days=days))
    if level:
        query = query.filter(User.onboarding_level == level)
    if source:
        source = str(source).strip()[:200]
        source_value = User.acquisition_meta['utm_source'].as_string()
        query = query.filter(or_(source_value.is_(None), source_value == '') if source == 'unknown'
                             else source_value == source)
    if last_activity_days is not None:
        last_activity_days = max(1, min(3650, int(last_activity_days)))
        query = query.filter(last_activity >= now - timedelta(days=last_activity_days))
    if status in STATUS_LABELS:
        query = query.filter(status_expression == status)
    if lesson_id is not None:
        lesson_state = lesson_state if lesson_state in ('opened', 'submitted', 'completed', 'idle_unfinished') else 'opened'
        if lesson_state == 'submitted':
            events = _submission_rows(db_session, now)
            query = query.filter(db_session.query(events.c.user_id).filter(
                events.c.user_id == User.id, events.c.lesson_id == lesson_id).exists())
        else:
            lesson_query = db_session.query(Progress.id).filter(
                Progress.user_id == User.id, Progress.lesson_id == lesson_id,
                Progress.started_at <= now, _real_progress(Progress),
                Progress.status.in_(('in_progress', 'completed')))
            if lesson_state == 'completed':
                lesson_query = lesson_query.filter(Progress.status == 'completed', Progress.completed_at <= now)
            elif lesson_state == 'idle_unfinished':
                lesson_query = lesson_query.filter(
                    Progress.status != 'completed', _progress_activity(Progress, now) <= now - timedelta(days=1))
            query = query.filter(lesson_query.exists())
    if user_ids is not None:
        query = query.filter(User.id.in_(user_ids))
    # Counts/histogram operate on grouped per-user rows, never full history.
    filtered = query.subquery()
    total = int(db_session.query(func.count()).select_from(filtered).scalar() or 0)
    histogram = db_session.query(filtered.c.lessons_completed, func.count()).group_by(filtered.c.lessons_completed).all()
    middle_positions = ((total - 1) // 2, total // 2)
    med_values, cursor = [], 0
    for completed, count in sorted(histogram):
        med_values.extend(completed for pos in middle_positions if cursor <= pos < cursor + count)
        cursor += count
    counts = dict(db_session.query(filtered.c.status, func.count()).group_by(filtered.c.status).all())
    completed_total = sum(n * count for n, count in histogram)
    submitted = int(db_session.query(func.count()).select_from(filtered)
                    .filter(filtered.c.last_submission_at.isnot(None)).scalar() or 0)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = query.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        'students': [_student(row) for row in rows], 'total': total, 'page': page,
        'per_page': per_page, 'pages': pages,
        'summary': {'students': total, 'lessons_completed': completed_total,
                    'avg_lessons_completed': round(completed_total / total, 1) if total else None,
                    'median_lessons_completed': median(med_values) if med_values else None,
                    'submitted_students': submitted, 'no_lesson_students': counts.get('no_lesson', 0),
                    'idle_students': counts.get('idle_3d', 0), 'status_counts': counts},
        'filters': {'search': search, 'days': days, 'level': level, 'status': status, 'lesson_id': lesson_id,
                    'lesson_state': lesson_state, 'source': source, 'last_activity_days': last_activity_days},
    }


def get_student_detail(db_session, user_id, *, now=None):
    """One student's current path plus up to three graded attempts per lesson."""
    _, Level, Attempt, Progress, Lesson, _, Module, _, _ = _models()
    from app.daily_plan.models import DailyPlanLog
    now = _now(now)
    query, _, _ = _base_query(db_session, now, include_admin=True)
    row = query.filter(_models()[0].id == user_id).first()
    if row is None:
        return None
    student = _student(row)
    lesson_rows = db_session.query(Progress, Lesson, Module, Level).join(Lesson, Lesson.id == Progress.lesson_id)
    lesson_rows = lesson_rows.join(Module, Module.id == Lesson.module_id).join(Level, Level.id == Module.level_id)
    lesson_rows = lesson_rows.filter(Progress.user_id == user_id, Progress.started_at <= now)
    lesson_rows = lesson_rows.order_by(Level.order, Module.number, Lesson.number, Lesson.id).all()
    module_progress = _module_progress(db_session, now)
    module_counts = {r.module_id: (r.lessons_total, r.lessons_completed) for r in db_session.query(
        module_progress.c.module_id, module_progress.c.lessons_total, module_progress.c.lessons_completed,
    ).filter(module_progress.c.user_id == user_id).all()}
    attempt_stats = {lid: {'attempts': count, 'failed_attempts': failed} for lid, count, failed in db_session.query(
        Attempt.lesson_id, func.count(Attempt.id), func.sum(case((Attempt.passed.is_(False), 1), else_=0)),
    ).join(Lesson, Lesson.id == Attempt.lesson_id).filter(
        Attempt.user_id == user_id, Attempt.completed_at.isnot(None), Attempt.completed_at <= now,
        _graded_condition(Lesson, Attempt))
        .group_by(Attempt.lesson_id).all()}
    ranked_attempts = db_session.query(
        Attempt.lesson_id, Attempt.attempt_number.label('number'), Attempt.score, Attempt.passed,
        Attempt.completed_at, func.row_number().over(
            partition_by=Attempt.lesson_id, order_by=(Attempt.completed_at.desc(), Attempt.id.desc())).label('rank'),
    ).join(Lesson, Lesson.id == Attempt.lesson_id).filter(
        Attempt.user_id == user_id, Attempt.completed_at.isnot(None), Attempt.completed_at <= now,
        _graded_condition(Lesson, Attempt)).subquery()
    recent = {}
    for attempt in db_session.query(ranked_attempts).filter(ranked_attempts.c.rank <= 3).order_by(
        ranked_attempts.c.lesson_id, ranked_attempts.c.rank,
    ).all():
        recent.setdefault(attempt.lesson_id, []).append({
            'number': attempt.number, 'score': attempt.score, 'passed': attempt.passed,
            'completed_at': attempt.completed_at,
        })
    lessons = []
    for progress, lesson, module, level in lesson_rows:
        lessons.append({
            'lesson_id': lesson.id, 'title': lesson.title, 'type': lesson.type, 'number': lesson.number,
            'module_id': module.id, 'module_number': module.number, 'module_title': module.title,
            'level': level.code, 'status': progress.status, 'score': progress.score,
            'best_score': progress.best_score, 'last_score': progress.last_score,
            'started_at': progress.started_at, 'completed_at': progress.completed_at,
            'last_activity': next((ts for ts in (progress.last_activity, progress.completed_at, progress.started_at)
                                   if ts is not None and _now(ts) <= now), None),
            'recent_attempts': recent.get(lesson.id, []),
            'test_out': bool(progress.data.get('test_out')) if isinstance(progress.data, dict) else False,
            'saved_position': _saved_position(progress.data),
            'module_lessons_total': module_counts.get(module.id, (0, 0))[0],
            'module_lessons_completed': module_counts.get(module.id, (0, 0))[1],
            **attempt_stats.get(lesson.id, {'attempts': 0, 'failed_attempts': 0}),
        })
    plan_count, secured_count = db_session.query(
        func.count(DailyPlanLog.id), func.sum(case((DailyPlanLog.secured_at.isnot(None), 1), else_=0)),
    ).filter(DailyPlanLog.user_id == user_id, DailyPlanLog.created_at <= now).one()
    plans = db_session.query(DailyPlanLog.plan_date, DailyPlanLog.secured_at).filter(
        DailyPlanLog.user_id == user_id, DailyPlanLog.created_at <= now,
    ).order_by(DailyPlanLog.plan_date.desc()).limit(14).all()
    return {
        'student': student, 'lessons': lessons, 'plan_days': plan_count,
        'secured_days': int(secured_count or 0),
        'recent_plans': [{'plan_date': p.plan_date, 'secured_at': p.secured_at} for p in plans],
        'notes': [
            'Состояние описывает последние записанные действия curriculum; это не диагноз причины ухода.',
            'Попытки и оценки относятся к серверной проверке. Чтение и карточки могут завершаться без оценки.',
            'Активное время по старым started_at не восстанавливается достоверно.',
            'Учебные дни — дни отправок curriculum в UTC, без SRS и отдельного чтения книг.',
        ],
    }


def get_lesson_diagnostics(db_session, *, days=30, limit=50, now=None):
    """Lesson bottlenecks among users registered in the selected cohort window."""
    User, Level, Attempt, Progress, Lesson, _, Module, _, _ = _models()
    now = _now(now)
    cutoff = now - timedelta(days=max(1, min(3650, int(days))))
    cohort = db_session.query(User.id).filter(User.is_admin.is_(False), User.created_at >= cutoff,
                                             User.created_at <= now)
    progress = db_session.query(
        Progress.lesson_id,
        func.count(func.distinct(Progress.user_id)).label('opened'),
        func.count(func.distinct(case((and_(Progress.status == 'completed', Progress.completed_at <= now),
                                       Progress.user_id)))).label('completed'),
        func.count(func.distinct(case((and_(Progress.status != 'completed',
                                             _progress_activity(Progress, now) <= now - timedelta(days=1)),
                                       Progress.user_id)))).label('idle_unfinished'),
        func.count(func.distinct(case((_progress_activity(Progress, now) <= now - timedelta(days=1),
                                       Progress.user_id)))).label('idle_eligible'),
    ).filter(Progress.user_id.in_(cohort), Progress.started_at <= now,
             _real_progress(Progress),
             Progress.status.in_(('in_progress', 'completed'))).group_by(Progress.lesson_id).subquery()
    attempts = db_session.query(
        Attempt.lesson_id, func.count(Attempt.id).label('attempts'),
        func.avg(Attempt.score).label('avg_score'),
        func.sum(case((Attempt.passed.is_(False), 1), else_=0)).label('failed_attempts'),
    ).join(Lesson, Lesson.id == Attempt.lesson_id).filter(
        Attempt.user_id.in_(cohort), Attempt.completed_at.isnot(None), Attempt.completed_at <= now,
        _graded_condition(Lesson, Attempt))
    attempts = attempts.group_by(Attempt.lesson_id).subquery()
    events = _submission_rows(db_session, now)
    submitted = db_session.query(events.c.lesson_id, func.count(func.distinct(events.c.user_id)).label('submitted'))
    submitted = submitted.filter(events.c.user_id.in_(cohort), events.c.lesson_id.isnot(None))
    submitted = submitted.group_by(events.c.lesson_id).subquery()
    rows = db_session.query(
        Lesson.id.label('lesson_id'), Lesson.title, Lesson.type, Lesson.number,
        Module.number.label('module_number'), Module.title.label('module_title'), Level.code.label('level'),
        progress.c.opened, progress.c.completed, progress.c.idle_unfinished, progress.c.idle_eligible,
        func.coalesce(submitted.c.submitted, 0).label('submitted'),
        func.coalesce(attempts.c.attempts, 0).label('attempts'),
        func.coalesce(attempts.c.failed_attempts, 0).label('failed_attempts'), attempts.c.avg_score,
    ).select_from(Lesson).join(progress, progress.c.lesson_id == Lesson.id).join(Module, Module.id == Lesson.module_id)
    rows = rows.join(Level, Level.id == Module.level_id).outerjoin(attempts, attempts.c.lesson_id == Lesson.id)
    rows = rows.outerjoin(submitted, submitted.c.lesson_id == Lesson.id)
    rows = rows.order_by(progress.c.idle_unfinished.desc(), progress.c.opened.desc(), Lesson.id)
    return [{**dict(row._mapping),
             'completion_percent': round(row.completed / row.opened * 100, 1) if row.opened else None,
             'avg_score': round(row.avg_score, 1) if row.avg_score is not None else None,
             'registration_days': days}
            for row in rows.limit(max(1, min(100, int(limit)))).all()]
