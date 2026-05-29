"""Tests for the /admin/word-contrasts UI."""
import uuid

import pytest

from app.utils.db import db
from app.words.models import CollectionWords, WordContrast


@pytest.fixture
def public_word_pair(db_session):
    suffix = uuid.uuid4().hex[:6]
    a = CollectionWords(
        english_word=f'admA {suffix}', russian_word='первое',
        item_type='word', level='A1', ipa_transcription='x',
    )
    b = CollectionWords(
        english_word=f'admB {suffix}', russian_word='второе',
        item_type='word', level='A1', ipa_transcription='y',
    )
    db_session.add_all([a, b])
    db_session.commit()
    return a, b


@pytest.mark.smoke
def test_index_returns_200_for_admin(admin_client, db_session):
    response = admin_client.get('/admin/word-contrasts')
    assert response.status_code == 200
    assert 'Контрастные пары'.encode('utf-8') in response.data


def test_index_rejects_non_admin(client):
    response = client.get('/admin/word-contrasts')
    assert response.status_code in (302, 401, 403)


def test_create_pair(admin_client, db_session, public_word_pair):
    a, b = public_word_pair
    response = admin_client.post('/admin/word-contrasts/create', data={
        'word_a': a.english_word,
        'word_b': b.english_word,
        'note_ru': '<b>A</b> для одного. <b>B</b> для другого.',
    }, follow_redirects=False)
    assert response.status_code == 302
    pair = WordContrast.query.filter(
        WordContrast.word_a_id.in_([a.id, b.id]),
        WordContrast.word_b_id.in_([a.id, b.id]),
    ).first()
    assert pair is not None
    assert pair.note_ru.startswith('<b>A</b>')
    # Canonical ordering enforced.
    assert pair.word_a_id < pair.word_b_id


def test_create_rejects_missing_word(admin_client, db_session, public_word_pair):
    a, _ = public_word_pair
    response = admin_client.post(
        '/admin/word-contrasts/create',
        data={
            'word_a': a.english_word, 'word_b': 'no-such-word-zzz',
            'note_ru': 'whatever',
        }, follow_redirects=True,
    )
    assert response.status_code == 200
    assert WordContrast.query.filter_by(word_a_id=a.id).count() == 0


def test_create_rejects_same_word(admin_client, db_session, public_word_pair):
    a, _ = public_word_pair
    response = admin_client.post(
        '/admin/word-contrasts/create',
        data={
            'word_a': a.english_word, 'word_b': a.english_word,
            'note_ru': 'self',
        }, follow_redirects=True,
    )
    assert response.status_code == 200
    assert WordContrast.query.filter_by(word_a_id=a.id, word_b_id=a.id).count() == 0


def test_create_dedupes_existing_pair(admin_client, db_session, public_word_pair):
    a, b = public_word_pair
    low_id, high_id = sorted((a.id, b.id))
    db_session.add(WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='old'))
    db_session.commit()
    admin_client.post('/admin/word-contrasts/create', data={
        'word_a': a.english_word, 'word_b': b.english_word, 'note_ru': 'new',
    }, follow_redirects=True)
    # Still only one row, note unchanged.
    rows = WordContrast.query.filter_by(word_a_id=low_id, word_b_id=high_id).all()
    assert len(rows) == 1
    assert rows[0].note_ru == 'old'


def test_update_note(admin_client, db_session, public_word_pair):
    a, b = public_word_pair
    low_id, high_id = sorted((a.id, b.id))
    pair = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='old note')
    db_session.add(pair)
    db_session.commit()
    response = admin_client.post(
        f'/admin/word-contrasts/{pair.id}/update',
        data={'note_ru': 'updated note via admin'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(pair)
    assert pair.note_ru == 'updated note via admin'


def test_update_rejects_empty_note(admin_client, db_session, public_word_pair):
    a, b = public_word_pair
    low_id, high_id = sorted((a.id, b.id))
    pair = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='kept')
    db_session.add(pair)
    db_session.commit()
    admin_client.post(
        f'/admin/word-contrasts/{pair.id}/update',
        data={'note_ru': '   '}, follow_redirects=True,
    )
    db_session.refresh(pair)
    assert pair.note_ru == 'kept'


def test_delete(admin_client, db_session, public_word_pair):
    a, b = public_word_pair
    low_id, high_id = sorted((a.id, b.id))
    pair = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru='goodbye')
    db_session.add(pair)
    db_session.commit()
    pair_id = pair.id
    response = admin_client.post(
        f'/admin/word-contrasts/{pair_id}/delete', follow_redirects=False,
    )
    assert response.status_code == 302
    assert WordContrast.query.get(pair_id) is None
