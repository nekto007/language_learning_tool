from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.types import JSON, TypeDecorator


class JSONBCompat(TypeDecorator):
    """
    Compatibility wrapper for JSONB that falls back to generic JSON
    when running on non-PostgreSQL backends (e.g., SQLite in tests).
    """

    impl = JSONB
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(JSON())
        return dialect.type_descriptor(JSONB())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


class TSVectorCompat(TypeDecorator):
    """
    Compatibility wrapper for PostgreSQL TSVECTOR to allow SQLite fallbacks.
    """

    impl = TSVECTOR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String())
        return dialect.type_descriptor(TSVECTOR())

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value
