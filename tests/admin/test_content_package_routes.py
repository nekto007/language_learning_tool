"""Exercise both steps of the content ZIP import through its admin forms."""

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse as HTTPResponse

from app.admin.audit import AdminAuditLog
from app.admin.routes import content_packages
from app.admin.utils import import_helpers
from app.auth.models import User
from app.curriculum.models import Lessons, Module

INDEX = '/admin/content-packages'
APPLY = f'{INDEX}/apply'


def _content(key: str, question: str) -> dict[str, Any]:
    return {
        'external_key': key,
        'test_sections': [{'title': 'Грамматика', 'exercises': [{
            'type': 'multiple_choice', 'question': question,
            'options': ['this', 'these'], 'correct': 'these',
        }]}],
        'exercises': [], 'passing_score': 75, 'total_points': 100, 'xp_reward': 200,
    }


@pytest.fixture
def staged_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
    return tmp_path


@pytest.fixture
def finals(db_session: scoped_session, test_module: Module) -> list[Lessons]:
    lessons = []
    for number in (18, 19):
        key = f'curriculum:final_test:{test_module.level.code}:{test_module.number:02}:forms-{number}'
        lessons.append(Lessons(
            module_id=test_module.id, number=number, type='final_test',
            title=f'Итоговый тест {number}', content=_content(key, 'Старый вопрос'),
        ))
    db_session.add_all(lessons)
    db_session.commit()
    return lessons


def _updated(lesson: Lessons, question: str = 'Выбери слово для нескольких предметов.') -> dict[str, Any]:
    return _content(lesson.content['external_key'], question)


