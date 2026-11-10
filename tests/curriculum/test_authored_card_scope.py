"""An authored 6/14 split must not expand to the 20-word vocabulary collection."""
from __future__ import annotations

import json
import uuid

import pytest
from flask_login import login_user

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.card_lessons import _lesson_deck_size, _resolve_lesson_deck
from app.srs.constants import DIRECTION_ENG_RUS
from app.study.models import UserCardDirection, UserWord
from app.words.models import Collection, CollectionWordLink, CollectionWords
from tests.conftest import unique_level_code


@pytest.fixture()
def split_deck(db_session):
    suffix = uuid.uuid4().hex[:10]
    level = CEFRLevel(code=unique_level_code(), name='Scope test', order=100)
    collection = Collection(name=f'Authored scope {suffix}')
    db_session.add_all([level, collection])
    db_session.flush()
    module = Module(level_id=level.id, number=1, title='Scope module')
    db_session.add(module)
    db_session.flush()
    words = [CollectionWords(english_word=f'word_{suffix}_{index}', russian_word=f'слово {index}')
             for index in range(20)]
    db_session.add_all(words)
    db_session.flush()
    db_session.add_all([CollectionWordLink(collection_id=collection.id, word_id=word.id) for word in words])
    vocabulary = Lessons(module_id=module.id, number=1, order=1, type='vocabulary',
                         title='Twenty words', collection_id=collection.id)
    cards = [{'id': index + 1, 'front': word.english_word, 'back': word.russian_word,
              'example': f'{word.english_word} example'} for index, word in enumerate(words)]
    first = Lessons(module_id=module.id, number=2, order=2, type='flashcards',
                    title='First six', content={'cards': cards[:6]})
    second = Lessons(module_id=module.id, number=10, order=10, type='flashcards',
                     title='Other fourteen', collection_id=collection.id, content={'cards': cards[6:]})
    db_session.add_all([vocabulary, first, second])
    db_session.commit()
    return first, second, words, collection


def test_authored_six_and_fourteen_never_expand_to_previous_or_own_collection(app, split_deck):
    first, second, words, _ = split_deck
    first_words, missing, _ = _resolve_lesson_deck(first)
    second_words, second_missing, _ = _resolve_lesson_deck(second)
    assert [word.id for word in first_words] == [word.id for word in words[:6]]
    assert [word.id for word in second_words] == [word.id for word in words[6:]]
    assert not missing and not second_missing
    assert _lesson_deck_size(first) == 6
    assert _lesson_deck_size(second) == 14


def test_english_matching_is_case_insensitive_but_numeric_ids_remain_explicit(app, db_session, split_deck):
    first, _, words, _ = split_deck
    first.content = {'cards': [
        {'front': words[0].english_word.upper(), 'back': 'Авторский перевод'},
        {'word_id': str(words[19].id)},
    ]}
    db_session.flush()
    selected, display, _ = _resolve_lesson_deck(first)
    assert [word.id for word in selected] == [words[0].id, words[19].id]
    assert display == []
    assert _lesson_deck_size(first) == 2


def test_missing_english_stays_display_only_and_is_counted_in_small_deck(app, db_session, split_deck):
    first, _, words, _ = split_deck
    missing = {'id': 'not-imported', 'front': f'missing_{uuid.uuid4().hex}', 'back': 'Ещё не импортировано',
               'audio': '[sound:authored_scope_missing.mp3]'}
    first.content = {'cards': [first.content['cards'][0], missing]}
    db_session.flush()
    selected, display, _ = _resolve_lesson_deck(first)
    assert [word.id for word in selected] == [words[0].id]
    assert len(display) == 1 and display[0]['front'] == missing['front']
    assert display[0]['word_id'] is None and display[0]['direction_id'] is None
    assert display[0]['audio_url'] == '/static/audio/authored_scope_missing.mp3'
    assert _lesson_deck_size(first) == 2


def test_unimported_authored_cards_do_not_fall_back_to_unrelated_words(app, db_session, split_deck):
    first, _, _, _ = split_deck
    first.content = json.dumps({'cards': [{'front': f'unimported_{uuid.uuid4().hex}', 'back': 'Пример'}]})
    db_session.flush()
    selected, display, _ = _resolve_lesson_deck(first)
    assert selected == []
    assert len(display) == 1
    assert _lesson_deck_size(first) == 1


def test_explicit_empty_deck_is_empty_legacy_collection_fallback_still_works(app, db_session, split_deck):
    first, _, _, _ = split_deck
    first.content = {'cards': []}
    db_session.flush()
    assert _lesson_deck_size(first) == 0
    first.content = {}
    db_session.flush()
    assert _lesson_deck_size(first) == 20


@pytest.mark.parametrize('entry', ['render_card_lesson', 'card_lesson'])
def test_both_render_paths_keep_six_words_and_existing_srs_ids(
        app, db_session, split_deck, admin_user, monkeypatch, entry):
    from app.curriculum.routes import card_lessons
    first, _, words, _ = split_deck
    user_word = UserWord(user_id=admin_user.id, word_id=words[0].id)
    db_session.add(user_word)
    db_session.flush()
    direction = UserCardDirection(user_word_id=user_word.id, direction=DIRECTION_ENG_RUS,
                                  interval=17, repetitions=4, state='review')
    db_session.add(direction)
    db_session.commit()
    stable_id = direction.id
    captured = {}
    monkeypatch.setattr(card_lessons, 'render_template', lambda template, **context: captured.update(context) or 'ok')
    with app.test_request_context('/'):
        login_user(admin_user)
        if entry == 'render_card_lesson':
            result = card_lessons.render_card_lesson(first)
        else:
            result = card_lessons.card_lesson(lesson_id=first.id)
    assert result == 'ok'
    assert {card['word_id'] for card in captured['fc_cards']} == {word.id for word in words[:6]}
    assert stable_id in {card['direction_id'] for card in captured['fc_cards']}
    db_session.refresh(direction)
    assert direction.id == stable_id and direction.interval == 17 and direction.repetitions == 4
    assert {item.word_id for item in UserWord.query.filter_by(user_id=admin_user.id)} == {
        word.id for word in words[:6]}


def test_six_card_lesson_can_complete_below_default_ten(app, client, db_session, split_deck, admin_user):
    first, _, _, _ = split_deck
    admin_user.onboarding_completed = True
    db_session.commit()
    response = client.post(f'/curriculum/lessons/{first.id}/complete-srs',
                           json={'cards_studied': 6, 'accuracy': 100})
    assert response.status_code == 200
    progress = LessonProgress.query.filter_by(user_id=admin_user.id, lesson_id=first.id).one()
    assert progress.status == 'completed'
