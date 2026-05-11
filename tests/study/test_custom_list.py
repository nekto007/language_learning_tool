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


# ---------------------------------------------------------------------------
# _parse_bulk_import unit tests (Task 70)
# ---------------------------------------------------------------------------

class TestParseBulkImport:
    """Unit tests for the _parse_bulk_import helper."""

    def _parse(self, text: str):
        from app.study.routes import _parse_bulk_import
        return _parse_bulk_import(text)

    def test_dash_delimiter(self):
        pairs = self._parse('apple - яблоко')
        assert pairs == [('apple', 'яблоко')]

    def test_pipe_delimiter(self):
        pairs = self._parse('book|книга')
        assert pairs == [('book', 'книга')]

    def test_multiple_lines(self):
        text = 'apple - яблоко\nbook - книга\nrun|бежать'
        pairs = self._parse(text)
        assert len(pairs) == 3
        assert pairs[0] == ('apple', 'яблоко')
        assert pairs[2] == ('run', 'бежать')

    def test_blank_lines_skipped(self):
        text = 'apple - яблоко\n\n\nbook - книга'
        pairs = self._parse(text)
        assert len(pairs) == 2

    def test_malformed_lines_skipped(self):
        text = 'apple\nbook - книга\njust_a_word'
        pairs = self._parse(text)
        assert pairs == [('book', 'книга')]

    def test_whitespace_stripped(self):
        pairs = self._parse('  apple  -  яблоко  ')
        assert pairs == [('apple', 'яблоко')]

    def test_empty_text_returns_empty(self):
        assert self._parse('') == []

    def test_only_blank_lines(self):
        assert self._parse('\n\n\n') == []


# ---------------------------------------------------------------------------
# Route: POST /study/lists/<id> action=import (Task 70)
# ---------------------------------------------------------------------------

class TestCustomListImport:
    def test_import_adds_words(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'cat - кошка\ndog - собака'},
        )
        entries = CustomWordListEntry.query.filter_by(list_id=lst.id).all()
        words = {e.word for e in entries}
        assert 'cat' in words
        assert 'dog' in words

    def test_import_correct_count(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'cat - кошка\ndog - собака\nbird - птица'},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        assert 'Добавлено 3' in html
        assert 'пропущено 0' in html

    def test_import_duplicates_skipped(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'cat', 'кошка')
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'cat - кошка\ndog - собака'},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        assert 'Добавлено 1' in html
        assert 'пропущено 1' in html
        count = CustomWordListEntry.query.filter_by(list_id=lst.id, word='cat').count()
        assert count == 1

    def test_import_malformed_lines_ignored(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'cat - кошка\njust_a_word\ndog - собака'},
            follow_redirects=True,
        )
        count = CustomWordListEntry.query.filter_by(list_id=lst.id).count()
        assert count == 2

    def test_import_empty_text_shows_error(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': ''},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        assert 'Ничего не добавлено' in html

    def test_import_pipe_delimiter(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'run|бежать\nfly|летать'},
        )
        count = CustomWordListEntry.query.filter_by(list_id=lst.id).count()
        assert count == 2

    def test_import_dedup_within_batch(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.post(
            f'/study/lists/{lst.id}',
            data={'action': 'import', 'import_text': 'cat - кошка\ncat - кот'},
            follow_redirects=True,
        )
        count = CustomWordListEntry.query.filter_by(list_id=lst.id, word='cat').count()
        assert count == 1

    def test_import_template_shows_import_toggle(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        html = resp.get_data(as_text=True)
        assert 'Импортировать список' in html


# ---------------------------------------------------------------------------
# Route: GET /study/lists/<id>/study (Task 71)
# ---------------------------------------------------------------------------

def _make_collection_word(db_session, english_word: str, russian_word: str = 'перевод'):
    from app.words.models import CollectionWords
    word = CollectionWords(english_word=english_word, russian_word=russian_word)
    db_session.add(word)
    db_session.commit()
    return word


class TestCustomListStudy:
    def test_study_route_creates_card_directions(self, app, db_session, test_user, client):
        from app.study.models import UserWord, UserCardDirection
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'apple', 'яблоко')
        cw = _make_collection_word(db_session, 'apple', 'яблоко')
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}/study', follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers['Location']
        assert 'source=custom_list' in location
        assert f'list_id={lst.id}' in location
        user_word = UserWord.query.filter_by(user_id=test_user.id, word_id=cw.id).first()
        assert user_word is not None
        directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
        assert len(directions) == 2
        direction_types = {d.direction for d in directions}
        assert 'eng-rus' in direction_types
        assert 'rus-eng' in direction_types

    def test_study_route_existing_cards_not_duplicated(self, app, db_session, test_user, client):
        from app.study.models import UserWord, UserCardDirection
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'apple', 'яблоко')
        cw = _make_collection_word(db_session, 'apple')
        user_word = UserWord.get_or_create(test_user.id, cw.id)
        db_session.add(UserCardDirection(user_word.id, 'eng-rus'))
        db_session.add(UserCardDirection(user_word.id, 'rus-eng'))
        db_session.commit()
        _login(client, test_user)
        client.get(f'/study/lists/{lst.id}/study')
        cards = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
        assert len(cards) == 2

    def test_study_route_403_for_other_user_list(self, app, db_session, test_user, client):
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
        resp = client.get(f'/study/lists/{lst.id}/study')
        assert resp.status_code == 403

    def test_study_route_empty_list_redirects_back(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}/study', follow_redirects=False)
        assert resp.status_code == 302
        assert f'/lists/{lst.id}' in resp.headers['Location']

    def test_study_route_no_matching_words_redirects_back(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'nonexistentword12345', 'перевод')
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}/study', follow_redirects=False)
        assert resp.status_code == 302
        assert f'/lists/{lst.id}' in resp.headers['Location']

    def test_study_button_shown_when_entries_exist(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _make_entry(db_session, lst.id, 'apple', 'яблоко')
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        html = resp.get_data(as_text=True)
        assert 'Учить список' in html

    def test_study_button_not_shown_on_empty_list(self, app, db_session, test_user, client):
        lst = _make_list(db_session, test_user.id)
        _login(client, test_user)
        resp = client.get(f'/study/lists/{lst.id}')
        html = resp.get_data(as_text=True)
        assert 'Учить список' not in html
