"""
Tests for template variable default handling (Task 32).

Verifies that templates with unguarded variable references handle None/missing
values gracefully and do not raise 500 errors on edge cases.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.study.models import StudySession
from app.utils.db import db


class TestStudyStatsNullStartTime:
    """Tests for study/stats.html with session.start_time = None (edge case)."""

    @pytest.mark.smoke
    def test_stats_page_renders_with_null_start_time(self, authenticated_client, test_user, db_session, study_settings):
        """Verify stats page doesn't 500 when a session has start_time=None."""
        session = StudySession(
            user_id=test_user.id,
            session_type='cards',
            start_time=None,
            words_studied=3,
            correct_answers=2,
            incorrect_answers=1,
        )
        db_session.add(session)
        db_session.commit()

        response = authenticated_client.get('/study/stats')

        assert response.status_code == 200

    def test_stats_page_renders_without_sessions(self, authenticated_client, study_settings):
        """Verify stats page renders OK with no sessions at all (empty recent_sessions)."""
        response = authenticated_client.get('/study/stats')

        assert response.status_code == 200

    def test_stats_page_renders_with_normal_session(self, authenticated_client, study_session, study_settings):
        """Verify stats page renders OK when start_time is present (baseline)."""
        response = authenticated_client.get('/study/stats')

        assert response.status_code == 200


class TestCurriculumIndexNullLastActivity:
    """Tests for curriculum/index.html with activity.last_activity = None (edge case)."""

    def test_learn_index_with_null_last_activity(self, authenticated_client, test_user, db_session):
        """Verify /learn/ doesn't 500 when a progress record has last_activity=None."""
        activity_with_null = {
            'lesson': MagicMock(title='Test Lesson', id=1),
            'module': MagicMock(number=1),
            'level': MagicMock(code='A1'),
            'status': 'in_progress',
            'score': None,
            'last_activity': None,
        }

        with patch(
            'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_recent_activity',
            return_value=[activity_with_null]
        ):
            with patch(
                'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_levels_with_progress',
                return_value=[{
                    'level': MagicMock(code='A1', name='Beginner'),
                    'total_lessons': 5,
                    'completed_lessons': 2,
                    'modules': [],
                }]
            ):
                with patch(
                    'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_gamification_stats',
                    return_value={}
                ):
                    response = authenticated_client.get('/learn/')

        assert response.status_code == 200

    @pytest.mark.smoke
    def test_learn_index_with_empty_activity(self, authenticated_client):
        """Verify /learn/ renders OK with no recent activity (no strftime called)."""
        with patch(
            'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_recent_activity',
            return_value=[]
        ):
            with patch(
                'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_levels_with_progress',
                return_value=[]
            ):
                with patch(
                    'app.curriculum.services.curriculum_cache_service.CurriculumCacheService.get_gamification_stats',
                    return_value={}
                ):
                    response = authenticated_client.get('/learn/')

        assert response.status_code == 200
