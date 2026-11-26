"""Check the ordinary TOC and the explicit revision projection against real SQL."""

from importlib import import_module
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.orm import scoped_session

from app.books.models import Book, Chapter, chapter_text_revision_cache
from app.utils.db import db

BODY = 'A small lamp burns.\n\nThe quiet room is empty.\n\nThe last line ends here.'


@pytest.fixture
def revision_edition(db_session: scoped_session) -> tuple[Book, Chapter]:
    conn = db_session.connection()
    if conn.dialect.name != 'postgresql':
        pytest.skip('Confirmed revisions use PostgreSQL transactions')
    # Fixtures start from create_all. Recreate just these objects through the actual migration.
    conn.exec_driver_sql('DROP TABLE chapter_text_revision_cache')
    conn.exec_driver_sql('ALTER TABLE chapter DROP COLUMN text_generation')
    migration = import_module('migrations.versions.20261126_chapter_text_revisions')
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    book = Book(slug='chapter-revision-test', title='Synthetic book', author='Fixture', chapters_cnt=2,
                rights_status='licensed', is_free_access=True, allowed_text_percent=25)
    first = Chapter(book=book, chap_num=1, title='First', words=14, text_raw=BODY)
    second = Chapter(book=book, chap_num=2, title='Second', words=4, text_raw='A pale sunset glows.')
    db_session.add_all([first, second])
    db_session.commit()
    return book, first


def test_legacy_and_warm_confirmed_toc_do_not_select_bodies(
    app: Flask, authenticated_client: FlaskClient, revision_edition: tuple[Book, Chapter],
) -> None:
    book, first = revision_edition
    numeric = f'/api/books/{book.id}/chapters'
    slug = f'/api/books/{book.slug}/chapters'
    confirmed = '?text_revisions=confirmed'
    old = authenticated_client.get(numeric).json
    assert old == authenticated_client.get(slug + '?text_revisions=compute').json
    assert set(old[0]) == {'id', 'num', 'title', 'words', 'audio_url'}

    cold = authenticated_client.get(numeric + confirmed)
    assert cold.status_code == 200
    assert cold.headers['Cache-Control'] == 'private, no-store'
    assert [{k: v for k, v in row.items() if k != 'text_revision'} for row in cold.json] == old
    chapter = authenticated_client.get(f'/api/chapters/{first.id}').json['chapter']
    assert chapter['text_revision'] == cold.json[0]['text_revision'] and chapter['text_truncated']

    statements = []

    def capture(
        _conn: Any, _cursor: Any, statement: str, _params: Any, _context: Any, _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        assert authenticated_client.get(numeric).json == old
        assert authenticated_client.get(slug + confirmed).json == cold.json
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert any('chapter_text_revision_cache' in statement for statement in statements)
    assert all('chapter.text_raw' not in statement and 'INSERT' not in statement for statement in statements)


def test_confirmed_recomputes_only_edited_chapter_and_keeps_unchanged_visible_revision(
    authenticated_client: FlaskClient, db_session: scoped_session, revision_edition: tuple[Book, Chapter],
) -> None:
    book, first = revision_edition
    path = f'/api/books/{book.id}/chapters?text_revisions=confirmed'
    previous = authenticated_client.get(path).json
    db_session.refresh(first)
    first.text_raw = BODY.replace('ends', 'goes')
    db_session.commit()
    assert authenticated_client.get(path).json == previous
    cached = chapter_text_revision_cache
    first_id = first.id
    assert db_session.scalar(db.select(cached.c.generation).where(cached.c.chapter_id == first_id)) == 2

    first.text_raw = first.text_raw.replace('small', 'short')
    db_session.commit()
    after = authenticated_client.get(path).json
    assert after[0]['text_revision'] != previous[0]['text_revision']
    assert after[1] == previous[1]

    book.allowed_text_percent = 0
    db_session.commit()
    zero = authenticated_client.get(path).json
    assert zero[0]['text_revision'] == zero[1]['text_revision']
    assert zero[0]['text_revision'] != after[0]['text_revision']
    assert db_session.scalar(db.select(db.func.count()).select_from(cached)) == 2
