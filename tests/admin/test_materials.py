"""Cover the catalog through the real admin routes and edit forms."""
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.admin.routes import materials
from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.models import GrammarExercise, GrammarTopic

INDEX = '/admin/materials'


def _page(response: TestResponse) -> BeautifulSoup:
    assert response.status_code == 200, response.location
    return BeautifulSoup(response.data, 'html.parser')


def _results(page: BeautifulSoup) -> list[tuple[str, int]]:
    return [(row['data-kind'], int(row['data-material-id'])) for row in page.select('.materials-result')]


@pytest.fixture
def material_pair(db_session: scoped_session) -> tuple[Lessons, GrammarExercise]:
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db_session.add(level)
        db_session.flush()
    module = Module(level_id=level.id, number=995, title='Materials test module')
    topic = GrammarTopic(slug='materials-' + uuid4().hex, title='Harbour topic',
                         title_ru='Тема гавани', level='A1')
    db_session.add_all([module, topic])
    db_session.flush()
    lesson = Lessons(module_id=module.id, number=1, title='Harbour lesson', type='grammar', content={})
    exercise = GrammarExercise(topic_id=topic.id, exercise_type='translation',
                               content={'sentence': 'A harbour_ test', 'correct_answer': 'A safe harbour'})
    db_session.add_all([lesson, exercise])
    db_session.commit()
    return lesson, exercise


def test_materials_search_and_filters(
    admin_client: FlaskClient, material_pair: tuple[Lessons, GrammarExercise],
) -> None:
    lesson, exercise = material_pair
    combined = _page(admin_client.get(INDEX, query_string={'q': 'Harbour', 'level': 'a1'}))
    assert set(_results(combined)) == {('lesson', lesson.id), ('exercise', exercise.id)}
    for kind, model in [('lesson', lesson), ('exercise', exercise)]:
        assert _results(_page(admin_client.get(INDEX, query_string={'q': f'#{model.id}', 'kind': kind}))) == [
            (kind, model.id),
        ]
    assert _results(_page(admin_client.get(INDEX, query_string={'q': 'harbour_'}))) == [('exercise', exercise.id)]
    assert not _results(_page(admin_client.get(INDEX, query_string={'q': 'Harbour', 'level': 'B2'})))
    assert not _results(_page(admin_client.get(INDEX, query_string={'q': '%'})))
    links = {a['href'] for a in combined.select('.materials-directories a')}
    assert {'/admin/words', '/admin/word-sets', '/admin/books', '/admin/book-courses',
            '/admin/collections', '/admin/content-packages', '/admin/grammar-lab/import-exercises-json'} <= links


def test_editor_back_link_and_save_keep_search_and_page(
    admin_client: FlaskClient, db_session: scoped_session, material_pair: tuple[Lessons, GrammarExercise],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lesson, exercise = material_pair
    monkeypatch.setattr(materials, '_PAGE_SIZE', 1)
    lab_first = GrammarExercise(topic_id=exercise.topic_id, exercise_type='translation',
                                content={'question': 'Harbour second exercise', 'correct_answer': 'A port'})
    db_session.add(lab_first)
    db_session.flush()
    db_session.add(Lessons(module_id=lesson.module_id, number=2, type='grammar', title='Harbour second lesson', content={}))
    db_session.commit()

    for kind in ('lesson', 'exercise'):
        search = {'q': 'Harbour', 'kind': kind, 'level': 'A1', 'page': '2'}
        page = _page(admin_client.get(INDEX, query_string=search))
        assert len(_results(page)) == 1
        item_id = _results(page)[0][1]
        path = (f'/curriculum/admin/lesson/{item_id}/edit' if kind == 'lesson'
                else f'/admin/grammar-lab/exercises/{item_id}/edit')
        editor_url = page.select_one('.materials-result a.btn')['href']
        assert urlsplit(editor_url).path == path
        editor = _page(admin_client.get(editor_url))
        back = editor.find('a', string='К результатам поиска')['href']  # noqa: RUF001 -- Exact Russian link text.
        assert urlsplit(back).path == INDEX
        assert parse_qs(urlsplit(back).query) == {key: [value] for key, value in search.items()}
        assert _results(_page(admin_client.get(back))) == _results(page)

        if kind == 'lesson':
            data = {'title': 'Harbour second lesson', 'description': 'Saved via catalog',
                    'number': '2', 'module_id': str(lesson.module_id)}
        else:
            revision = editor.select_one('input[name=revision]')['value']
            data = {'editor_type': 'translation', 'revision': revision, 'order': '3', 'difficulty': '2'}
            preview = _page(admin_client.post(editor_url, data={**data, 'action': 'preview'}))
            data.update(action='apply', preview_token=preview.select_one('input[name=preview_token]')['value'])
        saved = admin_client.post(editor_url, data=data)
        expected = back if kind == 'lesson' else f'{back}#materials-results'
        assert saved.status_code == (302 if kind == 'lesson' else 303) and saved.location == expected
        assert _results(_page(admin_client.get(saved.location))) == _results(page)
        if kind == 'lesson':
            assert db_session.get(Lessons, item_id).description == 'Saved via catalog'
        else:
            assert db_session.get(GrammarExercise, item_id).difficulty == 2


def test_admin_gate_and_safe_return(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
    material_pair: tuple[Lessons, GrammarExercise],
) -> None:
    guest = app.test_client()
    g.pop('_login_user', None)
    assert guest.get(INDEX).status_code in (302, 403)
    with guest.session_transaction() as session:
        session['_user_id'] = test_user.get_id()
        session['_fresh'] = True
    for is_moderator in (False, True):
        test_user.is_moderator = is_moderator
        db_session.commit()
        g.pop('_login_user', None)
        assert guest.get(INDEX).status_code in (302, 403)

    g.pop('_login_user', None)
    lesson, _ = material_pair
    editor = f'/curriculum/admin/lesson/{lesson.id}/edit'
    page = _page(admin_client.get(editor, query_string={'materials_query': 'next=https://example.invalid/'}))
    assert page.find('a', string='К результатам поиска')['href'] == INDEX  # noqa: RUF001 -- Exact Russian link text.
    editor_page = _page(admin_client.get(editor))
    assert not editor_page.find('a', string='К результатам поиска')  # noqa: RUF001 -- Exact Russian link text.
    revision = editor_page.select_one('input[name=content_revision]')['value']
    saved = admin_client.post(editor, data={'content_revision': revision, 'content': '{}'})
    assert saved.status_code == 302 and saved.location == f'/curriculum/admin/lesson/{lesson.id}/view'
