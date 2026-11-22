"""One cleaned learner population for the weekly learning goal and its drilldowns.

Reads evidence of work, never login/page-view timestamps. Historical progress
is mutable, so the report describes recorded evidence rather than attendance.
"""

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import inspect, or_

from app.admin.services.retention_report_service import GRADED_LESSON_TYPES

EXCLUSIONS_KEY = 'growth_account_overrides'
EXCLUSION_REASONS = {'self': 'Мой аккаунт', 'family': 'Семья', 'test': 'Тестовый', 'other': 'Другое'}
STATE_LABELS = {
    'new': 'Ещё не начал', 'opened': 'Открыл, не выполнил', 'errors': 'Повторные ошибки',
    'stopped': 'Остановился в уроке', 'active': 'Занимается', 'away': 'Нет занятий 7 дней',
}
CATEGORY_LABELS = {'course': 'Курс', 'words': 'Слова', 'grammar': 'Грамматика', 'reading': 'Чтение'}  # noqa: RUF001
# Only known automation namespaces. Ordinary names containing "test" are not a rule.
_AUDIT_NAME = re.compile(r'^(?:ios_audit_\d{8}_[a-z0-9]+|audit_android_\d+)$', re.I)


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def load_overrides(session):
    from app.admin.site_settings import get_site_setting

    raw = get_site_setting(EXCLUSIONS_KEY, '{}', db_session=session)
    values = json.loads(raw)
    if not isinstance(values, dict) or any(
        not str(key).isdigit() or not isinstance(value, dict)
        or type(value.get('excluded')) is not bool
        or (value['excluded'] and value.get('reason') not in EXCLUSION_REASONS)
        for key, value in values.items()
    ):
        raise ValueError('Invalid growth account exclusions')
    return values


def exclusion_reason(user, overrides):
    if user.get('is_admin'):
        return 'Администратор'
    override = overrides.get(str(user['id']))
    if override is not None:
        return EXCLUSION_REASONS[override['reason']] if override['excluded'] else ''
    if _AUDIT_NAME.fullmatch(user.get('username') or ''):
        return 'Автопроверка приложения'
    return ''


def acquisition(meta):
    """Show captured first-touch evidence, without inventing a direct/organic source."""
    meta = meta if isinstance(meta, dict) else {}
    source = str(meta.get('utm_source') or '').strip()[:100]
    medium = str(meta.get('utm_medium') or '').strip()[:100]
    campaign = str(meta.get('utm_campaign') or '').strip()[:150]
    try:
        referrer = (urlsplit(str(meta.get('referrer') or '')).hostname or '').lower()
    except ValueError:
        referrer = ''
    if referrer == 'llt-english.com' or referrer.endswith('.llt-english.com'):
        referrer = ''
    label = source or referrer or 'Источник не сохранён'
    path = str(meta.get('landing_path') or '').split('?', 1)[0][:200]
    if not path.startswith('/') or path.startswith('//'):
        path = ''
    return {'label': label, 'medium': medium, 'campaign': campaign, 'landing': path,
            'evidence': 'UTM' if source else 'Referrer' if referrer else 'Нет данных'}


def read_snapshot(session, overrides, now):
    """Bounded query count; excluded users are filtered before fetching their work."""
    from app.auth.models import User
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

    users = [dict(row._mapping) for row in session.query(
        User.id, User.username, User.email, User.created_at, User.is_admin, User.active,
        User.onboarding_level, User.acquisition_meta,
    ).filter(User.created_at <= now.replace(tzinfo=None)).all()]
    ids = [u['id'] for u in users if not exclusion_reason(u, overrides)]
    progress = []
    if ids:
        query = session.query(
            LessonProgress.user_id, LessonProgress.lesson_id, LessonProgress.status,
            LessonProgress.started_at, LessonProgress.completed_at, LessonProgress.last_activity,
            LessonProgress.data['test_out'].as_boolean().label('is_test_out'),
            Lessons.title, Lessons.type, Lessons.number,
            Module.number.label('module_number'), CEFRLevel.code.label('level'),
        ).join(Lessons, Lessons.id == LessonProgress.lesson_id)
        query = query.outerjoin(Module, Module.id == Lessons.module_id)
        query = query.outerjoin(CEFRLevel, CEFRLevel.id == Module.level_id)
        progress = [dict(row._mapping) for row in query.filter(LessonProgress.user_id.in_(ids))]
    missing = []
    return users, progress, _read_events(session, ids, missing, now), missing


