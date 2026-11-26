"""Aliases keep their own retry history and only add reader contexts."""
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from flask import Flask, g
from sqlalchemy.orm import Session

from app.achievements.models import UserStatistics
from app.api.native_reader import _context_key
from app.books.models import Book, Chapter
from app.modules.migrations import seed_initial_modules
from app.modules.service import ModuleService
from app.study.models import NativeReaderVocabulary, QuizDeckWord, UserCardDirection, UserWord
from app.words.models import CollectionWords
from tests.api.test_course_receipt_expiry import sign_in
from tests.api.test_native_full_integration import learner
from tests.api.test_native_reader import sync, word
from tests.api.test_web_reader_selection import selection


@pytest.fixture
def account(app: Flask, db_session: Session) -> tuple[Any, dict]:
    seed_initial_modules()
    user, headers = learner(app)
    user.onboarding_completed = True
    user.onboarding_level = 'A1'
    db_session.commit()
    ModuleService.grant_default_modules_to_user(user.id)
    return user, headers


def place(chapter: int, book_id: int, *, paragraph: int = 0, **fields: Any) -> dict:
    sentence = f'This passage is in chapter {chapter}.'
    value = word(sentence=sentence, **fields)
    value['contexts'] = [{
        'sentence': sentence, 'date': value['addedAt'],
        'location': {'chapter': chapter, 'bookID': book_id, 'paragraph': paragraph, 'title': 'Two passages'},
    }]
    return value


def chapters(card: dict) -> set[int]:
    return {context['location']['chapter'] for context in card['contexts']}


@pytest.mark.parametrize('order', [(1, 2), (2, 1)])
def test_distinct_input_uuids_same_revision_keep_both_chapters_and_retry(
    app: Flask, db_session: Session, account: tuple[Any, dict], order: tuple[int, int],
) -> None:
    user, headers = account
    client = app.test_client()
    book = Book(title='Two passages', author='Fixture', rights_status='public_domain',
                is_published=True, chapters_cnt=2)
    db_session.add(book)
    db_session.flush()
    db_session.add_all([
        Chapter(book=book, chap_num=i, title=f'Part {i}', text_raw=f'This passage is in chapter {i}.', words=6)
        for i in order
    ])
    dictionary = CollectionWords(english_word='reader' + uuid4().hex, russian_word='test translation')
    db_session.add(dictionary)
    db_session.flush()
    device = str(uuid4())
    a, b = [place(i, book.id, lemma=dictionary.english_word) for i in order]
    db_session.commit()
    first = sync(client, headers, [a], device)
    assert first.status_code == 200
    only, = first.json['words']
    owned = UserWord.query.filter_by(user_id=user.id, word_id=dictionary.id).one()
    cards = UserCardDirection.query.filter_by(user_word_id=owned.id).all()
    assert cards
    for card in cards:
        card.state, card.interval, card.repetitions = 'review', 17, 9
        card.first_reviewed = datetime.now(UTC)
    stats = UserStatistics(user_id=user.id, total_xp=137, current_level=2)
    db_session.add(stats)
    db_session.commit()

    b['repetitions'], b['intervalDays'], b['status'] = 99, 34, 'known'
    reply = sync(client, headers, [b], device)
    assert reply.status_code == 200
    assert reply.json['aliases'] == {b['id']: a['id']}
    assert reply.json['accepted'] == {b['id']: 1}
    assert reply.json['cursor'] == only['serverRevision'] + 1 == 2
    merged, = reply.json['words']
    assert chapters(merged) == {1, 2}
    assert {k: merged[k] for k in ('repetitions', 'intervalDays', 'status', 'dueAt', 'addedAt', 'updatedAt')} == {
        k: only[k] for k in ('repetitions', 'intervalDays', 'status', 'dueAt', 'addedAt', 'updatedAt')
    }
    for value in (b, a, b):
        repeated = sync(client, headers, [value], device)
        assert repeated.json['words'] == [merged]
        assert repeated.json['cursor'] == 2
    assert sync(client, headers, [], str(uuid4())).json['words'] == [merged]

    state = db_session.get(NativeReaderVocabulary, user.id)
    stored, = state.payload['words'].values()
    entry = db_session.get(QuizDeckWord, stored['_deckWord'])
    assert set(entry.custom_sentences.split('\n\n')) == {f'This passage is in chapter {i}.' for i in order}
    for card in cards:
        db_session.refresh(card)
        assert (card.state, card.interval, card.repetitions) == ('review', 17, 9)
    db_session.refresh(stats)
    assert stats.total_xp == 137

    browser = app.test_client()
    sign_in(browser, app, user)
    for context in merged['contexts']:
        g.pop('_login_user', None)
        target = browser.get(f"/words/reading-vocabulary/{a['id']}/context/{_context_key(context)}")
        assert target.status_code == 302
        assert parse_qs(urlsplit(target.location).query)['chapter'] == [str(context['location']['chapter'])]
        assert browser.get(target.location).status_code == 200

    canonical = deepcopy(merged)
    canonical.update(translation='A revised meaning', revision=2)
    changed = sync(client, headers, [canonical], device)
    assert changed.status_code == 200
    assert changed.json['words'][0]['translation'] == 'A revised meaning'
    assert changed.json['cursor'] == 3
    old_alias = sync(client, headers, [b], device)
    assert old_alias.json['aliases'] == {b['id']: a['id']}
    assert old_alias.json['cursor'] == 3
    assert chapters(old_alias.json['words'][0]) == {1, 2}

    other, foreign = learner(app)
    ModuleService.grant_default_modules_to_user(other.id)
    assert sync(client, foreign, [], device).json['words'] == []
    independent = sync(client, foreign, [b], device)
    assert independent.json['words'][0]['id'] == b['id']
    assert chapters(independent.json['words'][0]) == {order[1]}


