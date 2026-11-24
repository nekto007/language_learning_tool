"""Check the regular curriculum import paths after a guided publication."""
# ruff: noqa: RUF001 -- assertions inspect Russian form copy.

from copy import deepcopy
from io import BytesIO
import json

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.admin.main_routes import import_curriculum_data as legacy_import
from app.curriculum.models import Lessons
from tests.admin.test_content_package_routes import APPLY, _content, _page, _preview_id, _upload
from tests.admin.test_guided_topic_editor import INDEX, _field, _fields
from tests.admin.test_guided_topic_editor import _page as _editor_page
from tests.admin.test_guided_topic_editor import installed_topic as installed_topic

JSON_PATHS = ['/admin/curriculum/import', '/curriculum/admin/import']


def _publish(client: FlaskClient, installed: tuple, revision: str) -> str:
    topic, _, _, authored = installed
    document = deepcopy(authored)
    document['title'] = f'Published synthetic title {revision}'
    document['steps'][0]['body'] = f'Published synthetic theory {revision}.'
    path = f'{INDEX}/{topic.id}'
    preview = _editor_page(client.post(path + '/preview', data=_fields(topic, document)))
    published = client.post(path + '/publish', data={'preview_id': _field(preview, 'preview_id')})
    assert published.status_code == 303
    return path


@pytest.fixture
def published_module(
    admin_client: FlaskClient, db_session: scoped_session, installed_topic: tuple,
) -> tuple:
    _, lesson, final, _ = installed_topic
    path = _publish(admin_client, installed_topic, 'one')
    neighbour = Lessons(module_id=lesson.module_id, number=3, order=3, type='text',
                        title='Neighbour lesson', content={'text': 'Original neighbour.'})
    final.content = _content('synthetic-final', 'Original final question.')
    db_session.add(neighbour)
    db_session.commit()
    return lesson, final, neighbour, path


def _source(published: tuple, *, key: str | None = None) -> dict:
    lesson, final, neighbour, _ = published
    questions = _content('synthetic-final', 'Imported final question.')
    return {'level': lesson.module.level.code, 'module': lesson.module.number, 'title': lesson.module.title,
            'lessons': [
                {'lesson_number': neighbour.number, 'type': 'text', 'title': neighbour.title,
                 'content': {'text': 'Imported neighbour.'}},
                {'lesson_number': lesson.number, 'type': 'grammar', 'title': 'Guided seed',
                 'content': {'rule': 'Old source theory.', **({'external_key': key} if key else {})}},
                {'lesson_number': final.number, 'type': 'final_test', 'title': final.title,
                 'content': questions, 'exercises': questions['test_sections'][0]['exercises']},
            ]}


def _post_json(client: FlaskClient, path: str, source: dict) -> str:
    file_field = 'json_file' if path == JSON_PATHS[0] else 'file'
    response = client.post(path, data={file_field: (BytesIO(json.dumps(source).encode()), 'module.json')},
                           follow_redirects=True)
    assert response.status_code == 200
    return response.text


def _snapshot(lesson: Lessons) -> tuple:
    return (lesson.id, lesson.number, lesson.order, lesson.title, lesson.grammar_topic_id,
            lesson.content_version, deepcopy(lesson.content))


def _assert_guided_unchanged(client: FlaskClient, db_session: scoped_session, published: tuple, before: tuple) -> None:
    lesson, _, _, path = published
    db_session.refresh(lesson)
    assert _snapshot(lesson) == before
    assert Lessons.query.filter_by(module_id=lesson.module_id, type='grammar').count() == 1
    assert 'Published synthetic theory' in _editor_page(client.get(path)).select_one('#guided-body-1').text


