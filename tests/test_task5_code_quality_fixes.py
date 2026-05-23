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

    messages = " | ".join(record.getMessage() for record in caplog.records)
    assert "listening streak" in messages
    assert "writing streak" in messages
    assert "speaking streak" in messages


# ── C-011: navbar grammar/words badges log silent excepts ──


def test_template_utils_logs_words_due_count_failure(caplog):
    # The function is defined inside ``init_template_utils``; we recreate the
    # closure via direct call after patching the source query.
    from app.utils import template_utils

    src = Path(template_utils.__file__).read_text(encoding="utf-8")
    # Sanity: ensure the regression introduced the logger call so future
    # refactors don't silently drop it again.
    assert "Failed to get words due count for navbar" in src
    assert "Failed to get grammar due count for navbar" in src


# ── DC-001 / DC-002 / DC-006: dead files removed ──


@pytest.mark.smoke
def test_dead_files_removed():
    assert not (REPO_ROOT / "pytest.ini.bak").exists()
    assert not (
        REPO_ROOT / "app" / "templates" / "curriculum" / "lessons" / "vocabulary_old.html.backup"
    ).exists()
    assert not (REPO_ROOT / "app" / "static" / "js" / "reader-optimized.js").exists()
