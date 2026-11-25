"""Synthetic examples through the admin form, learner cards and bearer API."""
# ruff: noqa: RUF001 -- Synthetic bilingual examples and Russian UI labels.

from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.services.word_card_examples import parse_examples
from app.auth.models import User
from app.modules.models import SystemModule, UserModule
from app.study.models import CardGradeEvent, UserCardDirection, UserWord
from app.words.models import CollectionWords
from tests.admin.test_materials import _page
from tests.api.test_grammar_lab_disputes import browser


WORD = 'synthetic-gulf-fixture'
BEFORE = '<b>A synthetic boat</b> sails.<br>Лодка плывёт.<br><br>A synthetic shp rests.<br/>Корабль отдыхает.'
AFTER = BEFORE.replace('synthetic shp', 'synthetic ship').replace('Корабль отдыхает.', 'Корабль стоит.')


def _form(page: BeautifulSoup) -> tuple[str, dict[str, str]]:
    form = page.select_one('input[name=revision]').find_parent('form')
    fields = {field['name']: field.get_text() if field.name == 'textarea' else field['value']
              for field in form.select('input[name], textarea[name]')}
    return form['action'], fields


@pytest.mark.parametrize(('raw', 'position', 'english', 'russian', 'expected'), [
    (BEFORE, 1, 'A synthetic ship rests.', 'Корабль стоит.', AFTER),
    ('One fixture.\r\nРаз.\n\nTwo fixture.|Два.', 1, 'Second fixture.', 'Второй.',
     'One fixture.\r\nРаз.\n\nSecond fixture.|Второй.'),
    ('[ { "english": "One fixture.", "russian": "Раз.", "hint": {"n": 1} }, {"en":"Two fixture.","ru":"Два.","extra":[1,2]} ]',
     1, 'Second fixture.', 'Второй.',
     '[ { "english": "One fixture.", "russian": "Раз.", "hint": {"n": 1} }, {"en":"Second fixture.","ru":"Второй.","extra":[1,2]} ]'),
    ('{"sentence":"One fixture.", "metadata":{"x":true}}', 0, 'One fixture.', 'Один.',
     '{"sentence":"One fixture.", "metadata":{"x":true}, "ru": "Один."}'),
    ('  [ ]  ', 0, 'New fixture.', 'Новый.', '  [ {"en": "New fixture.", "ru": "Новый."}]  '),
    ('Plain <strong>test</strong> line.<BR />Русская строка.', 0, 'Plain trial line.', 'Русская строка.',
     'Plain <strong>trial</strong> line.<BR />Русская строка.'),
])
def test_example_formats_preserve_neighbor_bytes(
    raw: str, position: int, english: str, russian: str, expected: str,
) -> None:
    assert parse_examples(raw).edit(position, english, russian) == expected