def _read_events(session, ids, missing, now):
    """Stream narrow evidence rows; never load answers or count empty sessions."""
    if not ids:
        return
    from app.books.reading_session import UserReadingSession
    from app.curriculum.daily_lessons import UserLessonProgress
    from app.curriculum.models import LessonAttempt, Lessons, ListeningAttempt, PronunciationAttempt, UserWritingAttempt
    from app.grammar_lab.models import GrammarAttempt
    from app.study.models import CardGradeEvent, GameScore, QuizResult, StudySession, WordSetQuizResult

    tables = set(inspect(session.connection()).get_table_names())
    specs = [
        (LessonAttempt, LessonAttempt.completed_at, 'course', 'Упражнение курса', [
            LessonAttempt.score.isnot(None), Lessons.type.in_(GRADED_LESSON_TYPES),
            or_(Lessons.type.notin_(('grammar', 'listening_immersion')), LessonAttempt.total_questions > 0),
        ]),
        (ListeningAttempt, ListeningAttempt.created_at, 'course', 'Аудирование', []),
        (UserWritingAttempt, UserWritingAttempt.created_at, 'course', 'Письменное задание', [UserWritingAttempt.word_count > 0]),
        (PronunciationAttempt, PronunciationAttempt.created_at, 'course', 'Произношение', []),
        (CardGradeEvent, CardGradeEvent.graded_at, 'words', 'Ответ по карточке', []),
        (StudySession, StudySession.end_time, 'words', 'Словарная тренировка', [
            or_(StudySession.words_studied > 0, StudySession.correct_answers + StudySession.incorrect_answers > 0),
        ]),
        (QuizResult, QuizResult.completed_at, 'words', 'Тест по словам', [QuizResult.total_questions > 0]),
        (WordSetQuizResult, WordSetQuizResult.completed_at, 'words', 'Тематический тест', [WordSetQuizResult.total_questions > 0]),
        (GameScore, GameScore.date_achieved, 'words', 'Игра со словами', [or_(GameScore.pairs_matched > 0, GameScore.total_questions > 0)]),  # noqa: RUF001
        (GrammarAttempt, GrammarAttempt.created_at, 'grammar', 'Упражнение Grammar Lab', []),
        (UserLessonProgress, UserLessonProgress.completed_at, 'course', 'Урок книжного курса', [UserLessonProgress.status == 'completed']),
        (UserReadingSession, UserReadingSession.ended_at, 'reading', 'Чтение книги', [UserReadingSession.offset_delta > 0]),
    ]
    for model, timestamp, kind, title, conditions in specs:
        if model.__tablename__ not in tables:
            missing.append(model.__tablename__)
            continue
        columns = [model.user_id, timestamp.label('at')]
        if model is LessonAttempt:
            columns += [model.lesson_id, model.passed]
        if model is UserReadingSession:
            columns += [model.started_at]
        if model is StudySession:
            columns += [model.session_type]
        query = session.query(*columns)
        if model is LessonAttempt:
            query = query.join(Lessons, Lessons.id == model.lesson_id)
        query = query.filter(model.user_id.in_(ids), timestamp <= now, *conditions)
        for row in query.yield_per(2000):
            item = dict(row._mapping)
            if model is UserReadingSession and (
                item['started_at'] is None or (utc(item['at']) - utc(item['started_at'])).total_seconds() < 60
            ):
                continue
            event_kind = 'grammar' if model is StudySession and item['session_type'] == 'grammar' else kind
            yield {**item, 'kind': event_kind, 'title': title, 'graded': model is LessonAttempt}