@pytest.mark.parametrize('entry', [*JSON_PATHS, 'zip', 'legacy'])
def test_regular_import_updates_neighbour_and_same_fk_final(
    admin_client: FlaskClient, db_session: scoped_session, published_module: tuple, entry: str,
) -> None:
    lesson, final, neighbour, _ = published_module
    before = _snapshot(lesson)
    source = _source(published_module, key='synthetic-guided' if entry == JSON_PATHS[0] else None)
    if entry == 'zip':
        page = _page(admin_client, _upload(admin_client, {'module.json': source}))
        assert f'Пошаговый урок №1 сохранится без изменений · {lesson.title}' in page.get_text()
        assert neighbour.content['text'] == 'Original neighbour.'
        done = _page(admin_client, admin_client.post(APPLY, data={'preview_id': _preview_id(page)}))
        assert 'применён' in done.get_text()
    elif entry == 'legacy':
        legacy_import(source)
    else:
        body = _post_json(admin_client, entry, source)
        assert 'успешно импортирован' in body or 'Импортировано 1 из 1 файлов' in body
    _assert_guided_unchanged(admin_client, db_session, published_module, before)
    db_session.refresh(neighbour)
    db_session.refresh(final)
    assert neighbour.content['text'] == 'Imported neighbour.'
    assert final.grammar_topic_id == lesson.grammar_topic_id
    questions = final.content['exercises'] if entry == 'legacy' else final.content['test_sections'][0]['exercises']
    assert questions[0]['question'] == 'Imported final question.'


@pytest.mark.parametrize(('entry', 'conflict'), [
    (JSON_PATHS[0], 'type'), (JSON_PATHS[1], 'key'), ('zip', 'position'), ('legacy', 'key'),
])
def test_conflict_keeps_the_entire_module(
    admin_client: FlaskClient, db_session: scoped_session, published_module: tuple, entry: str, conflict: str,
) -> None:
    lesson, final, neighbour, _ = published_module
    before = _snapshot(lesson)
    source = _source(published_module, key='synthetic-guided')
    source['title'] = 'Must not be applied'
    row = source['lessons'][1]
    if conflict == 'type':
        row['type'] = 'text'
    elif conflict == 'position':
        row['lesson_number'] = 4
    else:
        row['content']['external_key'] = 'another-lesson'

    message = 'конфликтует с опубликованным пошаговым уроком'
    if entry == 'zip':
        page = _page(admin_client, _upload(admin_client, {'module.json': source}))
        assert page.select_one('input[name="preview_id"]') is None
        assert message in page.get_text()
    elif entry == 'legacy':
        with pytest.raises(ValueError, match=message):
            legacy_import(source)
        db_session.rollback()
    else:
        assert message in _post_json(admin_client, entry, source)
    _assert_guided_unchanged(admin_client, db_session, published_module, before)
    assert neighbour.content['text'] == 'Original neighbour.'
    assert final.content['test_sections'][0]['exercises'][0]['question'] == 'Original final question.'
    assert lesson.module.title == 'Synthetic module'


def test_new_guided_publication_stales_module_zip(
    admin_client: FlaskClient, db_session: scoped_session, published_module: tuple, installed_topic: tuple,
) -> None:
    lesson, _, neighbour, _ = published_module
    # The package only edits the neighbour. An omitted guided lesson is still
    # shown and covered by the module fingerprint.
    source = _source(published_module)
    del source['lessons'][1]
    page = _page(admin_client, _upload(admin_client, {'module.json': source}))
    token = _preview_id(page)
    assert 'Пошаговый урок №1 сохранится без изменений' in page.get_text()
    _publish(admin_client, installed_topic, 'two')
    before = _snapshot(lesson)
    stale = _page(admin_client, admin_client.post(APPLY, data={'preview_id': token}))
    assert 'Содержимое изменилось после просмотра' in stale.get_text()
    assert neighbour.content['text'] == 'Original neighbour.'

    fresh = _preview_id(_page(admin_client, _upload(admin_client, {'module.json': source})))
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': fresh}))
    _assert_guided_unchanged(admin_client, db_session, published_module, before)
    assert neighbour.content['text'] == 'Imported neighbour.'
