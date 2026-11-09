"""Standalone report tests: run with unittest; no Flask or application DB."""
import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'retention_report', Path(__file__).resolve().parents[2] /
    'app/admin/services/retention_report_service.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


def user(uid=1, created=None):
    return {'id': uid, 'created_at': created or NOW - timedelta(days=10),
            'onboarding_completed': True, 'level': 'A1', 'source': 'unknown'}


class RetentionReportTests(unittest.TestCase):
    def summary(self, users, progress=(), events=(), **kwargs):
        return report.summarize(users, progress, events, as_of=NOW, **kwargs)

    def test_early_activity_is_not_day7_retention(self):
        u = user()
        result = self.summary([u], events=[{'user_id': 1, 'at': u['created_at'] + timedelta(hours=2)}])
        self.assertEqual(result['curriculum_submission_retention']['D7'],
                         {'count': 0, 'eligible': 1, 'percent': 0.0})
        self.assertEqual(result['first_24h']['submission_recorded']['count'], 1)

    def test_exact_day7_counts_without_plan_or_completed_lesson(self):
        u = user()
        result = self.summary([u], events=[{'user_id': 1, 'at': u['created_at'] + timedelta(days=7)}])
        self.assertEqual(result['curriculum_submission_retention']['D7']['percent'], 100)
        self.assertEqual(result['first_24h']['one_lesson_completed']['count'], 0)

    def test_immature_users_excluded_from_denominator(self):
        u = user(created=NOW - timedelta(hours=1))
        result = self.summary([u])
        self.assertEqual(result['first_24h']['eligible'], 0)
        self.assertIsNone(result['curriculum_submission_retention']['D1']['percent'])
        self.assertIsNone(result['first_24h']['submission_recorded']['percent'])

    def test_day_window_is_half_open_and_uses_selected_timezone(self):
        u = user(created=datetime(2026, 11, 1, 22, tzinfo=UTC))
        event = {'user_id': 1, 'at': datetime(2026, 11, 2, 22, tzinfo=UTC)}
        # In Istanbul registration is Nov 2, the event is Nov 3 (D1).
        self.assertEqual(self.summary([u], events=[event], timezone_name='Europe/Istanbul')
                         ['curriculum_submission_retention']['D1']['count'], 1)
        event['at'] = datetime(2026, 11, 3, 21, tzinfo=UTC)  # Nov 4 00:00, D2
        self.assertEqual(self.summary([u], events=[event], timezone_name='Europe/Istanbul')
                         ['curriculum_submission_retention']['D1']['count'], 0)

    def test_page_view_and_last_activity_do_not_count_as_submission(self):
        u = user()
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'grammar',
             'started_at': u['created_at'], 'last_activity': u['created_at'] + timedelta(days=7),
             'completed_at': None}
        result = self.summary([u], [p])
        self.assertEqual(result['first_24h']['lesson_opened']['count'], 1)
        self.assertEqual(result['curriculum_submission_retention']['D7']['count'], 0)

    def test_duplicate_events_and_pre_registration_or_future_events(self):
        u = user()
        event = {'user_id': 1, 'at': u['created_at'] + timedelta(days=7)}
        result = self.summary([u], events=[event, event, {'user_id': 1, 'at': NOW},
                              {'user_id': 1, 'at': u['created_at'] - timedelta(seconds=1)}])
        self.assertEqual(result['curriculum_submission_retention']['D7']['count'], 1)
        self.assertEqual(result['first_24h']['submission_recorded']['count'], 0)

    def test_two_lessons_are_distinct_and_current_work_is_not_idle(self):
        u = user()
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz',
             'started_at': u['created_at'], 'last_activity': NOW - timedelta(hours=1),
             'completed_at': u['created_at'] + timedelta(hours=2)}
        result = self.summary([u], [p, dict(p)])
        self.assertEqual(result['first_24h']['one_lesson_completed']['count'], 1)
        self.assertEqual(result['first_24h']['two_lessons_completed']['count'], 0)
        self.assertEqual(result['idle_progress_by_type'], {})

    def test_segment_filters_events_to_its_users(self):
        u1, u2 = user(), user(2)
        u2['level'] = 'B2'
        result = report.build_report([u1, u2], [], [{'user_id': 2, 'at': u2['created_at']}],
                                     as_of=NOW, days=30, timezone_name='UTC')
        self.assertEqual(result['segments']['level']['A1']['first_24h']['submission_recorded']['count'], 0)
        self.assertEqual(result['segments']['level']['B2']['first_24h']['submission_recorded']['count'], 1)

    def test_admin_template_renders_real_denominators_and_missing_data(self):
        from jinja2 import DictLoader, Environment, select_autoescape
        from types import SimpleNamespace
        template = (Path(__file__).resolve().parents[2] /
                    'app/templates/admin/activity/funnel.html').read_text()
        env = Environment(loader=DictLoader({
            'funnel.html': template,
            'admin/activity/_tabs.html': '',
            'admin/base.html': '{% block content %}{% endblock %}',
            'admin/components.html': '{% macro page_header(a,b) %}{% endmacro %}'
                                     '{% macro breadcrumb(a) %}{% endmacro %}',
        }), autoescape=select_autoescape())
        data = report.build_report([user()], [], [], as_of=NOW, days=30, timezone_name='UTC')
        html = env.get_template('funnel.html').render(
            curriculum_report=data, funnel=SimpleNamespace(generated_at=NOW, steps=[]),
            cohorts=[], days=30, weeks=8, url_for=lambda *a, **kw: '/')
        self.assertIn('0 / 1', html)
        self.assertIn('Отправили работу строго на D7', html)
        self.assertIn('н/д', html)  # D30 not yet observable
        self.assertNotIn('Часть источников отправок недоступна', html)

    def test_ordered_path_uses_same_lesson_and_tolerates_commit_order(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': start,
             'completed_at': start + timedelta(minutes=2)}
        event = {'user_id': 1, 'lesson_id': 9, 'at': p['completed_at'] + timedelta(milliseconds=10)}
        p2 = {**p, 'lesson_id': 10, 'started_at': start + timedelta(minutes=3),
              'completed_at': start + timedelta(minutes=4)}
        result = report.build_report([u], [p, p2], [event], as_of=NOW, days=30,
                                     timezone_name='UTC', include_members=True)
        self.assertEqual(result['memberships']['second_completed'], [1])
        self.assertEqual(result['memberships']['opened_without_submitted'], [])
        self.assertEqual(result['ordered_funnel']['steps'][-1]['count'], 1)

    def test_passive_completion_is_not_timed_submission_completion(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'vocabulary', 'started_at': start,
             'completed_at': start + timedelta(minutes=2)}
        # Submission belongs to a different lesson: no same-lesson chain.
        event = {'user_id': 1, 'lesson_id': 10, 'at': start + timedelta(minutes=1)}
        result = report.build_report([u], [p], [event], as_of=NOW, days=30,
                                     timezone_name='UTC', include_members=True)
        self.assertEqual(result['memberships']['completed'], [])
        self.assertEqual(result['memberships']['opened_without_submitted'], [1])

    def test_ordered_path_does_not_reorder_old_completion_or_preopened_next_lesson(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': start,
             'completed_at': start + timedelta(minutes=2)}
        event = {'user_id': 1, 'lesson_id': 9, 'at': start + timedelta(hours=1)}
        result = report.ordered_funnel([u], [p], [event], as_of=NOW, include_members=True)
        self.assertEqual(result['steps'][2]['count'], 1)
        self.assertEqual(result['steps'][3]['count'], 0)
        event['at'] = p['completed_at']
        p2 = {**p, 'lesson_id': 10, 'started_at': start + timedelta(minutes=1)}
        result = report.ordered_funnel([u], [p, p2], [event], as_of=NOW)
        self.assertEqual(result['steps'][3]['count'], 1)
        self.assertEqual(result['steps'][4]['count'], 0)

    def test_memberships_never_exported_by_default(self):
        result = report.build_report([user()], [], [], as_of=NOW, days=30, timezone_name='UTC')
        self.assertNotIn('memberships', result)
        self.assertNotIn('user_ids', result['ordered_funnel']['steps'][0])

    def test_lesson_summary_uses_unique_learners_and_mature_idle_observations(self):
        u = user()
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': u['created_at'],
             'completed_at': None, 'last_activity': u['created_at']}
        events = [{'user_id': 1, 'lesson_id': 9, 'at': u['created_at'] + timedelta(minutes=1)}] * 2
        result = report.lesson_summary([u], [p, p], events, as_of=NOW)
        self.assertEqual(result[0]['opened'], 1)
        self.assertEqual(result[0]['submitted'], 1)
        self.assertEqual(result[0]['idle_unfinished'], 1)
        self.assertEqual(result[0]['idle_unfinished_percent'], 100)

    def test_weekly_cohorts_have_per_metric_mature_denominators(self):
        old, recent = user(), user(2, NOW - timedelta(hours=1))
        result = report.weekly_cohorts([old, recent], [], as_of=NOW)
        self.assertEqual(sum(row['cohort_size'] for row in result), 2)
        self.assertEqual(sum(row['retention']['D7']['eligible'] for row in result), 1)
        self.assertIsNone(result[-1]['retention']['D1']['percent'])

    def test_main_path_accepts_vocabulary_without_graded_submission(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'vocabulary', 'started_at': start,
             'completed_at': start + timedelta(minutes=2)}
        p2 = {**p, 'lesson_id': 10, 'type': 'flashcards',
              'started_at': start + timedelta(minutes=3), 'completed_at': start + timedelta(minutes=4)}
        data = report.build_report([u], [p, p2], [], as_of=NOW, days=30,
                                   timezone_name='UTC', include_members=True)
        self.assertEqual(data['memberships']['path_second_completed'], [1])
        self.assertEqual(data['memberships']['submitted'], [])
        self.assertEqual(data['progress_funnel']['steps'][2]['count'], 1)

    def test_synthetic_testout_never_proves_open_or_completion(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': start,
             'completed_at': start + timedelta(minutes=2), 'is_test_out': True}
        event = {'user_id': 1, 'lesson_id': 9, 'at': p['completed_at']}
        data = report.build_report([u], [p], [event], as_of=NOW, days=30,
                                   timezone_name='UTC', include_members=True)
        self.assertEqual(data['memberships']['path_registered_without_path_opened'], [1])
        self.assertEqual(data['memberships']['path_opened'], [])
        self.assertEqual(data['memberships']['opened'], [])

    def test_testout_open_is_not_independent_open_but_attainment_is_retained(self):
        u = user()
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': u['created_at'],
             'completed_at': u['created_at'], 'is_test_out': True}
        data = self.summary([u], [p])
        self.assertEqual(data['first_24h']['lesson_opened']['count'], 0)
        self.assertEqual(data['first_24h']['one_lesson_completed']['count'], 1)
        self.assertEqual(data['idle_progress_by_type'], {})

    def test_corrupt_completion_before_open_is_not_a_completed_step(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'quiz', 'started_at': start + timedelta(seconds=3),
             'completed_at': start + timedelta(seconds=2)}
        event = {'user_id': 1, 'lesson_id': 9, 'at': start + timedelta(seconds=4)}
        data = report.build_report([u], [p], [event], as_of=NOW, days=30,
                                   timezone_name='UTC', include_members=True)
        self.assertEqual(data['memberships']['path_completed'], [])
        self.assertEqual(data['memberships']['completed'], [])
        self.assertEqual(data['memberships']['submitted'], [1])

    def test_preopened_or_precompleted_lesson_is_not_invented_as_next(self):
        u = user()
        start = u['created_at']
        p = {'user_id': 1, 'lesson_id': 9, 'type': 'vocabulary', 'started_at': start,
             'completed_at': start + timedelta(minutes=2)}
        p2 = {**p, 'lesson_id': 10, 'started_at': start + timedelta(minutes=1),
              'completed_at': start + timedelta(minutes=3)}
        data = report.progress_funnel([u], [p, p2], as_of=NOW, include_members=True)
        self.assertEqual(data['steps'][2]['user_ids'], [1])
        self.assertEqual(data['steps'][3]['user_ids'], [])
        self.assertEqual(data['steps'][4]['user_ids'], [])

    def test_retention_memberships_match_exact_counts_and_mature_denominators(self):
        old, recent = user(), user(2, NOW - timedelta(hours=1))
        events = [{'user_id': 1, 'at': old['created_at'] + timedelta(days=7)},
                  {'user_id': 2, 'at': NOW - timedelta(minutes=10)}]
        data = report.build_report([old, recent], [], events, as_of=NOW, days=30,
                                   timezone_name='UTC', include_members=True)
        self.assertEqual(data['memberships']['eligible_D7'], [1])
        self.assertEqual(data['memberships']['retained_D7'], [1])
        self.assertEqual(data['memberships']['eligible_D30'], [])
        for day in ('D1', 'D7', 'D30'):
            metric = data['overall']['curriculum_submission_retention'][day]
            self.assertEqual(len(data['memberships'][f'eligible_{day}']), metric['eligible'])
            self.assertEqual(len(data['memberships'][f'retained_{day}']), metric['count'])

    def test_arbitrary_source_buckets_only_receive_their_own_event_rows(self):
        from unittest.mock import patch
        users = [user(i) for i in range(1, 21)]
        for u in users:
            u['source'] = f'unique_source_{u["id"]}'
        events = [{'user_id': u['id'], 'at': u['created_at']} for u in users]
        original, observed = report.summarize, []

        def summarize_spy(rows, progress, subset, **kwargs):
            observed.append((len(rows), len(subset)))
            return original(rows, progress, subset, **kwargs)

        with patch.object(report, 'summarize', side_effect=summarize_spy):
            report.build_report(users, [], events, as_of=NOW, days=30, timezone_name='UTC')
        # All singleton source buckets receive one event, not all twenty.
        singletons = [events_count for users_count, events_count in observed if users_count == 1]
        self.assertEqual(singletons, [1] * 20)

    def test_extractor_counts_legacy_zero_question_grades_but_excludes_passive(self):
        from sqlalchemy import create_engine
        engine = create_engine('sqlite://')
        with engine.begin() as conn:
            for statement in (
                'CREATE TABLE users (id int, created_at timestamp, is_admin bool, '
                'onboarding_completed bool, onboarding_level text, acquisition_meta text)',
                'CREATE TABLE lessons (id int, type text)',
                'CREATE TABLE lesson_progress (user_id int, lesson_id int, started_at timestamp, '
                'completed_at timestamp, last_activity timestamp, data text)',
                'CREATE TABLE lesson_attempts (user_id int, lesson_id int, completed_at timestamp, total_questions int, score float, passed bool)',
                "INSERT INTO lessons VALUES (11, 'translation')",
                "INSERT INTO lessons VALUES (12, 'reading')",
                "INSERT INTO lessons VALUES (13, 'grammar')",
                "INSERT INTO users VALUES (1, '2026-11-01', false, true, 'A1', '{}')",
                "INSERT INTO users VALUES (2, '2026-11-01', true, true, 'A1', '{}')",
                '''INSERT INTO lesson_progress VALUES (1, 11, '2026-11-01', '2026-11-01', '2026-11-01', '{"test_out": true, "response_text": "private answer"}')''',
                "INSERT INTO lesson_attempts VALUES (1, 11, '2026-11-02', 0, 0, false)",
                "INSERT INTO lesson_attempts VALUES (1, 12, '2026-11-08', 5, 100, true)",
                "INSERT INTO lesson_attempts VALUES (2, 11, '2026-11-08', 5, 100, true)",
                "INSERT INTO lesson_attempts VALUES (1, 13, '2026-11-08', 0, 100, true)",
                "INSERT INTO lesson_attempts VALUES (1, 13, '2026-11-08', 3, 80, true)",
            ):
                conn.exec_driver_sql(statement)
            users, progress, events, missing = report.read_snapshot(
                conn, cutoff=NOW - timedelta(days=30), as_of=NOW)
        self.assertEqual([u['id'] for u in users], [1])
        self.assertEqual(len(events), 2)
        self.assertEqual({(event['lesson_id'], event['score']) for event in events}, {(11, 0), (13, 80)})
        self.assertEqual(len(missing), 3)
        self.assertEqual(len(progress), 1)
        self.assertTrue(progress[0]['is_test_out'])
        self.assertNotIn('data', progress[0])
        self.assertNotIn('response_text', progress[0])


if __name__ == '__main__':
    unittest.main()
