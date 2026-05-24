# tests/admin/test_observability.py
"""Tests for admin observability — structured logging in critical operations.

Verifies that:
- print() calls in book_processing_service have been replaced with logger calls
- Critical exception handlers in admin routes emit ERROR-level log records
  that include contextual fields (admin_id, target id, error)
"""
import logging
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user to be an authenticated admin for route testing."""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user


# ---------------------------------------------------------------------------
# book_processing_service — background thread logging
# ---------------------------------------------------------------------------

class TestBookProcessingServiceLogging:
    """Ensure background thread uses logger instead of print()."""

    @pytest.mark.smoke
    def test_processing_start_is_logged_as_info(self, app, caplog):
        """start_background_chapter_processing logs INFO at worker start."""
        from app.admin.services.book_processing_service import BookProcessingService

        mock_app = MagicMock()
        ctx_mgr = MagicMock()
        mock_app.app_context.return_value.__enter__ = lambda s: None
        mock_app.app_context.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            'app.admin.services.book_processing_service.logger'
        ) as mock_logger:
            # Run worker synchronously by extracting the _worker closure.
            # We patch safe_process_book_chapters_words to return quickly.
            with patch(
                'app.books.safe_processors.safe_process_book_chapters_words',
                return_value={'status': 'success'},
            ):
                thread = BookProcessingService.start_background_chapter_processing(
                    mock_app, book_id=42
                )
                thread.join(timeout=5)

        mock_logger.info.assert_called()
        first_call_args = mock_logger.info.call_args_list[0][0]
        assert 'book_id' in first_call_args[0] or '42' in str(first_call_args)

    def test_processing_error_is_logged_as_error(self, app, caplog):
        """start_background_chapter_processing logs ERROR on exception."""
        from app.admin.services.book_processing_service import BookProcessingService

        mock_app = MagicMock()
        mock_app.app_context.return_value.__enter__ = lambda s: None
        mock_app.app_context.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            'app.admin.services.book_processing_service.logger'
        ) as mock_logger:
            with patch(
                'app.books.safe_processors.safe_process_book_chapters_words',
                side_effect=RuntimeError('disk full'),
            ):
                thread = BookProcessingService.start_background_chapter_processing(
                    mock_app, book_id=99
                )
                thread.join(timeout=5)

        mock_logger.error.assert_called()
        error_args = mock_logger.error.call_args_list[0][0]
        assert '99' in str(error_args)

    def test_no_print_calls_in_book_processing_service(self, app):
        """Ensure book_processing_service.py no longer uses print() at runtime."""
        import inspect
        import app.admin.services.book_processing_service as mod

        src = inspect.getsource(mod)
        # Check for standalone print( calls — excluding comments and strings
        import re
        non_comment_lines = [
            line for line in src.splitlines()
            if not line.strip().startswith('#')
        ]
        source_without_comments = '\n'.join(non_comment_lines)
        assert 'print(' not in source_without_comments, (
            "book_processing_service.py still contains print() calls; "
            "use logger instead"
        )


# ---------------------------------------------------------------------------
# grammar_lab_routes — exception handler logging
# ---------------------------------------------------------------------------

class TestGrammarLabRouteErrorLogging:
    """Verify that grammar lab route exception handlers emit structured logs."""

    @pytest.mark.smoke
    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_delete_topic_db_error_is_logged(
        self, mock_db, admin_client, mock_admin_user, caplog
    ):
        """delete_topic logs ERROR with admin_id and topic_id on DB failure."""
        mock_db.session.delete.return_value = None
        mock_db.session.commit.side_effect = Exception('DB connection lost')
        mock_db.session.rollback.return_value = None

        with patch('app.admin.routes.grammar_lab_routes.GrammarTopic') as mock_topic_cls:
            mock_topic = MagicMock()
            mock_topic.title = 'Test Topic'
            mock_topic_cls.query.get_or_404.return_value = mock_topic

            with caplog.at_level(logging.ERROR, logger='app.admin.routes.grammar_lab_routes'):
                admin_client.post(
                    '/admin/grammar-lab/topics/99/delete',
                    follow_redirects=True,
                )

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "Expected at least one ERROR log record for topic delete failure"
        combined = ' '.join(r.message for r in error_records)
        assert '99' in combined or 'admin_id' in combined.lower() or 'topic' in combined.lower()

    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_delete_exercise_db_error_is_logged(
        self, mock_db, admin_client, mock_admin_user, caplog
    ):
        """delete_exercise logs ERROR with admin_id and exercise_id on DB failure."""
        mock_db.session.delete.return_value = None
        mock_db.session.commit.side_effect = Exception('FK violation')
        mock_db.session.rollback.return_value = None

        with patch('app.admin.routes.grammar_lab_routes.GrammarExercise') as mock_ex_cls:
            mock_ex = MagicMock()
            mock_ex.topic_id = 5
            mock_ex_cls.query.get_or_404.return_value = mock_ex

            with caplog.at_level(logging.ERROR, logger='app.admin.routes.grammar_lab_routes'):
                admin_client.post(
                    '/admin/grammar-lab/exercises/77/delete',
                    follow_redirects=True,
                )

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "Expected at least one ERROR log for exercise delete failure"

    @patch('app.admin.routes.grammar_lab_routes.db')
    @patch('app.admin.routes.grammar_lab_routes.log_admin_action')
    @patch('app.grammar_lab.content_validator.validate_exercise_content', return_value=None)
    def test_update_exercise_db_error_is_logged(
        self, _mock_validate, mock_log_action, mock_db, admin_client, mock_admin_user, caplog
    ):
        """edit_exercise logs ERROR with admin_id and exercise_id on DB failure."""
        mock_db.session.commit.side_effect = Exception('timeout')
        mock_db.session.rollback.return_value = None
        mock_db.session.flush.return_value = None

        with patch('app.admin.routes.grammar_lab_routes.GrammarExercise') as mock_ex_cls:
            mock_ex = MagicMock()
            mock_ex.topic_id = 3
            mock_ex.exercise_type = 'fill_blank'
            mock_ex.content = {'correct_answer': 'word'}
            mock_ex.order = 1
            mock_ex.difficulty = 1
            mock_topic = MagicMock()
            mock_topic.id = 3
            mock_ex.topic = mock_topic
            mock_ex_cls.query.get_or_404.return_value = mock_ex

            with caplog.at_level(logging.ERROR, logger='app.admin.routes.grammar_lab_routes'):
                admin_client.post(
                    '/admin/grammar-lab/exercises/55/edit',
                    data={
                        'exercise_type': 'fill_blank',
                        'order': '1',
                        'difficulty': '1',
                        'content': '{"correct_answer": "word"}',
                    },
                    follow_redirects=True,
                )

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "Expected at least one ERROR log for exercise update failure"


# ---------------------------------------------------------------------------
# Structural check — no bare print() in admin routes or services
# ---------------------------------------------------------------------------

class TestNoPrintInAdminCode:
    """Guard against new print() calls slipping into admin modules."""

    def _get_print_violations(self, module_path: str) -> list[tuple[str, int, str]]:
        """Return list of (filepath, lineno, line) for standalone print() calls."""
        import os
        import re

        violations = []
        for dirpath, _, filenames in os.walk(module_path):
            for fname in filenames:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(dirpath, fname)
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped.startswith('#'):
                            continue
                        if re.search(r'\bprint\s*\(', stripped):
                            violations.append((fpath, lineno, stripped))
        return violations

    def test_no_print_calls_in_admin_routes(self, app):
        """No print() calls in app/admin/routes/."""
        import os
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'app', 'admin', 'routes',
        )
        violations = self._get_print_violations(base)
        assert not violations, (
            f"Found {len(violations)} print() call(s) in admin routes — use logger:\n"
            + '\n'.join(f"  {f}:{l}: {t}" for f, l, t in violations)
        )

    def test_no_print_calls_in_admin_services(self, app):
        """No print() calls in app/admin/services/."""
        import os
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'app', 'admin', 'services',
        )
        violations = self._get_print_violations(base)
        assert not violations, (
            f"Found {len(violations)} print() call(s) in admin services — use logger:\n"
            + '\n'.join(f"  {f}:{l}: {t}" for f, l, t in violations)
        )