def test_existing_word_card_previews_applies_and_preserves_history(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    word = CollectionWords(english_word=WORD, russian_word='Исходный перевод', sentences=BEFORE, level='A1',
                           listening='synthetic.mp3', get_download=1, frequency_rank=31,
                           synonyms='older, backfill', antonyms=['former'])
    db_session.add(word)
    db_session.flush()
    owned = UserWord(user_id=test_user.id, word_id=word.id)
    db_session.add(owned)
    db_session.flush()
    card = UserCardDirection(user_word_id=owned.id, direction='eng-rus', repetitions=8, interval=17)
    db_session.add(card)
    db_session.flush()
    grade = CardGradeEvent(user_id=test_user.id, direction_id=card.id, word_id=word.id, rating=3,
                           state_before='review', state_after='review', interval_after=17)
    db_session.add(grade)
    module = SystemModule.query.filter_by(code='words').first()
    if module is None:
        module = SystemModule(code='words', name='Words', is_active=True)
        db_session.add(module)
        db_session.flush()
    db_session.add_all([UserModule(user_id=user.id, module_id=module.id, is_enabled=True)
                        for user in (admin_user, test_user)])
    db_session.commit()

    listing = _page(admin_client.get('/admin/materials', query_string={'q': WORD, 'kind': 'word'}))
    card_path = listing.find('a', string='Примеры и карточка')['href']
    assert listing.find('a', string='Править перевод')
    page = _page(admin_client.get(card_path))
    second = page.find('a', string=lambda value: value and value.strip() == 'Пример 2')['href']
    page = _page(admin_client.get(second))
    editor_url, fields = _form(page)
    public_url = page.find('a', string='На сайте')['href']
    cabinet_url = page.find('a', string='Карточка в словаре')['href']
    assert fields['example_en'] == 'A synthetic shp rests.'
    request = {
        **fields, 'example_en': 'A synthetic ship rests.', 'example_ru': 'Корабль стоит.',
        'ipa_transcription': '/sɪnθ/', 'antonyms': 'opposite\nother', 'etymology': 'Synthetic etymology.',
        'action': 'preview',
    }
    proof = _page(admin_client.post(editor_url, data=request))
    assert proof.select_one('input[name=preview_token]')['value']
    assert all(text in proof.text for text in ('sɪnθ', 'Synthetic etymology.', 'A synthetic ship rests.', 'Корабль стоит.'))
    assert word.sentences == BEFORE and word.ipa_transcription is None
    _, publish = _form(proof)
    publish['action'] = 'apply'
    assert admin_client.post(editor_url, data={**publish, 'example_ru': 'Изменено после просмотра.'}).status_code == 409
    saved = admin_client.post(editor_url, data=publish)
    assert saved.status_code == 303 and urlsplit(saved.location).path == '/admin/materials'
    assert parse_qs(urlsplit(saved.location).query) == {'q': [WORD], 'kind': ['word']}
    assert admin_client.post(editor_url, data=publish).status_code == 409

    assert word.sentences == AFTER
    assert word.synonyms == 'older, backfill' and word.antonyms == ['opposite', 'other']
    assert word.ipa_transcription == 'sɪnθ' and word.etymology == 'Synthetic etymology.'
    assert word.russian_word == 'Исходный перевод'
    assert word.listening == 'synthetic.mp3' and word.level == 'A1' and word.get_download == 1 and word.frequency_rank == 31
    assert card.repetitions == 8 and card.interval == 17 and grade.rating == 3
    assert AdminAuditLog.query.filter_by(action='word.card.update', target_id=str(word.id)).count() == 1

    guest, _ = browser(app, test_user)
    g.pop('_login_user', None)
    public = _page(app.test_client().get(public_url))
    g.pop('_login_user', None)
    cabinet = _page(guest.get(cabinet_url))
    for view in (public, cabinet):
        assert 'A synthetic ship rests.' in view.text and 'Корабль стоит.' in view.text
        assert 'Synthetic etymology.' in view.text and 'opposite' in view.text
        assert '/sɪnθ/' in view.text and '//sɪnθ//' not in view.text
    jwt = create_access_token(identity=str(test_user.id), additional_claims={'auth_version': test_user.auth_version()})
    g.pop('_login_user', None)
    native = app.test_client().get(f'/api/native/vocabulary/{word.id}', headers={'Authorization': f'Bearer {jwt}'})
    assert native.status_code == 200
    assert {key: native.json[key] for key in ('id', 'sentences', 'listening', 'level', 'in_study')} == {
        'id': word.id, 'sentences': AFTER, 'listening': 'synthetic.mp3', 'level': 'A1', 'in_study': True,
    }
    g.pop('_login_user', None)
    assert guest.post(editor_url, data=publish).status_code == 302


@pytest.mark.parametrize('prior', [
    None,
    '<section data-synthetic="yes">Во входе неизвестный формат.</section>',
    '<section>' + 'synthetic ' * 2100 + '</section>',
], ids=['empty', 'opaque', 'oversized-opaque'])
def test_empty_can_add_example_and_opaque_value_survives_metadata_change(
    admin_client: FlaskClient, db_session: scoped_session, prior: str | None,
) -> None:
    word = CollectionWords(english_word='synthetic formats', level='A1', sentences=prior)
    db_session.add(word)
    db_session.commit()
    editor_url, form = _form(_page(admin_client.get(f'/admin/words/{word.id}/card')))
    assert ('example_en' in form) == (prior is None)
    form['ipa_transcription'] = 'aɪ'
    if prior is None:
        form.update(example_en='Synthetic new example.', example_ru='Новый пример.')
    form['action'] = 'preview'
    prepared = _page(admin_client.post(editor_url, data=form))
    _, payload = _form(prepared)
    payload['action'] = 'apply'
    assert admin_client.post(editor_url, data=payload).status_code == 303
    assert word.ipa_transcription == 'aɪ'
    assert word.sentences == (prior if prior is not None else 'Synthetic new example.<br>Новый пример.')


def test_json_pairs_render_without_storage_syntax_through_both_learner_gets(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    before = ('[{"english":"Synthetic draft.","russian":"Черновик.","note":{"source":true}},'
              ' { "sentence": "Synthetic neighbor.", "translation": "Сосед.", "rank": 2 }]')
    after = before.replace('Synthetic draft.', 'Synthetic published.').replace('Черновик.', 'Готово.')
    word = CollectionWords(english_word='synthetic-json-pair', russian_word='Проверка', sentences=before, level='A1')
    module = SystemModule.query.filter_by(code='words').first()
    if module is None:
        module = SystemModule(code='words', name='Words', is_active=True)
        db_session.add(module)
    db_session.add(word)
    db_session.flush()
    db_session.add_all([UserModule(user_id=user.id, module_id=module.id, is_enabled=True)
                        for user in (admin_user, test_user)])
    db_session.commit()
    listing = _page(admin_client.get('/admin/materials', query_string={'q': word.english_word, 'kind': 'word'}))
    editor = _page(admin_client.get(listing.find('a', string='Примеры и карточка')['href']))
    public, cabinet = (editor.find('a', string=label)['href'] for label in ('На сайте', 'Карточка в словаре'))
    edit_url, values = _form(editor)
    values.update(example_en='Synthetic published.', example_ru='Готово.', action='preview')
    preview = _page(admin_client.post(edit_url, data=values))
    assert [node.get_text(strip=True) for node in preview.select('#card-preview-title ~ dl dd p span')] == [
        'Synthetic published.', 'Готово.', 'Synthetic neighbor.', 'Сосед.',
    ]
    _, publish = _form(preview)
    publish['action'] = 'apply'
    assert admin_client.post(edit_url, data=publish).status_code == 303
    assert word.sentences == after
    member, _ = browser(app, test_user)
    for client, path in ((app.test_client(), public), (member, cabinet)):
        g.pop('_login_user', None)
        panel = _page(client.get(path)).select_one('.wprof-example')
        assert [(row.select_one('[lang=en]').text, row.select_one('[lang=ru]').text) for row in panel.select('p')] == [
            ('Synthetic published.', 'Готово.'), ('Synthetic neighbor.', 'Сосед.'),
        ]
        assert '{' not in panel.text and 'source' not in panel.text
    jwt = create_access_token(identity=str(test_user.id), additional_claims={'auth_version': test_user.auth_version()})
    g.pop('_login_user', None)
    response = app.test_client().get(
        f'/api/native/vocabulary/{word.id}', headers={'Authorization': f'Bearer {jwt}'},
    )
    assert response.status_code == 200 and response.json['sentences'] == after and response.json['id'] == word.id


def test_opaque_examples_can_only_be_replaced_explicitly_and_atomically(
    admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    original = '\n<section data-test="opaque"><div>Посторонний синтетический формат.</div></section>\n'
    word = CollectionWords(english_word='synthetic opaque fixture', russian_word='Изначальное значение',
                           level='B1', listening='fixture-opaque.mp3', get_download=1,
                           sentences=original, ipa_transcription='test', synonyms=['other'], etymology='Origin.')
    db_session.add(word)
    db_session.flush()
    owned = UserWord(user_id=test_user.id, word_id=word.id)
    db_session.add(owned)
    db_session.flush()
    direction = UserCardDirection(user_word_id=owned.id, direction='eng-rus', repetitions=6, interval=33)
    db_session.add(direction)
    db_session.flush()
    grade = CardGradeEvent(user_id=test_user.id, direction_id=direction.id, word_id=word.id, rating=3,
                           state_before='review', state_after='review', interval_after=33)
    db_session.add(grade)
    db_session.commit()
    preserved = {key: getattr(word, key) for key in word.__table__.columns.keys() if key != 'sentences'}
    path = f'/admin/words/{word.id}/card'
    page = _page(admin_client.get(path))
    replacement_url = page.find('a', string=lambda value: value and value.strip() == 'Заменить все примеры')['href']
    opened = _page(admin_client.get(replacement_url))
    assert opened.pre.text == original and word.sentences == original
    target, form = _form(opened)
    form.update(english='Synthetic first.\nSynthetic second.', russian='Первый.\nВторой.', action='preview')
    assert admin_client.post(target, data={**form, 'russian': 'Только один перевод.'}).status_code == 422
    preview = _page(admin_client.post(target, data=form))
    assert preview.pre.text == original
    assert all(text in preview.text for text in ('Synthetic first.', 'Первый.', 'Synthetic second.', 'Второй.'))
    assert word.sentences == original
    _, apply = _form(preview)
    apply['action'] = 'apply'
    assert admin_client.post(target, data={**apply, 'english': 'Modified after preview.'}).status_code == 422
    assert word.sentences == original
    assert admin_client.post(target, data={**apply, 'english': 'Changed first.\nSynthetic second.'}).status_code == 409
    assert word.sentences == original
    assert admin_client.post(target, data=apply).status_code == 303
    assert admin_client.post(target, data=apply).status_code == 409
    assert admin_client.get(target).status_code == 404
    assert word.sentences == 'Synthetic first.<br>Первый.<br><br>Synthetic second.<br>Второй.'
    assert {key: getattr(word, key) for key in preserved} == preserved
    assert direction.repetitions == 6 and direction.interval == 33 and grade.rating == 3
    assert AdminAuditLog.query.filter_by(action='word.examples.replace', target_id=str(word.id)).count() == 1
    assert AdminAuditLog.query.filter_by(action='word.card.update', target_id=str(word.id)).count() == 0


def test_partially_readable_storage_offers_replacement_without_losing_regular_edits(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    raw = ('[{"en":"Editable synthetic example.","ru":"Пример."},'
           ' {"opaque":{"retain":"all"}}]')
    word = CollectionWords(english_word='synthetic partial fixture', level='A1', sentences=raw)
    db_session.add(word)
    db_session.commit()
    response = _page(admin_client.get(f'/admin/words/{word.id}/card'))
    assert response.find('a', string=lambda value: value and value.strip() == 'Заменить все примеры')
    edit_url, data = _form(response)
    assert data['example_en'] == 'Editable synthetic example.'
    data.update(example_ru='Исправлено.', action='preview')
    _, prepared = _form(_page(admin_client.post(edit_url, data=data)))
    prepared['action'] = 'apply'
    assert admin_client.post(edit_url, data=prepared).status_code == 303
    assert word.sentences == raw.replace('Пример.', 'Исправлено.')
