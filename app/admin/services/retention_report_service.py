#!/usr/bin/env python3
"""Read-only curriculum activation/retention report; usable without the Flask app.

DATABASE_URL must be supplied explicitly in the environment. Output contains
aggregates only. Missing evidence is reported, never replaced by page views.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo


# Explicit server-graded types. A counter of zero is not proof of no submission:
# older graders returned total_items, whereas persistence read total_questions.
GRADED_LESSON_TYPES = frozenset((
    'dictation', 'audio_fill_blank', 'translation', 'sentence_correction',
    'sentence_completion', 'collocation_matching', 'quiz', 'ordering_quiz',
    'translation_quiz', 'listening_quiz', 'dialogue_completion_quiz',
    'grammar', 'matching', 'final_test',
))


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def rate(count, eligible):
    return {'count': count, 'eligible': eligible,
            'percent': round(100 * count / eligible, 1) if eligible else None}


def summarize(users, progress, events, *, as_of, timezone_name='UTC'):
    """Use complete observation windows, immutable submissions, exact local days.

    `events` are actual submissions, including failed ones, not page visits.
    `progress` is a mutable historical proxy; its limitations remain explicit.
    """
    as_of = utc(as_of)
    zone = ZoneInfo(timezone_name)
    users = {u['id']: u for u in users if utc(u['created_at']) < as_of}
    history = defaultdict(list)
    opens = defaultdict(list)
    completed = defaultdict(list)
    for row in events:
        uid = row['user_id']
        ts = utc(row['at'])
        if uid in users and utc(users[uid]['created_at']) <= ts < as_of:
            history[uid].append(ts)
    for row in progress:
        uid = row['user_id']
        if uid not in users:
            continue
        reg = utc(users[uid]['created_at'])
        if (row.get('started_at') and not row.get('is_test_out')
                and reg <= utc(row['started_at']) < as_of):
            opens[uid].append(row)
        if row.get('completed_at') and reg <= utc(row['completed_at']) < as_of:
            completed[uid].append(row)

    mature = {uid for uid, u in users.items()
              if utc(u['created_at']) + timedelta(days=1) <= as_of}
    opened24, completed24, second24, submitted24 = set(), set(), set(), set()
    latencies = []
    for uid in mature:
        end = utc(users[uid]['created_at']) + timedelta(days=1)
        if any(utc(p['started_at']) < end for p in opens[uid]):
            opened24.add(uid)
        ids = {p['lesson_id'] for p in completed[uid] if utc(p['completed_at']) < end}
        if ids:
            completed24.add(uid)
        if len(ids) >= 2:
            second24.add(uid)
        ts = [t for t in history[uid] if t < end]
        if ts:
            submitted24.add(uid)
            latencies.append((min(ts) - utc(users[uid]['created_at'])).total_seconds())

    retention = {}
    for day in (1, 7, 30):
        eligible, retained = 0, 0
        for uid, u in users.items():
            target = utc(u['created_at']).astimezone(zone).date() + timedelta(days=day)
            end = datetime.combine(target + timedelta(days=1), time.min, zone).astimezone(UTC)
            if end > as_of:
                continue
            eligible += 1
            retained += any(t.astimezone(zone).date() == target for t in history[uid])
        retention[f'D{day}'] = rate(retained, eligible)

    unfinished = defaultdict(lambda: {'opened_idle_24h': 0, 'unfinished_idle_24h': 0})
    for rows in opens.values():
        for row in rows:
            last = row.get('last_activity') or row['started_at']
            # Exclude still-active observations and future/malformed timestamps.
            if utc(last) > as_of - timedelta(days=1):
                continue
            item = unfinished[row['type']]
            item['opened_idle_24h'] += 1
            if not row.get('completed_at') or utc(row['completed_at']) >= as_of:
                item['unfinished_idle_24h'] += 1

    latencies.sort()
    median = None
    if latencies:
        middle = len(latencies) // 2
        median = (latencies[middle] if len(latencies) % 2 else
                  (latencies[middle - 1] + latencies[middle]) / 2)
    return {
        'registered': len(users),
        'onboarding_completed_current_state': sum(bool(u['onboarding_completed']) for u in users.values()),
        'first_24h': {
            'eligible': len(mature),
            'lesson_opened': rate(len(opened24), len(mature)),
            'submission_recorded': rate(len(submitted24), len(mature)),
            'one_lesson_completed': rate(len(completed24), len(mature)),
            'two_lessons_completed': rate(len(second24), len(mature)),
            'median_seconds_to_first_submission_among_submitters': median,
        },
        'curriculum_submission_retention': retention,
        'idle_progress_by_type': dict(sorted(unfinished.items())),
    }


def ordered_funnel(users, progress, events, *, as_of, include_members=False):
    """A timed, same-lesson path in fully observed first-24h cohorts.

    Passive completion and test-out do not prove a graded-submission path.
    Onboarding is deliberately separate: there is no historical timestamp.
    """
    as_of = utc(as_of)
    cohort = {u['id']: u for u in users
              if utc(u['created_at']) + timedelta(days=1) <= as_of}
    rows, submissions = defaultdict(list), defaultdict(list)
    for p in progress:
        if p['user_id'] in cohort and not p.get('is_test_out'):
            rows[p['user_id']].append(p)
    for event in events:
        if event['user_id'] in cohort and event.get('lesson_id') is not None:
            submissions[event['user_id']].append(event)
    reached = {key: set() for key in ('registered', 'opened', 'submitted', 'completed',
                                     'next_opened', 'second_completed')}
    reached['registered'] = set(cohort)
    for uid, user in cohort.items():
        start = utc(user['created_at'])
        end = start + timedelta(days=1)
        valid = [p for p in rows[uid] if p.get('started_at') and start <= utc(p['started_at']) < end]
        if not valid:
            continue
        reached['opened'].add(uid)
        chains = []
        for p in valid:
            matches = [utc(e['at']) for e in submissions[uid]
                       if e['lesson_id'] == p['lesson_id'] and utc(p['started_at']) <= utc(e['at']) < end]
            if not matches:
                continue
            reached['submitted'].add(uid)
            # Progress is committed before its attempt row in the same handler;
            # tolerate only a small same-request persistence ordering difference.
            if (p.get('completed_at') and utc(p['started_at']) <= utc(p['completed_at']) < end
                    and min(matches) <= utc(p['completed_at']) + timedelta(seconds=5)):
                chains.append((max(utc(p['completed_at']), min(matches)), p['lesson_id']))
        if not chains:
            continue
        reached['completed'].add(uid)
        first_at, first_id = min(chains)
        next_rows = [p for p in valid if p['lesson_id'] != first_id and utc(p['started_at']) >= first_at]
        if not next_rows:
            continue
        reached['next_opened'].add(uid)
        if any(p.get('completed_at') and utc(p['started_at']) <= utc(p['completed_at']) < end
               for p in next_rows):
            reached['second_completed'].add(uid)
    labels = {
        'registered': 'Регистрации: полное окно 24 часа',
        'opened': 'Открыли урок', 'submitted': 'Отправили работу после открытия',
        'completed': 'Завершили этот урок после отправки',
        'next_opened': 'Открыли другой урок после завершения',
        'second_completed': 'Завершили следующий урок',
    }
    steps, previous = [], None
    for key, members in reached.items():
        prev_members = reached[previous] if previous else None
        count = len(members)
        row = {'key': key, 'label': labels[key], **rate(count, len(cohort)),
               'conversion_from_prev': rate(count, len(prev_members))['percent'] if previous else None,
               'lost_from_prev': len(prev_members - members) if previous else None}
        if include_members:
            row['user_ids'] = sorted(members)
            row['lost_user_ids'] = sorted(prev_members - members) if previous else []
        steps.append(row)
        previous = key
    return {'window_hours': 24, 'steps': steps}


def progress_funnel(users, progress, *, as_of, include_members=False):
    """Observable lesson navigation for all lesson types in first 24 hours.

    Vocabulary/cards can complete without a graded submission. Test-out rows
    are synthetic progression, so they never prove a lesson opening here.
    """
    as_of = utc(as_of)
    cohort = {u['id']: u for u in users
              if utc(u['created_at']) + timedelta(days=1) <= as_of}
    rows = defaultdict(list)
    for item in progress:
        if item['user_id'] in cohort and not item.get('is_test_out'):
            rows[item['user_id']].append(item)
    reached = {key: set() for key in ('path_registered', 'path_opened', 'path_completed',
                                     'path_next_opened', 'path_second_completed')}
    reached['path_registered'] = set(cohort)
    for uid, user in cohort.items():
        start, end = utc(user['created_at']), utc(user['created_at']) + timedelta(days=1)
        valid = [p for p in rows[uid] if p.get('started_at') and start <= utc(p['started_at']) < end]
        if not valid:
            continue
        reached['path_opened'].add(uid)
        completed = [(utc(p['completed_at']), p['lesson_id']) for p in valid
                     if p.get('completed_at') and utc(p['started_at']) <= utc(p['completed_at']) < end]
        if not completed:
            continue
        reached['path_completed'].add(uid)
        first_at, first_id = min(completed)
        next_rows = [p for p in valid if p['lesson_id'] != first_id and utc(p['started_at']) >= first_at]
        if not next_rows:
            continue
        reached['path_next_opened'].add(uid)
        if any(p.get('completed_at') and utc(p['started_at']) <= utc(p['completed_at']) < end
               for p in next_rows):
            reached['path_second_completed'].add(uid)
    labels = {
        'path_registered': 'Регистрации: полное окно 24 часа',
        'path_opened': 'Открыли хотя бы один урок',
        'path_completed': 'Завершили открытый урок',
        'path_next_opened': 'Открыли другой урок после завершения',
        'path_second_completed': 'Завершили следующий урок',
    }
    steps, previous = [], None
    for key, members in reached.items():
        prev_members = reached[previous] if previous else None
        count = len(members)
        item = {'key': key, 'label': labels[key], **rate(count, len(cohort)),
                'conversion_from_prev': rate(count, len(prev_members))['percent'] if previous else None,
                'lost_from_prev': len(prev_members - members) if previous else None}
        if include_members:
            item['user_ids'] = sorted(members)
            item['lost_user_ids'] = sorted(prev_members - members) if previous else []
        steps.append(item)
        previous = key
    return {'window_hours': 24, 'steps': steps}


def lesson_summary(users, progress, events, *, as_of):
    """Unique learners per lesson; idle unfinished observations are not proven exits."""
    as_of = utc(as_of)
    cohort = {u['id']: utc(u['created_at']) for u in users if utc(u['created_at']) < as_of}
    lessons = {}
    for p in progress:
        uid = p['user_id']
        if uid not in cohort or not p.get('started_at') or not cohort[uid] <= utc(p['started_at']) < as_of:
            continue
        lid = p['lesson_id']
        item = lessons.setdefault(lid, {
            'lesson_id': lid, 'title': p.get('title') or f'Урок #{lid}', 'type': p.get('type', ''),
            'module_title': p.get('module_title'), 'level': p.get('level'),
            'opened': set(), 'completed': set(), 'submitted': set(),
            'idle_observed': set(), 'idle_unfinished': set(),
        })
        item['opened'].add(uid)
        complete = bool(p.get('completed_at') and cohort[uid] <= utc(p['completed_at']) < as_of)
        if complete:
            item['completed'].add(uid)
        last = p.get('last_activity') or p['started_at']
        if utc(last) <= as_of - timedelta(days=1):
            item['idle_observed'].add(uid)
            if not complete:
                item['idle_unfinished'].add(uid)
    for event in events:
        uid, lid = event['user_id'], event.get('lesson_id')
        if lid in lessons and uid in cohort and cohort[uid] <= utc(event['at']) < as_of:
            lessons[lid]['submitted'].add(uid)
    result = []
    for item in lessons.values():
        for key in ('opened', 'submitted', 'completed', 'idle_observed', 'idle_unfinished'):
            item[key] = len(item[key])
        item['completion_percent'] = rate(item['completed'], item['opened'])['percent']
        item['idle_unfinished_percent'] = rate(item['idle_unfinished'], item['idle_observed'])['percent']
        result.append(item)
    return sorted(result, key=lambda r: (-r['idle_unfinished'], -r['opened'], r['lesson_id']))


def _rows_by_user(rows):
    result = defaultdict(list)
    for row in rows:
        result[row['user_id']].append(row)
    return result


def _rows_for_users(users, rows_by_user):
    return [row for user in users for row in rows_by_user.get(user['id'], ())]


def weekly_cohorts(users, events, *, as_of, timezone_name='UTC'):
    """Per-user mature denominators without re-scanning all events per week."""
    as_of = utc(as_of)
    zone = ZoneInfo(timezone_name)
    buckets = defaultdict(list)
    events_by_user = _rows_by_user(events)
    for user in users:
        if utc(user['created_at']) >= as_of:
            continue
        date = utc(user['created_at']).astimezone(zone).date()
        monday = date - timedelta(days=date.weekday())
        buckets[monday.isoformat()].append(user)
    return [{'week_start': key, 'cohort_size': len(rows),
             'retention': summarize(rows, [], _rows_for_users(rows, events_by_user), as_of=as_of,
                                    timezone_name=timezone_name)['curriculum_submission_retention']}
            for key, rows in sorted(buckets.items())]


def retention_memberships(users, events, *, as_of, timezone_name='UTC'):
    """Server-only drilldown sets matching exact-day count and eligibility rules."""
    as_of, zone = utc(as_of), ZoneInfo(timezone_name)
    cohort = {u['id']: utc(u['created_at']) for u in users if utc(u['created_at']) < as_of}
    active_dates = defaultdict(set)
    for event in events:
        uid, at = event['user_id'], utc(event['at'])
        if uid in cohort and cohort[uid] <= at < as_of:
            active_dates[uid].add(at.astimezone(zone).date())
    result = {}
    for day in (1, 7, 30):
        eligible, retained = [], []
        for uid, registration in cohort.items():
            target = registration.astimezone(zone).date() + timedelta(days=day)
            end = datetime.combine(target + timedelta(days=1), time.min, zone).astimezone(UTC)
            if end > as_of:
                continue
            eligible.append(uid)
            if target in active_dates[uid]:
                retained.append(uid)
        result[f'eligible_D{day}'] = sorted(eligible)
        result[f'retained_D{day}'] = sorted(retained)
    return result


def build_report(users, progress, events, *, as_of, days, timezone_name, missing_sources=(),
                 include_members=False):
    as_of = utc(as_of)
    users = [user for user in users if utc(user['created_at']) < as_of]
    args = {'as_of': as_of, 'timezone_name': timezone_name}
    progress_by_user, events_by_user = _rows_by_user(progress), _rows_by_user(events)
    segments = {}
    for dimension in ('level', 'source'):
        buckets = defaultdict(list)
        for user in users:
            buckets[user.get(dimension) or 'unknown'].append(user)
        segments[dimension] = {
            key: summarize(rows, _rows_for_users(rows, progress_by_user),
                           _rows_for_users(rows, events_by_user), **args)
            for key, rows in sorted(buckets.items())
        }
    report = {
        'as_of_utc': utc(as_of).isoformat(), 'registration_window_days': days,
        'timezone': timezone_name,
        'missing_sources': list(missing_sources),
        'definitions': {
            'activation_window': 'First 24 hours after registration; only fully observed users.',
            'retention': 'Submission on exact calendar day N after registration in report timezone; '
                         'only users whose entire target day has elapsed. Not rolling retention.',
            'submission': 'Completed server-graded lesson attempt, listening, '
                          'nonempty writing, or pronunciation attempt. Includes failed submissions.',
            'completion': 'Historical LessonProgress proxy; can include passive lessons and test-out.',
            'idle': 'Opened progress with no recorded activity for at least 24h; not proven abandonment.',
        },
        'limitations': [
            'No visitor denominator, guest activity, first-answer events or content version in these tables.',
            'No reliable historical device split; device_info is not consistently populated.',
            'Curriculum submissions only: reading, SRS and other learning activity are not retention here.',
            'Onboarding flag has no timestamp; not a timed or strictly ordered funnel step.',
            'Source and level are registration/current-profile metadata, not event-time dimensions.',
            'LessonProgress is mutable; historical completion may have changed on retry or import.',
            'First submission latency is not active time or time to first answer.',
            'Legacy zero-question attempts count for explicit server-graded lesson types except '
            'grammar: grammar requires a positive question count to exclude theory-only records.',
            'The graded path requires a same-lesson submission before completion; the main lesson '
            'path includes passive completion. Synthetic test-out progress is excluded from both paths.',
        ] + [f'Missing source: {source}; counts may be incomplete.' for source in missing_sources],
        'overall': summarize(users, progress, events, **args), 'segments': segments,
        'ordered_funnel': ordered_funnel(users, progress, events, as_of=as_of, include_members=include_members),
        'progress_funnel': progress_funnel(users, progress, as_of=as_of, include_members=include_members),
        'lesson_summary': lesson_summary(users, progress, events, as_of=as_of),
        'weekly_cohorts': weekly_cohorts(users, events, **args),
    }
    if include_members:
        report['memberships'] = {}
        for name in ('ordered_funnel', 'progress_funnel'):
            steps = report[name]['steps']
            report['memberships'].update({step['key']: step['user_ids'] for step in steps})
            for previous, current in pairwise(steps):
                key = f"{previous['key']}_without_{current['key']}"
                report['memberships'][key] = current['lost_user_ids']
        report['memberships'].update(retention_memberships(users, events, **args))
    return report


def read_snapshot(connection, *, cutoff, as_of):
    """Select only needed metadata; no email, answers, IP, or user-agent is read."""
    from sqlalchemy import inspect, text

    tables = set(inspect(connection).get_table_names())
    required = {'users', 'lesson_progress', 'lessons', 'lesson_attempts'}
    if not required <= tables:
        raise ValueError('Required curriculum tables are missing')
    params = {'cutoff': utc(cutoff).replace(tzinfo=None), 'as_of': utc(as_of).replace(tzinfo=None)}
    cohort = 'u.created_at >= :cutoff AND u.created_at < :as_of AND u.is_admin = false'
    users = [dict(r) for r in connection.execute(text(
        'SELECT u.id, u.created_at, u.onboarding_completed, u.onboarding_level AS level, '
        f'u.acquisition_meta FROM users u WHERE {cohort}'), params).mappings()]
    for user in users:
        meta = user.pop('acquisition_meta') or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        user['source'] = str(meta.get('utm_source') or 'unknown')[:100] if isinstance(meta, dict) else 'unknown'
    lesson_columns = {c['name'] for c in inspect(connection).get_columns('lessons')}
    title = 'l.title' if 'title' in lesson_columns else 'NULL'
    progress_columns = {c['name'] for c in inspect(connection).get_columns('lesson_progress')}
    test_out = ("CASE WHEN CAST(p.data ->> 'test_out' AS TEXT) IN ('true', '1') THEN true ELSE false END"
                if 'data' in progress_columns else 'false')
    module_join, module_fields = '', 'NULL AS module_title, NULL AS level'
    if {'modules', 'cefr_levels'} <= tables and 'module_id' in lesson_columns:
        module_join = (' LEFT JOIN modules m ON m.id=l.module_id '
                       'LEFT JOIN cefr_levels v ON v.id=m.level_id ')
        module_fields = 'm.title AS module_title, v.code AS level'
    progress = [dict(r) for r in connection.execute(text(
        'SELECT p.user_id, p.lesson_id, p.started_at, p.completed_at, p.last_activity, '
        f'l.type, {title} AS title, {module_fields}, {test_out} AS is_test_out '
        'FROM lesson_progress p JOIN users u ON u.id=p.user_id '
        f'JOIN lessons l ON l.id=p.lesson_id {module_join} WHERE {cohort}'), params).mappings()]
    graded_types = ', '.join("'" + value + "'" for value in sorted(GRADED_LESSON_TYPES))
    # Passive lesson types are excluded even if old synthetic attempts say 100%.
    specs = [
        ('lesson_attempts', 'completed_at',
         f"l.type IN ({graded_types}) AND (l.type != 'grammar' OR s.total_questions > 0)",
         's.lesson_id', 's.score', 's.passed', 'JOIN lessons l ON l.id=s.lesson_id'),
        ('listening_attempts', 'created_at', 'true', 's.lesson_id', 's.score', 'NULL', ''),
        ('user_writing_attempts', 'created_at', 's.word_count > 0', 's.lesson_id', 'NULL', 'NULL', ''),
        ('pronunciation_attempts', 'created_at', 'true', 'NULL', 'NULL', 'NULL', ''),
    ]
    events, missing = [], []
    for table, column, condition, lesson_id, score, passed, extra_join in specs:
        if table not in tables:
            missing.append(table)
            continue
        query = (f'SELECT s.user_id, s.{column} AS at, {lesson_id} AS lesson_id, '
                 f'{score} AS score, {passed} AS passed FROM {table} s '
                 f'JOIN users u ON u.id=s.user_id {extra_join} WHERE {cohort} '
                 f'AND s.{column} >= u.created_at AND s.{column} < :as_of AND {condition}')
        for row in connection.execute(text(query), params).mappings():
            events.append({**dict(row), 'kind': table})
    return users, progress, events, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, choices=(7, 14, 30, 60, 90), default=30)
    parser.add_argument('--timezone', default='UTC')
    parser.add_argument('--as-of', help='ISO timestamp, default now in UTC')
    args = parser.parse_args(argv)
    url = os.environ.get('DATABASE_URL')
    if not url:
        parser.error('Set DATABASE_URL explicitly; .env is not loaded automatically')
    try:
        from sqlalchemy import create_engine
        as_of = utc(args.as_of) if args.as_of else datetime.now(UTC)
        ZoneInfo(args.timezone)
        engine = create_engine(url, connect_args={'connect_timeout': 10})
        if engine.dialect.name != 'postgresql':
            raise ValueError('PostgreSQL is required')
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            conn.exec_driver_sql('SET TRANSACTION READ ONLY')
            conn.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
            users, progress, events, missing = read_snapshot(
                conn, cutoff=as_of - timedelta(days=args.days), as_of=as_of)
        report = build_report(users, progress, events, as_of=as_of, days=args.days,
                              timezone_name=args.timezone, missing_sources=missing)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        engine.dispose()
    except Exception as error:
        # SQLAlchemy connection errors can contain credentials/connection details.
        print(f'Report failed ({type(error).__name__}); no report generated. '
              'Check database access, schema and arguments. Credentials are not logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
