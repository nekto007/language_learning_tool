"""Paths from the Materials index through the actual library admin forms."""
# ruff: noqa: RUF001 -- Russian copy and test translations.

from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy import func
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.services import chapter_editor
from app.auth.models import User
from app.books.models import Book, Bookmark, Chapter, UserChapterProgress
from app.modules.models import SystemModule, UserModule
from app.study.models import CardGradeEvent, UserCardDirection, UserWord, WordSet
from app.words.models import Collection, CollectionWords, word_book_link
from tests.admin.test_materials import INDEX, _page, _results
from tests.api.test_grammar_lab_disputes import browser


@pytest.fixture
def library(db_session: scoped_session, test_user: User) -> tuple:
    book = Book(slug='proof-material-library', title='Material library proof', author='Index proof author',
                chapters_cnt=1, words_total=7, unique_words=6, rights_status='public_domain', level='A1')
    words = [CollectionWords(english_word=name, russian_word='Перевод для проверки', level='A1',
                             sentences='Original example.', listening='original.mp3', frequency_rank=42)
             for name in ('river', 'forest', 'valley', 'run', 'one', 'flow', 'stand', 'lie', 'here', 'rest')]
    word_set = WordSet(slug='material-library-proof', name='Set library proof', level='A1')
    collection = Collection(name='Collection library proof')
    db_session.add_all([book, word_set, collection, *words])
    db_session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='Opening',
                      text_raw='A river runs.\\nOne river flows.\\n\\nA forest stands.', words=9)
    db_session.add(chapter)
    db_session.flush()
    bookmark = Bookmark(user_id=test_user.id, book_id=book.id, name='Private test note',
                        context='A river runs.', position=38)
    progress = UserChapterProgress(user_id=test_user.id, chapter_id=chapter.id, offset_pct=0.45)
    db_session.add_all([bookmark, progress])
    old = {'river': 2, 'forest': 1, 'run': 1, 'one': 1, 'flow': 1, 'stand': 1}
    for word in words:
        if word.english_word in old:
            db_session.execute(word_book_link.insert().values(
                book_id=book.id, word_id=word.id, frequency=old[word.english_word],
            ))
    db_session.commit()
    return book, chapter, bookmark, progress, words, word_set, collection


def _field(page, name: str) -> str:
    return str(page.select_one(f'input[name="{name}"]')['value'])


def _search(client: FlaskClient, kind: str, query: str) -> str:
    page = _page(client.get(INDEX, query_string={'kind': kind, 'q': query}))
    assert len(_results(page)) == 1
    return str(page.select_one('.materials-actions a.btn')['href'])


def _snapshot_link(book: Book, word: CollectionWords, db_session: scoped_session) -> tuple | None:
    row = db_session.execute(word_book_link.select().where(
        word_book_link.c.book_id == book.id, word_book_link.c.word_id == word.id,
    )).one_or_none()
    return (row.id, row.frequency) if row else None


def test_catalog_filters_and_existing_editors(admin_client: FlaskClient, library: tuple) -> None:
    book, _, _, _, words, word_set, collection = library
    for term, kind, model in [
        ('Index proof author', 'book', book),
        ('river', 'word', words[0]),
        ('Set library proof', 'word_set', word_set),
        ('Collection library proof', 'collection', collection),
    ]:
        page = _page(admin_client.get(INDEX, query_string={'kind': kind, 'q': term}))
        assert _results(page) == [(kind, model.id)]
        exact = _page(admin_client.get(INDEX, query_string={'kind': kind, 'q': f'#{model.id}'}))
        assert _results(exact) == [(kind, model.id)]
        assert admin_client.get(page.select_one('.materials-actions a.btn')['href']).status_code == 200

    for kind, query, data in [
        ('word_set', 'Set library proof', {'name': 'Set library proof', 'description': 'New set', 'level': 'A1'}),
        ('collection', 'Collection library proof',
         {'name': 'Collection library proof', 'description': 'New collection'}),
    ]:
        path = _search(admin_client, kind, query)
        response = admin_client.post(path, data=data)
        assert response.status_code == 302 and parse_qs(urlsplit(response.location).query) == {
            'q': [query], 'kind': [kind],
        }
    assert word_set.description == 'New set' and collection.description == 'New collection'