def _upload(
    client: FlaskClient, documents: dict[str, dict | str], *, csrf: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPResponse:
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        for name, value in documents.items():
            archive.writestr(name, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    stream.seek(0)
    form = {'file': (stream, 'update.zip')}
    if csrf is not None:
        form['csrf_token'] = csrf
    return client.post(INDEX, data=form, headers=headers)


def _page(client: FlaskClient, redirect: HTTPResponse) -> BeautifulSoup:
    assert redirect.status_code == 303
    assert urlsplit(redirect.location).path == INDEX
    response = client.get(redirect.location)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def _preview_id(page: BeautifulSoup) -> str:
    field = page.select_one(f'form[action="{APPLY}"] input[name="preview_id"]')
    assert field is not None, page.get_text(' ', strip=True)
    assert field['value']
    return str(field['value'])


def _audit_count(admin: User) -> int:
    return AdminAuditLog.query.filter_by(admin_id=admin.id, action='content_package.apply').count()


def test_admin_previews_and_confirms_once(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session,
    staged_files: Path, finals: list[Lessons],
) -> None:
    lesson = finals[0]
    old, new = lesson.content, _updated(lesson)
    page = _page(admin_client, _upload(admin_client, {'course/final.json': new}))
    preview_id = _preview_id(page)
    assert 'update.zip' in page.get_text()
    row = page.select_one('[data-package-row]')
    assert row and 'course/final.json' in row.get_text() and lesson.title in row.get_text()
    assert 'Заданий в тесте — 1' in row.get_text(' ', strip=True)
    assert 'Заданий в отдельных тестах' in page.select_one('dl[aria-label="Сводка пакета"]').get_text(' ', strip=True)
    assert list(staged_files.iterdir())
    db_session.refresh(lesson)
    assert lesson.content == old and _audit_count(admin_user) == 0

    staged_path, = staged_files.iterdir()
    staged_bytes = staged_path.read_bytes()
    assert admin_client.head(INDEX).status_code == 200
    assert staged_path.read_bytes() == staged_bytes
    confirmation = {'preview_id': preview_id}
    done = _page(admin_client, admin_client.post(APPLY, data=confirmation))
    assert done.select_one('input[name="preview_id"]') is None
    assert 'Заданий в отдельных тестах — 1' in done.select_one('[role=alert]').get_text()
    audit = done.select_one('a[href*="action=content_package.apply"]')
    assert urlsplit(audit['href']).path == '/admin/audit-log'
    assert b'content_package.apply' in admin_client.get(audit['href']).data
    db_session.refresh(lesson)
    assert lesson.content == new and _audit_count(admin_user) == 1
    assert not list(staged_files.iterdir())

    _page(admin_client, admin_client.post(APPLY, data=confirmation))
    db_session.refresh(lesson)
    assert lesson.content == new and _audit_count(admin_user) == 1


def test_content_and_translation_previews_have_separate_storage(
    admin_client: FlaskClient, staged_files: Path, finals: list[Lessons],
) -> None:
    translations = {'translations': [{'english': 'book', 'russian': 'книга'}]}
    translation_id = import_helpers.save_import_data(translations)
    preview_id = _preview_id(_page(admin_client, _upload(admin_client, {'final.json': _updated(finals[0])})))
    assert import_helpers.load_import_data(preview_id) is None
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    assert import_helpers.load_import_data(translation_id) == translations
    assert list(staged_files.glob('curriculum-*.json')) == []


def test_mixed_archive_summary_keeps_lesson_and_question_units_separate(
    admin_client: FlaskClient, finals: list[Lessons], staged_files: Path,
) -> None:
    existing = finals[0]
    content = _updated(existing)
    content['test_sections'][0]['exercises'].append({
        'type': 'multiple_choice', 'question': 'Pick a shape.',
        'options': ['a square', 'a circle'], 'correct': 'a circle',
    })
    module = {'module': {
        'level': 'A1', 'number': 8820, 'title': 'New shapes',
        'lessons': [{'order': 1, 'type': 'final_test', 'title': 'Shapes',
                     'content': _content('new:shapes:final', 'Pick a shape.')}],
    }}
    page = _page(admin_client, _upload(admin_client, {'module.json': module, 'final.json': content}))
    summary = page.select_one('dl[aria-label="Сводка пакета"]')
    assert summary is not None, page.get_text(' ', strip=True)
    counts = {item.dt.get_text(strip=True): item.dd.get_text(strip=True) for item in summary.select('div')}
    assert counts == {'Файлов': '2', 'Модулей': '1', 'Уроков в модулях': '1',
                      'Отдельных итоговых тестов': '1', 'Заданий в отдельных тестах': '2'}


def test_confirmation_losing_file_claim_skips_apply_and_audit(
    admin_client: FlaskClient, admin_user: User, staged_files: Path,
    finals: list[Lessons], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Identical content still has the previewed fingerprint after the winning request commits.
    preview = _page(admin_client, _upload(admin_client, {'final.json': finals[0].content}))
    preview_id = _preview_id(preview)

    def lose_claim(import_id: str, *, prefix: str) -> bool:
        assert import_id == preview_id
        assert import_helpers.delete_import_data(import_id, prefix=prefix)
        return False

    apply = Mock(wraps=content_packages.apply_package)
    monkeypatch.setattr(content_packages, 'apply_package', apply)
    monkeypatch.setattr(content_packages, 'delete_import_data', lose_claim)
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    assert not list(staged_files.iterdir())
    apply.assert_not_called()
    assert _audit_count(admin_user) == 0


@pytest.mark.parametrize('invalid_file', ['run.py', 'second-final.json'])
def test_rejects_code_or_duplicate_target_without_staging(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session,
    staged_files: Path, finals: list[Lessons], invalid_file: str,
) -> None:
    lesson = finals[0]
    old, new = lesson.content, _updated(lesson)
    documents = {'final.json': new, invalid_file: '# code' if invalid_file.endswith('.py') else new}
    page = _page(admin_client, _upload(admin_client, documents))
    assert page.select_one('input[name="preview_id"]') is None
    assert not list(staged_files.iterdir())
    db_session.refresh(lesson)
    assert lesson.content == old and _audit_count(admin_user) == 0


def test_change_to_one_of_two_lessons_invalidates_whole_preview(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session,
    staged_files: Path, finals: list[Lessons],
) -> None:
    first, second = finals
    first_old = first.content
    documents = {'first.json': _updated(first), 'second.json': _updated(second)}
    preview_id = _preview_id(_page(admin_client, _upload(admin_client, documents)))
    edited = _updated(second, 'Вопрос уже отредактировал другой преподаватель.')
    second.content = edited
    db_session.commit()

    _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.content == first_old and second.content == edited
    assert _audit_count(admin_user) == 0


def test_older_preview_form_cannot_apply_replacement_archive(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session,
    staged_files: Path, finals: list[Lessons],
) -> None:
    lesson = finals[0]
    old = lesson.content
    first = _preview_id(_page(admin_client, _upload(admin_client, {'final.json': _updated(lesson)})))
    replacement = _updated(lesson, 'Выбери множественное число.')
    second = _preview_id(_page(admin_client, _upload(admin_client, {'revised.json': replacement})))
    assert second != first
    page = _page(admin_client, admin_client.post(APPLY, data={'preview_id': first}))
    assert _preview_id(page) == second
    db_session.refresh(lesson)
    assert lesson.content == old and _audit_count(admin_user) == 0
    _page(admin_client, admin_client.post(APPLY, data={'preview_id': second}))
    db_session.refresh(lesson)
    assert lesson.content == replacement and _audit_count(admin_user) == 1
    assert not list(staged_files.iterdir())


def test_preview_scoped_to_admin_and_session(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User,
    db_session: scoped_session, staged_files: Path, finals: list[Lessons],
) -> None:
    lesson = finals[0]
    old, new = lesson.content, _updated(lesson)
    preview_id = _preview_id(_page(admin_client, _upload(admin_client, {'final.json': new})))
    other_session = app.test_client()
    with other_session.session_transaction() as session:
        session['_user_id'] = admin_user.get_id()
        session['_fresh'] = True
    _page(other_session, other_session.post(APPLY, data={'preview_id': preview_id}))
    db_session.refresh(lesson)
    assert lesson.content == old and _audit_count(admin_user) == 0

    test_user.is_admin = True
    db_session.commit()
    with admin_client.session_transaction() as session:
        session['_user_id'] = test_user.get_id()
        session['user_id'] = test_user.id
    # db_session's shared application context also retains Flask-Login's request-local cache.
    g.pop('_login_user', None)
    page = _page(admin_client, admin_client.post(APPLY, data={'preview_id': preview_id}))
    assert page.select_one('input[name="preview_id"]') is None
    db_session.refresh(lesson)
    assert lesson.content == old
    assert _audit_count(admin_user) == _audit_count(test_user) == 0


@pytest.mark.parametrize('signed_in', [False, True], ids=['guest', 'student'])
def test_both_steps_require_admin(
    client: FlaskClient, test_user: User, staged_files: Path, signed_in: bool,
) -> None:
    if signed_in:
        with client.session_transaction() as session:
            session['_user_id'] = test_user.get_id()
            session['_fresh'] = True
    for response in (client.get(INDEX), client.post(INDEX), client.post(APPLY)):
        assert response.status_code == 302 and urlsplit(response.location).path.endswith('/login')
    assert not list(staged_files.iterdir())


def test_csrf_required_for_preview_and_confirmation(
    app: Flask, monkeypatch: pytest.MonkeyPatch, admin_client: FlaskClient,
    admin_user: User, db_session: scoped_session, staged_files: Path, finals: list[Lessons],
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    headers = {'Accept': 'application/json'}
    lesson = finals[0]
    old, new = lesson.content, _updated(lesson)
    rejected = _upload(admin_client, {'final.json': new}, headers=headers)
    assert rejected.status_code == 400 and rejected.json['csrf_expired']
    assert not list(staged_files.iterdir())

    upload = BeautifulSoup(admin_client.get(INDEX).data, 'html.parser')
    csrf = upload.select_one(f'form[action="{INDEX}"] input[name="csrf_token"]')['value']
    preview = _page(admin_client, _upload(admin_client, {'final.json': new}, csrf=csrf))
    preview_id = _preview_id(preview)
    confirmation = {'preview_id': preview_id}
    rejected = admin_client.post(APPLY, data=confirmation, headers=headers)
    assert rejected.status_code == 400 and rejected.json['csrf_expired']
    db_session.refresh(lesson)
    assert lesson.content == old and _audit_count(admin_user) == 0

    confirmation['csrf_token'] = preview.select_one(f'form[action="{APPLY}"] input[name="csrf_token"]')['value']
    _page(admin_client, admin_client.post(APPLY, data=confirmation))
    db_session.refresh(lesson)
    assert lesson.content == new and _audit_count(admin_user) == 1
