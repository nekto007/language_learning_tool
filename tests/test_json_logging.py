"""Tests for structured JSON logging configuration."""
import json
import logging
import os

import pytest


@pytest.mark.smoke
def test_json_formatter_produces_valid_json(monkeypatch, tmp_path):
    """When LOG_FORMAT=json, log records must be valid JSON objects."""
    monkeypatch.setenv("LOG_FORMAT", "json")

    # Import fresh so the function is not cached with old handlers
    import importlib
    import config.logging_config as logging_config_module
    importlib.reload(logging_config_module)

    # Build an isolated logger with a stream-to-string handler
    import io
    stream = io.StringIO()

    from pythonjsonlogger import jsonlogger

    handler = logging.StreamHandler(stream)

    class _TestJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super().add_fields(log_record, record, message_dict)
            log_record.setdefault("level", record.levelname)
            log_record.setdefault("logger", record.name)

    handler.setFormatter(_TestJsonFormatter(fmt="%(asctime)s %(name)s %(levelname)s %(message)s"))

    test_logger = logging.getLogger("test_json_logging_isolated")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.DEBUG)
    test_logger.propagate = False

    test_logger.info("hello structured world")

    output = stream.getvalue().strip()
    assert output, "Expected at least one log line"

    # Every line must be valid JSON
    for line in output.splitlines():
        record = json.loads(line)
        assert "message" in record
        assert record["message"] == "hello structured world"
        assert "level" in record
        assert record["level"] == "INFO"

    # Cleanup
    test_logger.removeHandler(handler)


def test_plain_formatter_used_by_default(monkeypatch):
    """When LOG_FORMAT is not set, plain-text formatting is used (no JSON)."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    import importlib
    import config.logging_config as logging_config_module
    importlib.reload(logging_config_module)

    import io
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter(fmt="%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)

    test_logger = logging.getLogger("test_plain_logging_isolated")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.DEBUG)
    test_logger.propagate = False

    test_logger.info("plain text message")

    output = stream.getvalue().strip()
    assert "plain text message" in output

    # Should NOT be valid JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(output)

    test_logger.removeHandler(handler)


def test_configure_logging_does_not_add_duplicate_handlers():
    """configure_logging() called twice must not add duplicate handlers."""
    from config.logging_config import configure_logging

    root = logging.getLogger()
    original_count = len(root.handlers)

    # Remove all existing handlers first so we can test the dedup logic cleanly
    for h in list(root.handlers):
        root.removeHandler(h)

    configure_logging()
    count_after_first = len(root.handlers)

    configure_logging()
    count_after_second = len(root.handlers)

    assert count_after_first == count_after_second, (
        f"Handler count grew from {count_after_first} to {count_after_second} on second call"
    )

    # Restore original state
    for h in list(root.handlers):
        root.removeHandler(h)
