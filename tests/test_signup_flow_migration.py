"""Apply and reverse the release migration in an isolated PostgreSQL schema."""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.utils.db import db


def test_signup_migration_round_trip(app):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Production migration is verified against PostgreSQL')
    schema = 'signup_migration_' + uuid4().hex[:12]
    path = Path(__file__).parents[1] / 'migrations/versions/20261115_landing_signup_flow.py'
    spec = importlib.util.spec_from_file_location('signup_release_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
            connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            inspector = inspect(connection)
            assert set(inspector.get_table_names(schema=schema)) == {'users', 'landing_visits', 'welcome_email_queue'}
            queue = {c['name']: c for c in inspector.get_columns('welcome_email_queue', schema=schema)}
            assert not queue['user_id']['nullable']
            assert inspector.get_unique_constraints('welcome_email_queue', schema=schema)[0]['column_names'] == ['user_id']
            assert inspector.get_foreign_keys('welcome_email_queue', schema=schema)[0]['options']['ondelete'] == 'CASCADE'
            assert inspector.get_foreign_keys('landing_visits', schema=schema)[0]['options']['ondelete'] == 'SET NULL'
            connection.execute(text('INSERT INTO users VALUES (1)'))
            connection.execute(text("INSERT INTO welcome_email_queue(user_id, available_at) VALUES (1, now())"))
            assert connection.execute(text('SELECT status, attempts FROM welcome_email_queue')).one() == ('pending', 0)
            migration.downgrade()
            assert inspect(connection).get_table_names(schema=schema) == ['users']
        finally:
            transaction.rollback()  # Includes the isolated schema; shared test tables are untouched.
