"""
Logging configuration for the application.

When the LOG_FORMAT environment variable is set to "json", the root logger
uses pythonjsonlogger.jsonlogger.JsonFormatter so every log record is emitted
as a single-line JSON object.  In all other cases plain-text formatting is used.

Usage (called once inside create_app()):
    from config.logging_config import configure_logging
    configure_logging()
"""
import logging
import os


def configure_logging() -> None:
    """Configure root logger format based on LOG_FORMAT env var."""
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_format = os.environ.get("LOG_FORMAT", "").lower()

    root_logger = logging.getLogger()

    # Avoid adding duplicate handlers when called multiple times (e.g. in tests)
    if root_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setLevel(log_level)

    if log_format == "json":
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore[import]

            class _AppJsonFormatter(jsonlogger.JsonFormatter):
                def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
                    super().add_fields(log_record, record, message_dict)
                    log_record.setdefault("level", record.levelname)
                    log_record.setdefault("logger", record.name)

            formatter: logging.Formatter = _AppJsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s"
            )
        except ImportError:  # pragma: no cover — fallback if package missing
            formatter = logging.Formatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s"
            )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
