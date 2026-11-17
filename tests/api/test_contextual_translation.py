"""Lexical API uses the existing word table; no remote translation provider."""
import pytest
from tests.api.test_native_push import native_app
from tests.api.test_native_full_integration import learner

PREFIX = '/api/native/reader/lexicon'


def selection(text='ice', sentence='🌊 She broke the ice at the meeting.', lemma='ice'):
    start = sentence.index(text)
    return dict(text=text, sentence=sentence, lemma=lemma,
                lower_utf16=len(sentence[:start].encode('utf-16-le'))//2,
                length_utf16=len(text.encode('utf-16-le'))//2)


@pytest.fixture(autouse=True)
def clean_words(native_app):
    from app.words.models import CollectionWords
    from app.utils.db import db
    CollectionWords.query.delete()
    db.session.commit()


def add_word(english, russian, kind='word', **metadata):
    from app.words.models import CollectionWords
    from app.utils.db import db
    word = CollectionWords(english_word=english, russian_word=russian,
                           item_type=kind, get_download=0, **metadata)
    db.session.add(word); db.session.commit()
    return word


def test_current_idiom_marking_and_metadata_are_used_without_seed(native_app):
    from app.utils.db import db
    word = add_word('break the ice', 'разрядить обстановку', usage_context='A friendly joke.', level='B1', frequency_band=2)
    _, headers = learner(native_app); client = native_app.test_client()
    assert client.post(PREFIX, headers=headers, json=selection()).json['expressions'] == []
    word.item_type = 'idiom'; db.session.commit()
    response = client.post(PREFIX, headers=headers, json=selection())
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.json['version'] == 'opus-lexicon-v1'
    assert response.json['expressions'][0]['sourceText'] == 'broke the ice'
    assert response.json['expressions'][0]['lemma'] == 'break the ice'
    page = client.get('/api/native/reader/dictionary', headers=headers).json
    entry = next(e for e in page['entries'] if e['id'] == word.id)
    assert (entry['kind'], entry['frequencyBand'], entry['level']) == ('idiom', 2, 'B1')
    assert entry['example'] == 'A friendly joke.'


@pytest.mark.parametrize('text,sentence,phrase,kind', [
    ('pulling', "I'm just pulling your leg.", "pull someone's leg", 'idiom'),
    ('turned', 'She turned the music down.', 'turn down', 'phrasal_verb'),
    ('down', 'She turned down the offer.', 'turn down', 'phrasal_verb'),
    ('beans', 'She spilled the beans.', 'spill the beans', 'idiom'),
])
def test_inflected_possessive_and_separated_candidates(native_app, text, sentence, phrase, kind):
    add_word(phrase, 'выражение', kind)
    _, headers = learner(native_app)
    reply = native_app.test_client().post(PREFIX, headers=headers, json=selection(text, sentence, text))
    assert reply.status_code == 200, reply.json
    assert reply.json['expressions'][0]['lemma'] == phrase


def test_expression_must_include_selected_occurrence(native_app):
    add_word('break the ice', 'разрядить обстановку', 'idiom')
    _, headers = learner(native_app)
    sentence = 'Break the ice, then bring more ice.'
    body = selection('ice', sentence)
    body['lower_utf16'] = sentence.rindex('ice')
    assert native_app.test_client().post(PREFIX, headers=headers, json=body).json['expressions'] == []


def test_regular_forms_look_up_real_dictionary_not_guessed_translation(native_app):
    add_word('mutter', 'бормотать', level='B2')
    _, headers = learner(native_app)
    response = native_app.test_client().post(PREFIX, headers=headers,
        json=selection('muttered', 'She muttered something.', 'muttered'))
    assert response.json['entries'][0]['english'] == 'mutter'
    assert response.json['entries'][0]['translation'] == 'бормотать'
    assert 'translation' not in response.json  # only candidates, no server model


@pytest.mark.parametrize('changes', [dict(lower_utf16=True), dict(lower_utf16=-1), dict(lower_utf16=1),
    dict(length_utf16=2), dict(text=''), dict(lemma=''), dict(sentence='x'*1201),
    dict(text='два'), dict(extra=True), dict(lower_utf16=1.5)])
def test_invalid_spans_and_payloads_are_rejected(native_app, changes):
    _, headers = learner(native_app)
    response = native_app.test_client().post(PREFIX, headers=headers, json=dict(selection(), **changes))
    assert response.status_code == 400, response.json


def test_cookie_cannot_replace_bearer_and_lookup_is_read_only(native_app):
    from app.words.models import CollectionWords
    user, headers = learner(native_app); client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id); session['_fresh'] = True
    assert client.post(PREFIX, json=selection()).status_code == 401
    response = client.post(PREFIX, headers=headers, json=selection())
    assert response.status_code == 200, response.json
    assert CollectionWords.query.count() == 0


def test_csrf_exemptions_still_match_reviewed_allowlist(native_app):
    from tests.security.test_csrf_sweep import test_exempt_views_allowlist
    test_exempt_views_allowlist(native_app)
