"""Regression tests for Task 5 code quality fixes (2026-05-23).

Each test pins one finding from
``docs/audit/2026-05-23-audit-findings.md`` so future refactors stay caught.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# ── C-005: SQL identifier allowlist in repository.update_download_status ──


@pytest.mark.smoke
def test_repository_rejects_unknown_table_identifier():
    from app.repository import _validate_sql_identifier, _ALLOWED_SQL_TABLES

    with pytest.raises(ValueError):
        _validate_sql_identifier("users; DROP TABLE users", _ALLOWED_SQL_TABLES)


@pytest.mark.smoke
def test_repository_accepts_allowlisted_identifier():
    from app.repository import _validate_sql_identifier, _ALLOWED_SQL_TABLES, _ALLOWED_SQL_COLUMNS

    assert _validate_sql_identifier("collection_words", _ALLOWED_SQL_TABLES) == "collection_words"
    assert _validate_sql_identifier("english_word", _ALLOWED_SQL_COLUMNS) == "english_word"


# ── C-009: streak service streak helpers log silent excepts ──


@pytest.mark.smoke
def test_streak_helpers_log_on_query_failure(monkeypatch, caplog):
    import app.achievements.streak_service as ss

    class _BrokenSession:
        def query(self, *_a, **_kw):
            raise RuntimeError("synthetic db failure")

    with caplog.at_level(logging.ERROR, logger=ss.logger.name):
        assert ss.get_listening_streak(user_id=999, db_session=_BrokenSession()) == 0
        assert ss.get_writing_streak(user_id=999, db_session=_BrokenSession()) == 0
        assert ss.get_speaking_streak(user_id=999, db_session=_BrokenSession()) == 0
        assert ss.get_immersion_streak(user_id=999, db_session=_BrokenSession()) == 0

    messages = " | ".join(record.getMessage() for record in caplog.records)
    assert "listening streak" in messages
    assert "writing streak" in messages
    assert "speaking streak" in messages
    assert "immersion streak" in messages


# ── C-011: navbar grammar/words badges log silent excepts ──


def test_template_utils_logs_words_due_count_failure(app, caplog):
    """Force the navbar badge queries to raise and assert exceptions are logged.

    Exercises the closures built by ``init_template_utils.inject_curriculum_data``
    so a future refactor that drops the ``logger.exception`` calls is caught.
    """
    import app.utils.template_utils as tu
    from flask_login import AnonymousUserMixin
    from unittest.mock import patch, MagicMock

    class _FakeAuthedUser(AnonymousUserMixin):
        is_authenticated = True
        id = 999

    # Locate the context processor that exposes the badge helpers.
    ctx = None
    with app.test_request_context('/'):
        with patch('flask_login.utils._get_user', return_value=_FakeAuthedUser()):
            for proc in app.template_context_processors[None]:
                try:
                    result = proc()
                except Exception:
                    continue
                if isinstance(result, dict) and 'get_words_due_count' in result:
                    ctx = result
                    break

    assert ctx is not None, 'inject_curriculum_data context processor not found'

    broken_session = MagicMock()
    broken_session.query.side_effect = RuntimeError('synthetic db failure')

    from app.utils import db as db_mod

    with app.test_request_context('/'):
        with patch('flask_login.utils._get_user', return_value=_FakeAuthedUser()):
            with patch.object(db_mod.db, 'session', broken_session):
                with caplog.at_level(logging.ERROR, logger=tu.logger.name):
                    assert ctx['get_words_due_count']() == 0
                    assert ctx['get_grammar_due_count']() == 0

    messages = ' | '.join(rec.getMessage() for rec in caplog.records)
    assert 'words due count' in messages
    assert 'grammar due count' in messages


# ── DC-001 / DC-002 / DC-006: dead files removed ──


@pytest.mark.smoke
def test_dead_files_removed():
    assert not (REPO_ROOT / "pytest.ini.bak").exists()
    assert not (
        REPO_ROOT / "app" / "templates" / "curriculum" / "lessons" / "vocabulary_old.html.backup"
    ).exists()
    assert not (REPO_ROOT / "app" / "static" / "js" / "reader-optimized.js").exists()