def test_legacy_high_water_and_deleted_aliases_keep_history_without_resurrection(
    app: Flask, db_session: Session, account: tuple[Any, dict],
) -> None:
    user, headers = account
    client = app.test_client()
    device = str(uuid4())
    a, b, delayed = [place(i, 701) for i in (1, 2, 3)]
    first = sync(client, headers, [a], device).json['words'][0]
    state = db_session.get(NativeReaderVocabulary, user.id)
    stored = state.payload['words'][a['id']]
    assert stored['_receipts'] == {device: 1} and '_aliasReceipts' not in stored

    old_replay = deepcopy(a)
    old_replay['id'] = str(uuid4())
    replayed = sync(client, headers, [old_replay], device).json
    assert replayed['aliases'] == {old_replay['id']: a['id']}
    assert replayed['cursor'] == 1
    assert replayed['words'] == [first]
    b_result = sync(client, headers, [b], device).json
    assert chapters(b_result['words'][0]) == {1, 2}
    removed = deepcopy(b_result['words'][0])
    removed.update(deletedAt=a['updatedAt'], revision=2)
    assert sync(client, headers, [removed], device).json['cursor'] == 3
    for stale in (b, delayed, delayed, old_replay):
        result = sync(client, headers, [stale], device).json
        assert result['aliases'] == {stale['id']: a['id']}
        assert result['cursor'] == 3 and result['words'][0]['deletedAt']
        assert chapters(result['words'][0]) == {1, 2}
    cold = sync(client, headers, [], str(uuid4())).json['words']
    assert len(cold) == 1 and cold[0]['deletedAt']
    removed.pop('deletedAt')
    removed['revision'] = 3
    undo = sync(client, headers, [removed], device).json
    assert not undo['words'][0].get('deletedAt')
    assert undo['cursor'] == 4
    assert chapters(undo['words'][0]) == {1, 2}
    assert sync(client, headers, [delayed], device).json['cursor'] == 4


def test_hundred_alias_limit_does_not_evict_retries_or_prevent_later_edit(
    app: Flask, db_session: Session, account: tuple[Any, dict],
) -> None:
    user, headers = account
    client = app.test_client()
    device = str(uuid4())
    original = place(1, 701)
    sync(client, headers, [original], device)
    aliases = [place(2, 701, paragraph=i) for i in range(100)]
    full = sync(client, headers, aliases, device)
    assert full.status_code == 200 and len(full.json['aliases']) == 100
    only, = full.json['words']
    assert len(only['contexts']) == 30
    version = full.json['cursor']
    updated = only | {'revision': 2, 'translation': 'New canonical meaning'}
    rejected = sync(client, headers, [deepcopy(only) | {'revision': 2, 'status': 'known'}, place(2, 701)], device)
    assert rejected.status_code == 422
    assert sync(client, headers, [], device).json['words'] == [only]

    repeated = sync(client, headers, [aliases[0]], device)
    assert repeated.json['aliases'] == {aliases[0]['id']: only['id']}
    assert repeated.json['cursor'] == version
    assert repeated.json['words'] == [only]
    changed = sync(client, headers, [updated], device)
    assert changed.status_code == 200 and changed.json['words'][0]['translation'] == 'New canonical meaning'
    assert changed.json['cursor'] == version + 1
    known = sync(client, headers, [aliases[0] | {'revision': 2}], device)
    assert known.status_code == 200 and known.json['aliases'] == {aliases[0]['id']: only['id']}
    state = db_session.get(NativeReaderVocabulary, user.id)
    assert len(state.payload['words'][only['id']]['_aliasReceipts']) == 100


def test_explicit_web_selection_can_add_a_removed_expression_again(
    app: Flask, db_session: Session, account: tuple[Any, dict],
) -> None:
    user, bearer = account
    book = Book(title='Two passages', author='Fixture', rights_status='public_domain',
                is_published=True, chapters_cnt=1)
    chapter = Chapter(book=book, chap_num=1, title='Part one', text_raw='They stepped aside.', words=3)
    db_session.add(chapter)
    db_session.commit()
    web = app.test_client()
    csrf = sign_in(web, app, user)
    path = f'/words/reading-vocabulary/selection/{book.id}/1'
    data = selection(chapter, 0, 'stepped aside') | {'translation': 'test translation'}
    assert web.post(path, json=data, headers=csrf).status_code == 200
    native = app.test_client()
    device = str(uuid4())
    only, = sync(native, bearer, [], device).json['words']
    g.pop('_login_user', None)
    removed = web.post(f"/words/reading-vocabulary/{only['id']}", data={'status': 'remove'}, headers=csrf)
    assert removed.status_code == 302
    assert sync(native, bearer, [], device).json['words'][0]['deletedAt']
    g.pop('_login_user', None)
    added = web.post(path, json=data, headers=csrf)
    assert added.status_code == 200 and added.json['review_url']
    cards = sync(native, bearer, [], device).json['words']
    assert len(cards) == 2
    assert [card['id'] for card in cards if card.get('deletedAt')] == [only['id']]
    fresh, = [card for card in cards if not card.get('deletedAt')]
    assert fresh['id'] != only['id'] and fresh['english'] == 'stepped aside'
