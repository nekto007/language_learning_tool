"""A PostgreSQL fixture must leave foreign keys available to SQLite DDL."""

from flask import Flask
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.auth.models import User
from app.utils.db import db


def _referrer_fk(engine: Engine) -> dict:
    return next(constraint for constraint in inspect(engine).get_foreign_keys('users')
                if constraint['constrained_columns'] == ['referred_by_id'])


def test_schema_fixture_preserves_referrer_cascade_across_dialects(app: Flask) -> None:
    assert _referrer_fk(db.engine)['options']['ondelete'] == 'SET NULL'
    sqlite = create_engine('sqlite://')
    try:
        with sqlite.begin() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys = ON')
            User.__table__.create(connection)
        constraint = _referrer_fk(sqlite)
        assert constraint['referred_table'] == 'users'
        assert constraint['referred_columns'] == ['id']
        assert constraint['options']['ondelete'] == 'SET NULL'
    finally:
        sqlite.dispose()