def test_translate_one_word_sees_new_answer_on_both_cards_and_keeps_rating(
    app: Flask, admin_client: FlaskClient, db_session: scoped_session,
    admin_user: User, test_user: User, library: tuple,
) -> None:
    _, _, _, _, words, _, _ = library
    word = words[0]
    user_word = UserWord(user_id=test_user.id, word_id=word.id)
    db_session.add(user_word)
    db_session.flush()
    card = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
    card.repetitions = 3
    db_session.add(card)
    db_session.flush()
    grade = CardGradeEvent(user_id=test_user.id, direction_id=card.id, word_id=word.id, rating=3,
                           state_before='review', state_after='review', interval_after=8)
    db_session.add(grade)
    module = SystemModule.query.filter_by(code='words').first()
    if not module:
        module = SystemModule(code='words', name='Words', is_active=True)
        db_session.add(module)
        db_session.flush()
    db_session.add(UserModule(user_id=admin_user.id, module_id=module.id, is_enabled=True))
    admin_user.onboarding_completed = True
    db_session.commit()
    edit_url = _search(admin_client, 'word', 'river')
    old_directory = _page(admin_client.get('/admin/words'))
    assert old_directory.find('a', href=INDEX + '?kind=word') is not None
    assert old_directory.find('a', href=f'/admin/words/{word.id}/translation') is not None
    page = _page(admin_client.get(edit_url))
    public = page.find('a', string='На сайте')['href']
    detail = page.find('a', string='Карточка в словаре')['href']
    revision = _field(page, 'revision')
    assert word.russian_word in admin_client.get(public).text
    assert admin_client.post(edit_url, data={'translation': ' ', 'revision': revision}).status_code == 422
    updated = admin_client.post(edit_url, data={'translation': 'Исправленный перевод', 'revision': revision})
    assert updated.status_code == 303 and urlsplit(updated.location).path == INDEX
    assert word.russian_word == 'Исправленный перевод'
    assert word.english_word == 'river' and word.listening == 'original.mp3' and word.frequency_rank == 42
    assert word.sentences == 'Original example.' and grade.rating == 3 and card.repetitions == 3
    assert word.russian_word in admin_client.get(public).text and word.russian_word in admin_client.get(detail).text
    assert admin_client.post(edit_url, data={'translation': 'Устаревшее значение', 'revision': revision}).status_code == 409
    assert AdminAuditLog.query.filter_by(admin_id=admin_user.id, action='word.translation.update',
                                         target_id=str(word.id)).count() == 1
    word.level = 'C2'
    db_session.commit()
    assert _page(admin_client.get(edit_url)).find('a', string='На сайте') is None
    visitor, _ = browser(app, test_user)
    g.pop('_login_user', None)
    assert visitor.post(edit_url, data={'translation': 'Чужая правка', 'revision': revision}).status_code == 302


