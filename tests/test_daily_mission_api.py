"""Integration tests for mission plan in API endpoints, dashboard route, and streak service."""
from unittest.mock import patch, MagicMock

import pytest


UNIFIED_MODULE = "app.daily_plan.service"

SAMPLE_MISSION_PAYLOAD = {
    'plan_version': '1',
    'mission': {
        'type': 'progress',
        'title': 'Продвигаемся по курсу',
        'reason_code': 'primary_track_progress',
        'reason_text': 'Двигаемся вперёд',
    },
    'primary_goal': {
        'type': 'advance',
        'title': 'Пройти урок',
        'success_criterion': 'lesson_completed',
    },
    'primary_source': {
        'kind': 'normal_course',
        'id': '42',
        'label': 'Урок 5',
    },
    'phases': [
        {'id': 'p1', 'phase': 'recall', 'title': 'Вспоминаем слова', 'source_kind': 'srs', 'mode': 'srs_review', 'required': True, 'completed': False},
        {'id': 'p2', 'phase': 'learn', 'title': 'Новый урок', 'source_kind': 'normal_course', 'mode': 'curriculum_lesson', 'required': True, 'completed': False},
        {'id': 'p3', 'phase': 'use', 'title': 'Практика', 'source_kind': 'normal_course', 'mode': 'lesson_practice', 'required': True, 'completed': False},
    ],
    'completion': {'done': False, 'phases_completed': 0, 'phases_total': 3},
    'legacy': {'next_lesson': {'lesson_id': 42, 'title': 'Test', 'module_number': 1}},
}

SAMPLE_LEGACY_PAYLOAD = {
    'steps': {
        'lesson': {'state': 'available'},
        'grammar': {'state': 'available'},
        'words': None,
        'books': None,
        'book_course_practice': None,
    },
    'next_lesson': {'lesson_id': 42, 'title': 'Test', 'module_number': 1, 'lesson_type': 'standard', 'level_code': 'A1', 'lesson_order': 1},
    'grammar_topic': {'topic_id': 1, 'title': 'Present Simple'},
    'words_due': 0,
    'has_any_words': False,
    'book_to_read': None,
    'suggested_books': [],
    'onboarding': None,
    'bonus': None,
    'book_course_lesson': None,
    'book_course_done_today': False,
}

SAMPLE_SUMMARY = {
    'lessons_count': 0,
    'lesson_types': [],
    'words_reviewed': 0,
    'srs_words_reviewed': 0,
    'srs_new_reviewed': 0,
    'srs_review_reviewed': 0,
    'grammar_exercises': 0,
    'grammar_correct': 0,
    'books_read': [],
    'book_course_lessons_today': 0,
    'lesson_score': None,
    'lesson_title': None,
    'grammar_topic_title': None,
    'book_chapter_title': None,
}


class TestDailyStatusAPIMissionIntegration:
    @patch('app.achievements.streak_service.process_streak_on_activity')
    @patch('app.telegram.queries.get_yesterday_summary', return_value={})
    @patch('app.telegram.queries.get_daily_summary', return_value=SAMPLE_SUMMARY)
    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_returns_mission_payload_when_flag_on(
        self, mock_unified, mock_summary, mock_yesterday, mock_streak,
        app, authenticated_client, test_user,
    ):
        mock_unified.return_value = SAMPLE_MISSION_PAYLOAD
        mock_streak.return_value = {
            'streak_status': {'streak': 5},
            'required_steps': 1,
            'streak_repaired': False,
            'steps_done': 0,
            'steps_total': 3,
            'milestone_reward': None,
        }

        resp = authenticated_client.get('/api/daily-status?tz=Europe/Moscow')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['plan']['plan_version'] == '1'
        assert data['plan']['mission']['type'] == 'progress'
        assert len(data['plan']['phases']) == 3

    @patch('app.achievements.streak_service.process_streak_on_activity')
    @patch('app.telegram.queries.get_yesterday_summary', return_value={})
    @patch('app.telegram.queries.get_daily_summary', return_value=SAMPLE_SUMMARY)
    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_returns_legacy_payload_when_flag_off(
        self, mock_unified, mock_summary, mock_yesterday, mock_streak,
        app, authenticated_client, test_user,
    ):
        mock_unified.return_value = SAMPLE_LEGACY_PAYLOAD
        mock_streak.return_value = {
            'streak_status': {'streak': 5},
            'required_steps': 1,
            'streak_repaired': False,
            'steps_done': 0,
            'steps_total': 2,
            'milestone_reward': None,
        }

        resp = authenticated_client.get('/api/daily-status?tz=Europe/Moscow')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'steps' in data['plan']
        assert 'phases' not in data['plan']


