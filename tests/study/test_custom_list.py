"""Tests for custom vocabulary list routes (Task 68).

Routes: GET/POST /study/lists, GET/POST /study/lists/<id>
"""
from __future__ import annotations

import uuid

import pytest

from app.study.models import CustomWordList, CustomWordListEntry
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _make_list(db_session, user_id: int, name: str = 'Test List') -> CustomWordList:
    word_list = CustomWordList(user_id=user_id, name=name)
    db_session.add(word_list)
    db_session.commit()
    return word_list


def _make_entry(db_session, list_id: int, word: str = 'apple', translation: str = 'яблоко') -> CustomWordListEntry:
    entry = CustomWordListEntry(list_id=list_id, word=word, translation=translation)
    db_session.add(entry)
    db_session.commit()
    return entry


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestCustomWordListModel:
    def test_create_list(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id, 'My Words')
        assert lst.id is not None
        assert lst.user_id == test_user.id
        assert lst.name == 'My Words'
        assert lst.created_at is not None

    def test_add_entry(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id)
        entry = _make_entry(db_session, lst.id, 'cat', 'кошка')
        assert entry.id is not None
        assert entry.list_id == lst.id
        assert entry.word == 'cat'
        assert entry.translation == 'кошка'

    def test_get_entries_for_list(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'dog', 'собака')
        _make_entry(db_session, lst.id, 'cat', 'кошка')
        entries = lst.entries.all()
        assert len(entries) == 2

    def test_get_entries_empty_list(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id)
        assert lst.entries.count() == 0

    def test_repr_list(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id, 'Repr Test')
        assert 'CustomWordList' in repr(lst)
        assert 'Repr Test' in repr(lst)

    def test_repr_entry(self, app, db_session, test_user):
        lst = _make_list(db_session, test_user.id)
        entry = _make_entry(db_session, lst.id, 'book', 'книга')
        assert 'CustomWordListEntry' in repr(entry)
        assert 'book' in repr(entry)


# ---------------------------------------------------------------------------
# Route: GET /study/lists
# ---------------------------------------------------------------------------

class TestCustomListsGet:
    def test_get_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/lists')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, app, db_session, client):
        resp = client.get('/study/lists')
        assert resp.status_code in (302, 401, 403)

    def test_empty_state_shows_no_lists_message(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/lists')
        html = resp.get_data(as_text=True)
        assert 'Пока нет списков' in html

    def test_existing_list_shown(self, app, db_session, test_user, client):
        _make_list(db_session, test_user.id, 'My Vocab')
        _login(client, test_user)
        resp = client.get('/study/lists')
        html = resp.get_data(as_text=True)
        assert 'My Vocab' in html

    def test_other_user_list_not_shown(self, app, db_session, test_user, client):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        _make_list(db_session, other.id, 'Other Secret List')
        _login(client, test_user)
        resp = client.get('/study/lists')
        html = resp.get_data(as_text=True)
        assert 'Other Secret List' not in html


# ---------------------------------------------------------------------------
# Route: POST /study/lists — create list
# ---------------------------------------------------------------------------

class TestCustomListsCreate:
    def test_create_list_redirects_to_detail(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post('/study/lists', data={'name': 'New List'}, follow_redirects=False)
        assert resp.status_code == 302
        assert '/lists/' in resp.headers['Location']

    def test_create_list_saves_to_db(self, app, db_session, test_user, client):
        _login(client, test_user)
        client.post('/study/lists', data={'name': 'Saved List'})
        lst = CustomWordList.query.filter_by(user_id=test_user.id, name='Saved List').first()
        assert lst is not None

    def test_create_list_empty_name_redirects_back(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post('/study/lists', data={'name': ''}, follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Введите название списка' in html


# ---------------------------------------------------------------------------
# Route: GET /study/lists/<id>
# ---------------------------------------------------------------------------

class TestCustomListDetailGet:
    def test_get_returns_200(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        assert resp.status_code == 200

    def test_403_for_other_user_list(self, app, db_session, test_user, client):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        lst = _make_list(db_session, other.id, 'Private')
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        assert resp.status_code == 403

    def test_404_for_nonexistent_list(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/lists/99999999')
        assert resp.status_code == 404

    def test_entries_shown(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'river', 'река')
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        html = resp.get_data(as_text=True)
        assert 'river' in html
        assert 'река' in html

    def test_empty_list_shows_empty_message(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        html = resp.get_data(as_text=True)
        assert 'Список пуст' in html


# ---------------------------------------------------------------------------
# Route: POST /study/lists/<id> — add word
# ---------------------------------------------------------------------------

class TestCustomListDetailAddWord:
    def test_add_word_saves_entry(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'add', 'word': 'tree', 'translation': 'дерево'},
        )
        entry = CustomWordListEntry.query.filter_by(list_id=lst.id, word='tree').first()
        assert entry is not None
        assert entry.translation == 'дерево'

    def test_add_duplicate_word_idempotent(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'stone', 'камень')
        _login(client, test_user)
        client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'add', 'word': 'stone', 'translation': 'камень'},
        )
        count = CustomWordListEntry.query.filter_by(list_id=lst.id, word='stone').count()
        assert count == 1

    def test_add_word_missing_translation_shows_error(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'add', 'word': 'cloud', 'translation': ''},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        assert 'Укажите слово и перевод' in html

    def test_add_word_403_for_other_user_list(self, app, db_session, test_user, client):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        lst = _make_list(db_session, other.id, 'Other Private')
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'add', 'word': 'wind', 'translation': 'ветер'},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Route: POST /study/lists/<id> — remove word
# ---------------------------------------------------------------------------

class TestCustomListDetailRemoveWord:
    def test_remove_word_deletes_entry(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        entry = _make_entry(db_session, lst.id, 'fire', 'огонь')
        _login(client, test_user)
        client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'remove', 'entry_id': str(entry.id)},
        )
        remaining = CustomWordListEntry.query.get(entry.id)
        assert remaining is None

    def test_remove_wrong_list_entry_ignored(self, app, db_session, test_user, client):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass123')
        db_session.add(other)
        db_session.commit()
        other_list = _make_list(db_session, other.id, 'Other List')
        other_entry = _make_entry(db_session, other_list.id, 'ice', 'лёд')

        my_list = _make_list(db_session, test_user.id)
        _login(client, test_user)
        # Try to remove other user's entry via my list's URL
        resp = client.post(
            f'/study/lists/{my_list.id}',
            data={'action': 'remove', 'entry_id': str(other_entry.id)},
        )
        # Entry should still exist (not deleted)
        still_there = CustomWordListEntry.query.get(other_entry.id)
        assert still_there is not None
