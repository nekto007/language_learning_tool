"""Reading protocol, publication rights and completion using artificial data."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.api.test_native_full_integration import native_app as native_app, learner
from app.books.models import Book, Chapter, UserChapterProgress
from app.books.short_readings import install_pack, load_pack, PERMISSION, words
from app.utils.db import db
from tests.short_reading_fixtures import write_pack


@pytest.fixture(autouse=True)
def artificial_pack(tmp_path, monkeypatch):
    monkeypatch.setattr('app.books.short_readings.PACK', write_pack(tmp_path / 'fixture.json'))


@pytest.fixture
def account(native_app):
    user, headers = learner(native_app)
    user.onboarding_level = 'A1'
    user.onboarding_completed = True
    db.session.commit()
    return user, headers


@pytest.fixture
def pack(native_app):
    install_pack(apply=True)
    return Book.query.filter(Book.slug.like('llt-a1-reading-%')).order_by(Book.slug).all()


def test_pack_schema_accepts_gradual_lengths_and_question_evidence():
    import re
    pack = load_pack()
    lengths = [len(words(x['text'])) for x in pack['items']]
    assert len(pack['items']) == 15
    assert lengths[0] < 60 and lengths[-1] > 150
    assert sum(len(x['reading']['questions']) for x in pack['items']) == 43
    for item in pack['items']:
        for question in item['reading']['questions']:
            for evidence in re.findall('«([^»]+)»', question['explanation']):
                def normalize(text):
                    return ' '.join(words(text.casefold()))
                assert normalize(evidence) in normalize(item['text']), (item['slug'], question['id'])


def test_installer_is_dry_by_default_and_preserves_real_progress(native_app):
    count = Book.query.count()
    install_pack()
    assert Book.query.count() == count
    install_pack(apply=True)
    first = Book.query.filter_by(slug='llt-a1-reading-01').one()
    user, _ = learner(native_app)
    chapter = Chapter.query.filter_by(book_id=first.id).one()
    row = UserChapterProgress(user_id=user.id, chapter_id=chapter.id, offset_pct=0.5)
    db.session.add(row)
    db.session.commit()
    result = install_pack(apply=True)
    assert not result['created'] and len(result['unchanged']) == 15
    assert db.session.get(UserChapterProgress, (user.id, chapter.id)).offset_pct == 0.5
    assert first.rights_status == 'licensed' and first.is_free_access
    assert first.permission_document == PERMISSION
    assert all(book.chapters_cnt == 1 for book in Book.query.filter(Book.slug.like('llt-a1-reading-%')))


def test_install_refuses_to_overwrite_edits_and_preserves_admin_unpublication(native_app, pack):
    first = pack[0]
    chapter = Chapter.query.filter_by(book_id=first.id).one()
    old = chapter.text_raw
    chapter.text_raw = 'Edited by the publisher.'
    db.session.commit()
    with pytest.raises(ValueError, match='Existing material differs'):
        install_pack(apply=True)
    assert chapter.text_raw == 'Edited by the publisher.'
    chapter.text_raw = old
    first.is_published = False
    db.session.commit()
    install_pack(apply=True)
    assert not first.is_published
    first.is_published = True
    db.session.commit()


def test_catalogue_is_available_without_optional_books_module_and_is_ordered(native_app, account, pack):
    _, headers = account
    response = native_app.test_client().get('/api/books/catalog?level=A1', headers=headers)
    assert response.status_code == 200
    rows = [row for row in response.json['books'] if row['id'] in {b.id for b in pack}]
    assert [row['reading']['order'] for row in rows] == list(range(1, 16))
    assert all('questions' not in row['reading'] and 'glossary' not in row['reading'] for row in rows)
    first = pack[0]
    response = native_app.test_client().get(f'/api/books/{first.id}/chapters/1', headers=headers)
    assert response.status_code == 200
    assert response.json['reading']['questions'][0]['correct_option'] == 'b'
    assert response.json['reading']['glossary']
    detail = native_app.test_client().get(f'/api/books/{first.id}', headers=headers)
    assert detail.status_code == 200 and detail.json['reading']['format'] == 'short_text'
    assert detail.json['words_total'] == 44


def test_free_access_does_not_bypass_expiry_drafts_or_anonymous_auth(native_app, account, pack):
    from app.books.access import can_user_access_book, accessible_books_filter
    user, headers = account
    book = pack[1]
    client = native_app.test_client()
    assert can_user_access_book(user, book)
    assert client.get(f'/api/books/{book.id}/chapters/1').status_code == 401
    book.expiration_date = datetime.now(UTC).date() - timedelta(days=1)
    db.session.commit()
    assert not can_user_access_book(user, book)
    assert book.id not in {b.id for b in Book.query.filter(accessible_books_filter(user))}
    assert client.get(f'/api/books/{book.id}/chapters/1', headers=headers).status_code == 403
    book.expiration_date = None
    book.is_published = False
    db.session.commit()
    assert client.get(f'/api/books/{book.id}/chapters/1', headers=headers).status_code == 404
    book.is_published = True
    book.is_free_access = False
    db.session.commit()
    assert client.get(f'/api/books/{book.id}/chapters/1', headers=headers).status_code == 403
    book.is_free_access = True
    db.session.commit()
    anon = SimpleNamespace(is_authenticated=False, is_admin=False)
    assert not can_user_access_book(anon, book)
    assert Book.query.filter(accessible_books_filter(anon)).count() == 0


def test_finishing_short_text_credits_reading_without_timer_and_not_as_a_book(native_app, account, pack):
    from app.books.reading_session import get_book_reading_seconds_today, is_daily_reading_target_met_today
    from app.books.progress import get_book_completion_state
    from app.achievements.models import UserStatistics, StreakEvent
    from app.daily_plan.items.reading import build_reading_item
    user, headers = account
    first = pack[0]
    chapter = Chapter.query.filter_by(book_id=first.id).one()
    client = native_app.test_client()
    response = client.post('/api/native/books/select', headers=headers, json={'book_id': first.id})
    assert response.status_code == 200, response.json
    item = build_reading_item(user.id, db)
    assert item.data['completion_mode'] == 'short_reading' and item.data['goal_texts'] == 1
    assert 'мин' not in item.subtitle
    assert get_book_reading_seconds_today(user.id, first.id, db) == 0
    response = client.patch('/api/native/reading/progress', headers=headers,
                            json={'book_id': first.id, 'chapter_id': chapter.id, 'offset_pct': 1.0})
    assert response.status_code == 200, response.json
    assert response.json['book_completed'] and response.json['reading_slot_completed'], {'response': response.json, 'events': [(r.event_type, r.details) for r in StreakEvent.query.filter_by(user_id=user.id)]}
    assert is_daily_reading_target_met_today(user.id, first.id, db)
    assert get_book_completion_state(user.id, first.id, db)['is_completed']
    assert build_reading_item(user.id, db).completed
    stats = UserStatistics.query.filter_by(user_id=user.id).one()
    assert stats.total_books_completed == 0
    events = StreakEvent.query.filter_by(user_id=user.id).count()
    repeated = client.patch('/api/native/reading/progress', headers=headers,
                            json={'book_id': first.id, 'chapter_id': chapter.id, 'offset_pct': 1.0})
    assert repeated.status_code == 200
    assert StreakEvent.query.filter_by(user_id=user.id).count() == events
    assert stats.total_books_completed == 0


def test_invalid_questions_are_rejected_before_install(tmp_path):
    pack = deepcopy(load_pack())
    pack['items'][0]['reading']['questions'][0]['correct_option'] = 'missing'
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(pack))
    with pytest.raises(ValueError, match='Invalid formative question'):
        load_pack(path)


def test_cli_accepts_explicit_external_pack_and_keeps_dry_run(native_app, tmp_path, monkeypatch):
    path = write_pack(tmp_path / 'external.json')
    monkeypatch.setattr('app.books.short_readings.PACK', tmp_path / 'absent-default.json')
    count = Book.query.count()
    runner = native_app.test_cli_runner()
    result = runner.invoke(args=['a1-readings-install', '--pack', str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['applied'] is False
    assert Book.query.count() == count
    result = runner.invoke(args=['a1-readings-install', '--pack', str(path), '--apply'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['applied'] is True


def test_missing_private_pack_has_actionable_cli_error(native_app, monkeypatch, tmp_path):
    monkeypatch.setattr('app.books.short_readings.PACK', tmp_path / 'absent.json')
    result = native_app.test_cli_runner().invoke(args=['a1-readings-install'])
    assert result.exit_code != 0
    assert 'Copy it separately and use --pack PATH' in result.output


def test_migration_adds_safe_defaults_and_can_rollback():
    path = Path(__file__).resolve().parents[2] / 'migrations/versions/20261122_a1_short_readings.py'
    spec = importlib.util.spec_from_file_location('short_reading_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE book (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO book VALUES (1)'))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.execute(sa.text('SELECT is_free_access, reading FROM book')).first() == (0, None)
        module.downgrade()
        assert [c['name'] for c in sa.inspect(connection).get_columns('book')] == ['id']


def test_waiting_for_time_does_not_complete_short_reading(native_app, account, pack):
    from app.books.reading_session import UserReadingSession, get_book_reading_seconds_today, is_daily_reading_target_met_today
    from app.daily_plan.items.reading import build_reading_item
    user, headers = account
    book = pack[2]
    chapter = Chapter.query.filter_by(book_id=book.id).one()
    client = native_app.test_client()
    assert client.post('/api/native/books/select', headers=headers, json={'book_id': book.id}).status_code == 200
    now = datetime.now(UTC)
    db.session.add(UserReadingSession(user_id=user.id, chapter_id=chapter.id,
        started_at=now-timedelta(minutes=10), ended_at=now, start_offset_pct=0, offset_delta=0.2))
    db.session.commit()
    assert get_book_reading_seconds_today(user.id, book.id, db) >= 300
    assert not is_daily_reading_target_met_today(user.id, book.id, db)
    item = build_reading_item(user.id, db)
    assert not item.completed and not item.data['gate_reached']
