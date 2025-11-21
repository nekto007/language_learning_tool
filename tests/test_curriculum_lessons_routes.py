"""
Tests for curriculum lesson routes
Тесты маршрутов уроков
"""
import pytest
from unittest.mock import patch, MagicMock, Mock
from datetime import datetime, UTC
from flask import url_for


class TestUpdateLessonProgressHelper:
    """Тесты вспомогательной функции update_lesson_progress_with_grading"""

    def test_update_existing_progress_with_passing_score(self, app, test_user, test_lesson_vocabulary):
        """Тест обновления существующего прогресса с проходным баллом"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from app.curriculum.models import LessonProgress
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            # Create existing progress
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress',
                score=50.0
            )

            result = {'score': 85.5, 'answers': []}

            # Mock process_lesson_completion
            with patch('app.curriculum.routes.lessons.process_lesson_completion') as mock_completion:
                mock_completion.return_value = {'grade': 'A', 'achievements': []}

                updated_progress, completion_result = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    progress,
                    result,
                    passing_score=70
                )

                # Verify progress was updated
                assert updated_progress.score == 85.5
                assert updated_progress.status == 'completed'
                assert updated_progress.completed_at is not None
                assert mock_completion.called

    def test_update_progress_with_failing_score(self, app, test_user, test_lesson_vocabulary):
        """Тест обновления прогресса с непроходным баллом"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from app.curriculum.models import LessonProgress
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress'
            )

            result = {'score': 45.0}

            with patch('app.curriculum.routes.lessons.process_lesson_completion') as mock_completion:
                updated_progress, completion_result = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    progress,
                    result,
                    passing_score=70
                )

                # Should remain in_progress
                assert updated_progress.score == 45.0
                assert updated_progress.status == 'in_progress'
                assert updated_progress.completed_at is None
                # process_lesson_completion should NOT be called
                assert not mock_completion.called

    def test_create_new_progress_with_passing_score(self, app, test_user, test_lesson_vocabulary, db_session):
        """Тест создания нового прогресса с проходным баллом"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            result = {'score': 95.0}

            with patch('app.curriculum.routes.lessons.process_lesson_completion') as mock_completion:
                mock_completion.return_value = {'grade': 'A+'}

                progress, completion_result = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    None,  # No existing progress
                    result,
                    passing_score=70
                )

                # Verify new progress was created
                assert progress is not None
                assert progress.user_id == test_user.id
                assert progress.lesson_id == test_lesson_vocabulary.id
                assert progress.score == 95.0
                assert progress.status == 'completed'
                assert mock_completion.called

    def test_update_progress_rounds_score(self, app, test_user, test_lesson_vocabulary):
        """Тест что оценка округляется до 2 знаков"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from app.curriculum.models import LessonProgress
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress'
            )

            result = {'score': 87.6666666}

            with patch('app.curriculum.routes.lessons.process_lesson_completion'):
                updated_progress, _ = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    progress,
                    result
                )

                # Score should be rounded to 2 decimal places
                assert updated_progress.score == 87.67

    def test_update_progress_handles_completion_error(self, app, test_user, test_lesson_vocabulary, caplog):
        """Тест что ошибка в process_lesson_completion не ломает обновление прогресса"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from app.curriculum.models import LessonProgress
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress'
            )

            result = {'score': 85.0}

            with patch('app.curriculum.routes.lessons.process_lesson_completion') as mock_completion:
                mock_completion.side_effect = Exception("Achievement service error")

                # Should not raise exception
                updated_progress, completion_result = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    progress,
                    result
                )

                # Progress should still be updated
                assert updated_progress.score == 85.0
                assert updated_progress.status == 'completed'
                # completion_result should be None due to error
                assert completion_result is None

    def test_update_progress_sets_timestamps(self, app, test_user, test_lesson_vocabulary):
        """Тест что устанавливаются корректные timestamp"""
        from app.curriculum.routes.lessons import update_lesson_progress_with_grading
        from app.curriculum.models import LessonProgress
        from flask_login import login_user

        with app.test_request_context():
            login_user(test_user)

            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress'
            )

            result = {'score': 90.0}

            with patch('app.curriculum.routes.lessons.process_lesson_completion'):
                updated_progress, _ = update_lesson_progress_with_grading(
                    test_lesson_vocabulary,
                    progress,
                    result
                )

                # Verify timestamps
                assert updated_progress.last_activity is not None
                assert updated_progress.completed_at is not None


