"""PostgreSQL schema and browser reader checks for the original A1 pack."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.books.models import Book
from app.books.short_readings import install_pack
from app.utils.db import db
from tests.short_reading_fixtures import write_pack


def migration():
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261122_a1_short_readings.py'
    spec = importlib.util.spec_from_file_location('a1_pg_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module', autouse=True)
def current_test_book_schema(app):
    # The disposable shared test DB uses create_all, which doesn't add columns
    # to older tables left by prior runs. Apply this revision there if needed.
    if 'reading' not in {c['name'] for c in sa.inspect(db.engine).get_columns('book')}:
        with db.engine.begin() as connection:
            module = migration()
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()


def test_postgres_short_reading_schema_roundtrip(app):
    schema = 'a1_reading_test_' + uuid4().hex
    with db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(sa.text('CREATE TABLE book (id INTEGER PRIMARY KEY)'))
            connection.execute(sa.text('INSERT INTO book VALUES (1)'))
            module = migration()
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            assert connection.execute(sa.text('SELECT is_free_access, reading FROM book')).first() == (False, None)
            types = {c['name']: str(c['type']) for c in sa.inspect(connection).get_columns('book', schema=schema)}
            assert types['reading'] == 'JSONB'
            module.downgrade()
            assert [c['name'] for c in sa.inspect(connection).get_columns('book', schema=schema)] == ['id']
        finally:
            transaction.rollback()


def test_web_reader_uses_same_database_practice_and_hides_timer(app, authenticated_client, test_user, tmp_path):
    try:
        install_pack(apply=True, path=write_pack(tmp_path / 'fixture.json'))
        first = Book.query.filter_by(slug='llt-a1-reading-01').one()
        response = authenticated_client.get(f'/read/{first.id}/chapters')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'short-reading-data' in html and 'short-reading-practice' in html
        assert first.reading['questions'][0]['prompt'] in html
        assert 'short_reading.js' in html and 'short-reading-finish' in html
        assert 'id="reading-timer-bar" class="rdr-timer-bar" hidden' in html
        api = authenticated_client.get(f'/api/books/{first.id}/chapters/1')
        assert api.json['reading']['questions'] == first.reading['questions']
    finally:
        # Only installer-owned test rows; no production connection is used.
        Book.query.filter(Book.slug.like('llt-a1-reading-%')).delete(synchronize_session=False)
        db.session.commit()
