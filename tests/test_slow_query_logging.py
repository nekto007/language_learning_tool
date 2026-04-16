"""
Tests for slow query logging (app/utils/db_config.py — configure_slow_query_logging).

Strategy: monkeypatch time.time so that every call advances the clock by 200 ms,
making every before/after cursor-execute pair exceed the 100 ms threshold and
trigger a slow_query WARNING regardless of actual DB speed.
"""
import logging
import time as time_module

import pytest
from sqlalchemy import text
from unittest.mock import patch


@pytest.mark.smoke
def test_slow_query_triggers_warning(app, db_session, caplog):
    """time.time advancing 200 ms per call triggers slow_query log entry."""
    state = {"t": 0.0}

    def mock_time():
        # Advance 200 ms on every call so each before/after pair shows 200 ms elapsed.
        state["t"] += 0.2
        return state["t"]

    with patch.object(time_module, "time", mock_time):
        with caplog.at_level(logging.WARNING, logger="app.utils.db_config"):
            # db_session already has an active app context; just run a query.
            db_session.execute(text("SELECT 1"))

    slow_records = [
        r
        for r in caplog.records
        if r.name == "app.utils.db_config" and "slow_query" in r.message
    ]
    assert slow_records, "Expected at least one slow_query WARNING log entry"
    assert "elapsed_ms" in slow_records[0].message


def test_fast_query_no_warning(app, db_session, caplog):
    """A normally fast query must NOT produce a slow_query warning."""
    with caplog.at_level(logging.WARNING, logger="app.utils.db_config"):
        db_session.execute(text("SELECT 1"))

    slow_records = [
        r
        for r in caplog.records
        if r.name == "app.utils.db_config" and "slow_query" in r.message
    ]
    # A real SELECT 1 should complete well under 100 ms.
    assert not slow_records, "Unexpected slow_query warning for a fast query"


def test_slow_query_ms_config_respected(app):
    """configure_slow_query_logging accepts SLOW_QUERY_MS from app.config without errors."""
    from app.utils.db_config import configure_slow_query_logging
    from app.utils.db import db

    original = app.config.get("SLOW_QUERY_MS", 100)
    app.config["SLOW_QUERY_MS"] = 50
    try:
        # Re-register with new threshold — must not raise
        with app.app_context():
            configure_slow_query_logging(app, db)
    finally:
        app.config["SLOW_QUERY_MS"] = original
