"""Integration tests for srs_limit_reason exposure in /api/daily-status and /api/daily-plan.

The reason codes (`backlog_reduction`, `accuracy_low`) are surfaced from
`SRSService.get_adaptive_limit_reason` so the dashboard can render a one-shot
toast when the new-card cap is reduced.
"""
from __future__ import annotations

from unittest.mock import patch


def _linear_plan() -> dict:
    return {
        'mode': 'linear',
        'position': {
            'lesson_id': 101,
            'lesson_type': 'card',
            'lesson_number': 3,
            'module_id': 50,
            'module_number': 5,
            'level_code': 'B1',
        },
        'progress': {'level': 'B1', 'percent': 20, 'lessons_remaining_in_level': 60},
        'baseline_slots': [
            {
                'kind': 'srs',
                'title': 'Карточки на повторение',
                'eta_minutes': 5,
                'url': '/study?source=linear_plan',
                'completed': False,
                'data': {'due_count': 3, 'srs_limit_reason': 'backlog_reduction'},
            },
        ],
        'continuation': {'available': False, 'next_lessons': []},
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': False,
            'effective_mode': 'linear',
            'fallback_reason': None,
        },
    }


def _empty_summary() -> dict:
    return {
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
    }


class TestSrsLimitReasonInDailyPlanApi:
    def test_normal_reason_omitted_from_payload(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='normal',
             ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert 'srs_limit_reason' not in response.get_json()

    def test_backlog_reduction_reason_surfaced(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='backlog_reduction',
             ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert response.get_json().get('srs_limit_reason') == 'backlog_reduction'

    def test_accuracy_low_reason_surfaced(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='accuracy_low',
             ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert response.get_json().get('srs_limit_reason') == 'accuracy_low'


class TestSrsLimitReasonInDailyStatusApi:
    def test_backlog_reduction_reason_surfaced(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='backlog_reduction',
             ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert response.get_json().get('srs_limit_reason') == 'backlog_reduction'

    def test_accuracy_low_reason_surfaced(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='accuracy_low',
             ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert response.get_json().get('srs_limit_reason') == 'accuracy_low'

    def test_normal_reason_omitted_from_payload(self, authenticated_client):
        plan = _linear_plan()
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()), \
             patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()), \
             patch(
                 'app.study.services.SRSService.get_adaptive_limit_reason',
                 return_value='normal',
             ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        assert 'srs_limit_reason' not in response.get_json()
