"""The browser selection shares the native reader inventory and deck quiz."""

from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
import pytest

from app.auth.models import User
from app.books.models import Book, Chapter
from app.books.reader_vocabulary import plain_paragraphs, selection_context
from app.study.models import NativeReaderVocabulary, QuizDeck, QuizDeckWord
from app.utils.db import db
from app.words.models import CollectionWords
from tests.api.test_native_reader import enabled, learner, native_app, sync, word  # noqa: F401


@pytest.fixture
def fixture_book(native_app: Flask) -> tuple[Book, Chapter]:
    title = 'Synthetic expression reader ' + uuid4().hex[:8]
    book = Book(title=title, author='Fixture', chapters_cnt=1, rights_status='public_domain', is_published=True)
    db.session.add(book)
    db.session.flush()
    chapter = Chapter(
        book_id=book.id, chap_num=1, title='Two encounters', words=30,
        text_raw='A red kiosk nearby.\nWe turn aside at noon.\n\nFar from the station.\nWe turn aside at noon.',
    )
    db.session.add(chapter)
    db.session.commit()
    return book, chapter


def cookie_client(app: Flask, user: User) -> tuple[FlaskClient, dict[str, str]]:
    user.onboarding_completed = True
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    return client, {'X-CSRFToken': client.get('/csrf-token').json['csrf_token']}


def selection(chapter: Chapter, paragraph: int, phrase: str) -> dict:
    rendered = plain_paragraphs(chapter.text_raw)[paragraph]
    start = rendered.index(phrase)
    return {'revision': sha256(chapter.text_raw.encode()).hexdigest(), 'paragraph': paragraph,
            'start': start, 'end': start + len(phrase)}


def test_browser_selection_replays_and_converges_with_native(
    native_app: Flask, fixture_book: tuple[Book, Chapter],
) -> None:
    user, bearer = learner(native_app)
    client, csrf = cookie_client(native_app, user)
    book, chapter = fixture_book
    url = f'/words/reading-vocabulary/selection/{book.id}/{chapter.chap_num}'
    data = selection(chapter, 1, 'turn aside')
    db.session.add(CollectionWords(english_word='turn aside', russian_word='свернуть', level='A2'))
    db.session.commit()

    assert client.post(url, json=data).status_code == 400
    preview = client.post(url, json=data, headers=csrf)
    assert preview.status_code == 200, preview.json
    assert preview.json == {'english': 'turn aside', 'context': 'We turn aside at noon.', 'translation': 'свернуть'}
    assert db.session.get(NativeReaderVocabulary, user.id) is None
    data['translation'] = 'свернуть'  # noqa: RUF001 -- Russian translation fixture
    saved = client.post(url, json=data, headers=csrf)
    assert saved.status_code == 200, saved.json
    assert saved.headers['Cache-Control'] == 'private, no-store'
    assert client.post(url, json=data, headers=csrf).json == saved.json

    native = native_app.test_client()
    state = sync(native, bearer, [], str(uuid4())).json
    assert state['cursor'] == 1 and len(state['words']) == 1
    item = state['words'][0]
    assert item['english'] == 'turn aside'
    assert item['contexts'][0]['sentence'] == 'We turn aside at noon.'
    assert item['contexts'][0]['location'] == {
        'title': book.title, 'bookID': book.id, 'chapter': 1, 'paragraph': 3,
    }
    assert not any(key.startswith('_') for key in item)
    assert QuizDeckWord.query.filter_by(custom_english='turn aside').count() == 1
    from app.study.services.deck_service import DeckService
    deck = db.session.get(QuizDeck, db.session.get(NativeReaderVocabulary, user.id).payload['deck'])
    updated, error = DeckService.update_deck(deck.id, user.id, is_public=True, generate_share=True)
    assert updated is None and error and not deck.is_public and not deck.share_code


    g.pop('_login_user', None)
    review = client.get(saved.json['review_url'])
    assert review.status_code == 200
    deck_id = urlsplit(saved.json['review_url']).path.rsplit('/', 1)[-1]
    questions = client.get('/study/api/get-quiz-questions', query_string={
        'source': 'deck', 'deck_id': deck_id, 'reader_card': item['id'],
    })
    assert questions.status_code == 200
    assert len(questions.json['questions']) == 2
    assert all(q['word_id'] is None for q in questions.json['questions'])

    soup = BeautifulSoup(review.get_data(as_text=True), 'html.parser')
    back = soup.find('a', string='Вернуться к чтению')['href']
    opened = client.get(back)
    assert parse_qs(urlsplit(opened.location).query)['reader_paragraph'] == ['1']
    assert client.get(saved.json['collection_url']).status_code == 200

    first_use = {**selection(chapter, 0, 'turn aside'), 'translation': data['translation']}
    assert client.post(url, json=first_use, headers=csrf).status_code == 200
    both = sync(native, bearer, [], str(uuid4())).json
    assert both['cursor'] == 2 and len(both['words']) == 1
    assert {c['location']['paragraph'] for c in both['words'][0]['contexts']} == {1, 3}
    assert QuizDeckWord.query.filter_by(custom_english='turn aside').count() == 1

    other, _ = learner(native_app)
    other_client, _ = cookie_client(native_app, other)
    assert other_client.get(back).status_code == 404
    g.pop('_login_user', None)
    assert other_client.get('/study/api/get-quiz-questions', query_string={
        'source': 'deck', 'deck_id': deck_id, 'reader_card': item['id'],
    }).status_code == 403

    g.pop('_login_user', None)
    chapter.text_raw = chapter.text_raw.replace('Far from the station.\nWe turn aside at noon.', 'Far from the station.')
    db.session.commit()
    drift = client.get(back)
    assert parse_qs(urlsplit(drift.location).query)['reader_quote_missing'] == ['1']
    assert client.post(url, json=data, headers=csrf).status_code == 409


