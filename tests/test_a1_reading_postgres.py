"""PostgreSQL schema and browser reader checks for the original A1 pack."""

import importlib.util
import re
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.books.models import Book, Chapter, UserChapterProgress
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


def test_web_catalogue_orders_before_pagination_and_uses_reading_progress(app, authenticated_client, test_user, tmp_path):
    ordinary = None
    try:
        install_pack(apply=True, path=write_pack(tmp_path / 'fixture.json'))
        materials = Book.query.filter(Book.slug.like('llt-a1-reading-%')).order_by(Book.slug).all()
        for index, book in enumerate(materials, start=1):
            # Alphabetic order deliberately conflicts with learning order.
            book.title = f'Fixture {16-index:02}'
        first_chapter = Chapter.query.filter_by(book_id=materials[0].id).one()
        completed_chapter = Chapter.query.filter_by(book_id=materials[2].id).one()
        db.session.add_all([
            UserChapterProgress(user_id=test_user.id, chapter_id=first_chapter.id, offset_pct=.4),
            UserChapterProgress(user_id=test_user.id, chapter_id=completed_chapter.id, offset_pct=1),
        ])
        ordinary = Book(title='AAA ordinary fixture', author='Test fixture', level='A1',
                        chapters_cnt=1, unique_words=37, rights_status='public_domain', is_published=True)
        db.session.add(ordinary)
        db.session.flush()
        db.session.add(Chapter(book_id=ordinary.id, chap_num=1, title='Fixture chapter', text_raw='Fixture.', words=1))
        db.session.commit()

        def orders(html):
            return [int(n) for n in re.findall(r'data-reading-order="(\d+)"', html)]

        response = authenticated_client.get('/books?level=A1&per_page=5')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert orders(html) == [1, 2, 3, 4, 5]
        cards = re.findall(r'<article\b.*?</article>', html, re.S)
        assert 'Прочитано 40%' in cards[0] and 'width: 40%' in cards[0]
        assert 'Ещё не начат' in cards[1]
        assert 'Текст прочитан' in cards[2] and 'Перечитать' in cards[2]
        assert all('book-cover' not in card and 'глав' not in card for card in cards)
        response = authenticated_client.get('/books?level=A1&per_page=5&page=2')
        assert response.status_code == 200
        assert orders(response.get_data(as_text=True)) == [6, 7, 8, 9, 10]
        response = authenticated_client.get('/books?level=A1&per_page=5&sort=title')
        assert response.status_code == 200
        assert orders(response.get_data(as_text=True)) == [15, 14, 13, 12]
        assert 'sort=title' in response.get_data(as_text=True)
        response = authenticated_client.get('/books?search=AAA%20ordinary')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'book-cover' in html and '0/37' in html
        response = authenticated_client.get('/read')
        assert response.status_code == 200
        # The first short material also appears once under Continue reading.
        html = response.get_data(as_text=True)
        assert orders(html)[-15:] == list(range(1, 16))
    finally:
        db.session.rollback()
        Book.query.filter(Book.slug.like('llt-a1-reading-%')).delete(synchronize_session=False)
        if ordinary and ordinary.id:
            Book.query.filter_by(id=ordinary.id).delete(synchronize_session=False)
        db.session.commit()