class TestDailyPlanAPIMissionIntegration:
    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_returns_mission_fields_when_flag_on(
        self, mock_unified, app, authenticated_client,
    ):
        mock_unified.return_value = SAMPLE_MISSION_PAYLOAD
        resp = authenticated_client.get('/api/daily-plan?tz=Europe/Moscow')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['plan_version'] == '1'
        assert data['mission']['type'] == 'progress'

    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_returns_legacy_fields_when_flag_off(
        self, mock_unified, app, authenticated_client,
    ):
        mock_unified.return_value = SAMPLE_LEGACY_PAYLOAD
        resp = authenticated_client.get('/api/daily-plan?tz=Europe/Moscow')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'steps' in data
        assert 'next_lesson' in data


class TestComputePlanStepsWithMissionPhases:
    def test_all_phases_incomplete(self):
        from app.achievements.streak_service import compute_plan_steps
        plan = {
            'phases': [
                {'id': 'p1', 'phase': 'recall', 'completed': False},
                {'id': 'p2', 'phase': 'learn', 'completed': False},
                {'id': 'p3', 'phase': 'use', 'completed': False},
            ],
        }
        completion, available, done, total = compute_plan_steps(plan, {})
        assert done == 0
        assert total == 3
        assert completion == {'p1': False, 'p2': False, 'p3': False}
        assert set(available.keys()) == {'p1', 'p2', 'p3'}

    def test_some_phases_completed(self):
        from app.achievements.streak_service import compute_plan_steps
        plan = {
            'phases': [
                {'id': 'p1', 'phase': 'recall', 'completed': True},
                {'id': 'p2', 'phase': 'learn', 'completed': False},
                {'id': 'p3', 'phase': 'use', 'completed': True},
            ],
        }
        completion, available, done, total = compute_plan_steps(plan, {})
        assert done == 2
        assert total == 3
        assert completion['p1'] is True
        assert completion['p2'] is False

    def test_all_phases_completed(self):
        from app.achievements.streak_service import compute_plan_steps
        plan = {
            'phases': [
                {'id': 'p1', 'phase': 'recall', 'completed': True},
                {'id': 'p2', 'phase': 'learn', 'completed': True},
                {'id': 'p3', 'phase': 'use', 'completed': True},
            ],
        }
        completion, available, done, total = compute_plan_steps(plan, {})
        assert done == 3
        assert total == 3

    def test_phases_without_completed_key_default_to_false(self):
        from app.achievements.streak_service import compute_plan_steps
        plan = {
            'phases': [
                {'id': 'p1', 'phase': 'recall'},
                {'id': 'p2', 'phase': 'learn'},
            ],
        }
        completion, available, done, total = compute_plan_steps(plan, {})
        assert done == 0
        assert total == 2

    def test_legacy_plan_still_works(self):
        from app.achievements.streak_service import compute_plan_steps
        plan = {
            'steps': {
                'lesson': {'state': 'completed'},
                'grammar': {'state': 'available'},
                'words': None,
                'books': None,
                'book_course_practice': None,
            },
        }
        summary = {
            'lessons_count': 1,
            'grammar_exercises': 0,
            'words_reviewed': 0,
            'srs_words_reviewed': 0,
            'books_read': [],
        }
        completion, available, done, total = compute_plan_steps(plan, summary)
        assert total == 2
        assert done == 1
        assert completion['lesson'] is True


class TestNextStepWithMissionPhases:
    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_returns_next_incomplete_phase(
        self, mock_unified, app, authenticated_client,
    ):
        payload = dict(SAMPLE_MISSION_PAYLOAD)
        payload['phases'] = [
            {'id': 'p1', 'phase': 'recall', 'title': 'Вспоминаем', 'completed': True},
            {'id': 'p2', 'phase': 'learn', 'title': 'Новый урок', 'completed': False},
            {'id': 'p3', 'phase': 'use', 'title': 'Практика', 'completed': False},
        ]
        mock_unified.return_value = payload

        resp = authenticated_client.get('/api/daily-plan/next-step')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_next'] is True
        assert data['step_type'] == 'learn'
        assert data['step_title'] == 'Новый урок'
        assert data['steps_done'] == 1
        assert data['steps_total'] == 3

    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_all_phases_done(
        self, mock_unified, app, authenticated_client,
    ):
        payload = dict(SAMPLE_MISSION_PAYLOAD)
        payload['phases'] = [
            {'id': 'p1', 'phase': 'recall', 'title': 'R', 'completed': True},
            {'id': 'p2', 'phase': 'learn', 'title': 'L', 'completed': True},
            {'id': 'p3', 'phase': 'use', 'title': 'U', 'completed': True},
        ]
        mock_unified.return_value = payload

        resp = authenticated_client.get('/api/daily-plan/next-step')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_next'] is False
        assert data['all_done'] is True
        assert data['steps_done'] == 3

    @patch('app.telegram.queries.get_daily_summary', return_value=SAMPLE_SUMMARY)
    @patch(f'{UNIFIED_MODULE}.get_daily_plan_unified')
    def test_legacy_plan_still_works(
        self, mock_unified, mock_summary, app, authenticated_client,
    ):
        mock_unified.return_value = SAMPLE_LEGACY_PAYLOAD

        resp = authenticated_client.get('/api/daily-plan/next-step')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['has_next'] is True
        assert data['step_type'] == 'lesson'