def test_native_lf_context_resolves_web_paragraph_and_manual_translation(
    native_app: Flask, fixture_book: tuple[Book, Chapter],
) -> None:
    user, bearer = learner(native_app)
    book, chapter = fixture_book
    incoming = word(english='turn aside', lemma='turn aside', sentence='We turn aside at noon.', translation='сворачивать')
    incoming['contexts'] = [{
        'sentence': incoming['sentence'], 'date': incoming['addedAt'],
        'location': {'title': book.title, 'bookID': book.id, 'chapter': chapter.chap_num, 'paragraph': 3},
    }]
    assert sync(native_app.test_client(), bearer, [incoming], str(uuid4())).status_code == 200
    client, csrf = cookie_client(native_app, user)
    response = client.get('/words/reading-vocabulary')
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    link = next(a['href'] for a in soup.select('a[href*="/context/"]') if incoming['id'] in a['href'])
    assert parse_qs(urlsplit(client.get(link).location).query)['reader_paragraph'] == ['1']

    payload = selection(chapter, 0, 'red kiosk')
    url = f'/words/reading-vocabulary/selection/{book.id}/{chapter.chap_num}'
    assert client.post(url, json=payload, headers=csrf).json['translation'] == ''
    payload['translation'] = 'красный киоск'
    assert client.post(url, json=payload, headers=csrf).status_code == 200


def test_selection_cannot_cross_visible_licensed_text(
    native_app: Flask, fixture_book: tuple[Book, Chapter],
) -> None:
    user, _ = learner(native_app)
    client, csrf = cookie_client(native_app, user)
    book, chapter = fixture_book
    book.rights_status = 'licensed'
    book.is_free_access = True
    book.allowed_text_percent = 30
    db.session.commit()
    url = f'/words/reading-vocabulary/selection/{book.id}/{chapter.chap_num}'
    payload = selection(chapter, 1, 'turn aside')
    assert client.post(url, json=payload, headers=csrf).status_code == 409
    book.allowed_text_percent = 0
    db.session.commit()
    assert client.post(url, json=payload, headers=csrf).status_code == 403
    assert db.session.get(NativeReaderVocabulary, user.id) is None



def test_selection_context_handles_an_abbreviation_and_a_boundary() -> None:
    paragraph = 'Go now. Dr. Avery will answer. It can wait. Stay here.'
    start = paragraph.index('Avery')
    assert selection_context(paragraph, start, start + len('Avery')) == 'Dr. Avery will answer.'
    end = paragraph.index('wait') + len('wait')
    assert selection_context(paragraph, start, end) == 'Dr. Avery will answer. It can wait.'