def build_report(users, progress, events, *, now, overrides=None, missing=None):
    """One population and UTC timeline for goal, sources, cohorts and learner rows."""
    now, overrides = utc(now), overrides or {}
    week, previous, month = now - timedelta(days=7), now - timedelta(days=14), now - timedelta(days=30)
    excluded, learners = [], {}
    for user in users:
        if not user.get('created_at') or utc(user['created_at']) > now:
            continue
        reason = exclusion_reason(user, overrides)
        account = {**user, 'created_at': utc(user['created_at']), 'excluded_reason': reason}
        if reason:
            excluded.append(account)
            continue
        learners[user['id']] = {
            **account, 'source': acquisition(user.get('acquisition_meta')), 'days': set(),
            'first': None, 'last': None, 'last_title': '', 'last_kind': '',
            'kinds': set(), 'learned24': False, 'returned7': False, 'week2': False,
            'first_week_days': set(),
            'days28_dates': set(),
            'completed': 0, 'opened': 0, 'latest_lesson': None,
        }
    progresses = defaultdict(list)
    completions = []
    for p in progress:
        learner = learners.get(p['user_id'])
        start, end = utc(p.get('started_at')), utc(p.get('completed_at'))
        if learner is None or p.get('is_test_out') or start is None or not learner['created_at'] <= start <= now:
            continue
        if p.get('status') not in ('in_progress', 'completed'):
            continue
        item = {**p, 'started_at': start, 'completed_at': end,
                'last_activity': utc(p.get('last_activity'))}
        activity = item['last_activity']
        item['observed_at'] = activity if activity and start <= activity <= now else end if end and start <= end <= now else start
        progresses[p['user_id']].append(item)
        learner['opened'] += 1
        if p.get('status') == 'completed' and end and start <= end <= now:
            learner['completed'] += 1
            completions.append({'user_id': p['user_id'], 'at': end, 'kind': 'course',
                                'title': p.get('title') or 'Завершённый урок'})

    attempts = defaultdict(list)
    trend_members = [set() for _ in range(8)]

    def record(event):
        learner = learners.get(event['user_id'])
        at = utc(event.get('at'))
        if learner is None or at is None or not learner['created_at'] <= at <= now:
            return
        learner['days'].add(at.date())
        if at >= now - timedelta(days=28):
            learner['days28_dates'].add(at.date())
        for offset in range(8):
            start, end = now - timedelta(days=7 * (offset + 1)), now - timedelta(days=7 * offset)
            if start <= at and (at < end or (offset == 0 and at == end)):
                trend_members[offset].add(learner['id'])
        learner['kinds'].add(event['kind'])
        if learner['first'] is None or at < learner['first']:
            learner['first'] = at
        if learner['last'] is None or at > learner['last']:
            learner.update(last=at, last_title=event.get('title', ''), last_kind=event['kind'])
        age = at - learner['created_at']
        if age < timedelta(days=1):
            learner['learned24'] = True
        registration_day = learner['created_at'].date()
        day = (at.date() - registration_day).days
        if 0 <= day <= 6:
            learner['first_week_days'].add(at.date())
        if 7 <= day <= 13:
            learner['week2'] = True
        if event.get('graded') and event.get('lesson_id') is not None:
            attempts[(learner['id'], event['lesson_id'])].append((at, event.get('passed')))
        if at >= week:
            learner.setdefault('recent_times', set()).add(at)
        elif at >= previous:
            learner['previous_week'] = True

    for event in events:
        record(event)
    for event in completions:
        record(event)

    bottlenecks = {}
    for learner in learners.values():
        learner['returned7'] = len(learner.pop('first_week_days')) >= 2
        learner['days7'] = len({at.date() for at in learner.pop('recent_times', ())})
        learner['days28'] = len(learner.pop('days28_dates'))
        learner['active7'] = learner['days7'] > 0
        learner['previous_week'] = learner.get('previous_week', False)
        learner['new30'] = learner['created_at'] >= month
        learner['state'] = 'new' if learner['first'] is None else 'active' if learner['active7'] else 'away'
        paths = progresses[learner['id']]
        if paths:
            latest = max(paths, key=lambda p: (p['observed_at'], p['lesson_id']))
            learner['latest_lesson'] = latest
            if learner['first'] is None:
                learner['state'] = 'opened'
            pending = latest['status'] != 'completed'
            grades = sorted(attempts[(learner['id'], latest['lesson_id'])], key=lambda grade: grade[0])
            last_pass = max((at for at, passed in grades if passed is True), default=datetime.min.replace(tzinfo=UTC))
            failures = sum(passed is False and at > last_pass for at, passed in grades)
            idle = latest['observed_at'] <= now - timedelta(days=1)
            later_work = learner['last'] and learner['last'] > latest['observed_at']
            if pending and failures >= 2:
                learner['state'] = 'errors'
            elif pending and idle and not later_work:
                learner['state'] = 'stopped'
            if learner['new30'] and pending and idle and not later_work:
                item = bottlenecks.setdefault(latest['lesson_id'], {
                    'id': latest['lesson_id'], 'title': latest.get('title'),
                    'level': latest.get('level'), 'count': 0, 'user_ids': [],
                })
                item['count'] += 1
                item['user_ids'].append(learner['id'])
        learner['state_label'] = STATE_LABELS[learner['state']]
        learner['kinds_label'] = ' · '.join(CATEGORY_LABELS[kind] for kind in CATEGORY_LABELS if kind in learner['kinds'])

    rows = sorted(learners.values(), key=lambda row: (row['created_at'], row['id']), reverse=True)
    current = {u['id'] for u in rows if u['active7']}
    old = {u['id'] for u in rows if u['previous_week']}
    new = {u['id'] for u in rows if u['first'] and week <= u['first'] <= now}
    sources = {}
    for row in rows:
        label = row['source']['label']
        source = sources.setdefault(label, {'label': label, 'total': 0, 'new30': 0, 'active7': 0, 'repeat7': 0})
        source['total'] += 1
        source['new30'] += row['new30']
        source['active7'] += row['active7']
        source['repeat7'] += row['days7'] >= 2
    recent = [u for u in rows if u['new30']]

    def metric(eligible, condition):
        count = sum(condition(u) for u in eligible)
        return {'count': count, 'eligible': len(eligible),
                'percent': round(100 * count / len(eligible), 1) if eligible else None}

    metrics = {
        'first24': metric([u for u in recent if u['created_at'] <= now - timedelta(days=1)], lambda u: u['learned24']),
        'return7': metric([u for u in recent if u['created_at'].date() <= now.date() - timedelta(days=7)], lambda u: u['returned7']),
        'week2': metric([u for u in recent if u['created_at'].date() <= now.date() - timedelta(days=14)], lambda u: u['week2']),
    }
    trend = []
    for offset in reversed(range(8)):
        end = now - timedelta(weeks=offset)
        trend.append({'label': end.strftime('%d.%m'), 'count': len(trend_members[offset])})
    accounts = sorted([*excluded, *rows], key=lambda u: (u['created_at'], u['id']), reverse=True)
    return {
        'now': now, 'learners': rows, 'accounts': accounts, 'excluded': excluded,
        'total': len(rows), 'active7': len(current), 'previous7': len(old), 'delta': len(current) - len(old),
        'new_active': len(current & new), 'retained': len(current & old),
        'returned': len(current - old - new), 'lost': len(old - current),
        'repeat7': sum(u['days7'] >= 2 for u in rows), 'remaining': max(0, 100 - len(current)),
        'progress_percent': min(100, len(current)), 'new30': len(recent), 'metrics': metrics,
        'sources': sorted(sources.values(), key=lambda s: (-s['active7'], -s['new30'], s['label'])),
        'bottlenecks': sorted(bottlenecks.values(), key=lambda b: (-b['count'], b['id']))[:6],
        'trend': trend, 'missing': list(missing or ()),
    }


def get_report(session, *, now=None):
    now = utc(now or datetime.now(UTC))
    overrides = load_overrides(session)
    users, progress, events, missing = read_snapshot(session, overrides, now)
    report = build_report(users, progress, events, now=now, overrides=overrides, missing=missing)
    # The streaming reader discovers unavailable sources while build_report consumes it.
    report['missing'] = missing
    return report