def test_chapter_preview_apply_keeps_identity_progress_bookmarks_and_links(
    app: Flask, admin_client: FlaskClient, db_session: scoped_session, test_user: User, library: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book, chapter, bookmark, progress, words, _, _ = library
    river, forest, valley = words[:3]
    other_book = Book(title='Separate book', author='Proof', chapters_cnt=0)
    db_session.add_all([other_book, Chapter(book_id=book.id, chap_num=2, title='Long sibling',
                                           words=20_000, text_raw='Distant hillside. ' * 10_000)])
    db_session.flush()
    db_session.execute(word_book_link.insert().values(book_id=other_book.id, word_id=river.id, frequency=9))
    if db_session.get_bind().dialect.name == 'postgresql':
        chapter.ts_idx = func.to_tsvector('forest')
    db_session.commit()
    analysed = []
    original_process = chapter_editor.process_text

    def record(text: str, *args) -> list[str]:
        assert 'distant hillside' not in text
        result = original_process(text, *args)
        analysed.append(result)
        return result

    monkeypatch.setattr(chapter_editor, 'process_text', record)
    reader, _ = browser(app, test_user)
    book_url = _search(admin_client, 'book', 'Index proof author')
    book_page = _page(admin_client.get(book_url))
    chapters = _page(admin_client.get(book_page.find('a', string='Главы книги')['href']))
    edit_url = chapters.find('a', string='Редактировать')['href']
    g.pop('_login_user', None)
    catalogues = [f'/api/books/{book.id}/chapters', f'/api/books/{book.slug}/chapters']
    for catalogue in catalogues:
        response = reader.get(catalogue)
        assert response.status_code == 200
        assert response.json[0]['title'] == 'Opening'
    bookmark_payload = reader.get(f'/api/bookmarks/{book.id}').json
    g.pop('_login_user', None)
    page = _page(admin_client.get(edit_url))
    assert 'Private test note' not in page.text
    body = {'title': 'Corrected opening', 'text': 'A river runs.\nOne valley lies here.\n\nA valley rests.',
            'revision': _field(page, 'revision'), 'action': 'preview'}
    preview = _page(admin_client.post(edit_url, data=body))
    assert 'A forest stands.' in preview.text and 'A valley rests.' in preview.text
    assert chapter.title == 'Opening' and _snapshot_link(book, river, db_session)[1] == 2
    river_link = _snapshot_link(book, river, db_session)[0]
    changed_body = {**body, 'action': 'apply', 'preview_token': _field(preview, 'preview_token')}
    assert admin_client.post(edit_url, data={**changed_body, 'text': body['text'] + ' Extra.'}).status_code == 409
    saved = admin_client.post(edit_url, data=changed_body)
    assert saved.status_code == 303 and saved.location == INDEX + '?q=Index+proof+author&kind=book'
    assert chapter.title == body['title'] and chapter.text_raw == body['text'] and chapter.chap_num == 1
    assert progress.offset_pct == 0.45 and bookmark.position == 38 and bookmark.context == 'A river runs.'
    assert _snapshot_link(book, river, db_session) == (river_link, 1)
    assert _snapshot_link(book, forest, db_session) is None
    assert _snapshot_link(book, valley, db_session)[1] == 2
    assert book.unique_words == 7 and chapter.words == 10
    assert _snapshot_link(other_book, river, db_session)[1] == 9
    assert len(analysed) == 4 and book.words_total == 7 + len(analysed[1]) - len(analysed[0])
    if db_session.get_bind().dialect.name == 'postgresql':
        assert 'valley' in chapter.ts_idx and 'forest' not in chapter.ts_idx
    assert AdminAuditLog.query.filter_by(action='book.chapter.update', target_id=str(chapter.id)).count() == 1
    assert admin_client.post(edit_url, data=changed_body).status_code == 409
    g.pop('_login_user', None)
    for catalogue in catalogues:
        assert reader.get(catalogue).json[0] == {
            'id': chapter.id, 'num': 1, 'title': body['title'], 'words': chapter.words, 'audio_url': None,
        }
    assert reader.get(f'/api/bookmarks/{book.id}').json == bookmark_payload
    assert body['text'] == reader.get(f'/api/books/{book.id}/chapters/1').json['text']
    assert 'A valley rests.' in reader.get(f'/books/{book.slug}/chapter/1').text


@pytest.mark.parametrize('text', [
    'A river runs. One river flows.\n\nA forest stands.',
    'The river stops.\nOne river flows.\n\nA forest stands.',
    'A river runs.\nOne river flows.\n\nA forest stands.\n<script>alert(1)</script>',
    'A river runs.\nOne river flows.\n\nA mountain stands.',
])
def test_chapter_rejects_incompatible_edit(admin_client: FlaskClient, library: tuple, text: str) -> None:
    book, chapter, *_ = library
    path = f'/admin/books/{book.id}/chapters/{chapter.id}/edit'
    revision = _field(_page(admin_client.get(path)), 'revision')
    response = admin_client.post(path, data={
        'title': chapter.title, 'text': text, 'revision': revision, 'action': 'preview',
    })
    assert response.status_code == 422
    assert 'alert-warning' in response.text and chapter.title == 'Opening'


def test_published_structure_without_server_anchors_warns_before_apply(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    book = Book(title='Unanchored chapter', author='Proof', chapters_cnt=1, words_total=2)
    db_session.add(book)
    db_session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='Opening', words=2, text_raw='One. Two.')
    db_session.add(chapter)
    db_session.commit()
    path = f'/admin/books/{book.id}/chapters/{chapter.id}/edit'
    revision = _field(_page(admin_client.get(path)), 'revision')
    data = {'title': chapter.title, 'text': 'One.\nTwo.', 'revision': revision}
    preview = _page(admin_client.post(path, data={**data, 'action': 'preview'}))
    assert 'Закладки, сохранённые только на устройстве' in preview.text
    assert 'загруженная копия' in preview.text
    assert admin_client.post(path, data={**data, 'action': 'apply',
                                       'preview_token': _field(preview, 'preview_token')}).status_code == 303
    assert chapter.text_raw == data['text']


def test_short_reading_keeps_installer_text_even_for_formatting_changes(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    book = Book(title='Structured reading', author='Proof', chapters_cnt=1, reading={'format': 'short_text'})
    db_session.add(book)
    db_session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='Opening', words=2, text_raw='Just words.')
    db_session.add(chapter)
    db_session.commit()
    path = f'/admin/books/{book.id}/chapters/{chapter.id}/edit'
    revision = _field(_page(admin_client.get(path)), 'revision')
    common = {'title': 'New chapter heading', 'revision': revision, 'action': 'preview'}
    formatted = admin_client.post(path, data={**common, 'text': '<em>Just</em> words.'})
    assert formatted.status_code == 422 and 'исходный пакет' in formatted.text
    preview = _page(admin_client.post(path, data={**common, 'text': chapter.text_raw}))
    assert admin_client.post(path, data={**common, 'text': chapter.text_raw, 'action': 'apply',
                                       'preview_token': _field(preview, 'preview_token')}).status_code == 303
    assert chapter.title == common['title'] and chapter.text_raw == 'Just words.'
