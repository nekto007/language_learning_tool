"""Preserve both chapter wire shapes while publishing the edition's text-access receipt."""

import gzip
import json
from datetime import date

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token
from sqlalchemy.orm import Session

from app.auth.models import User
from app.books.models import Book, Chapter

BODY = 'One small step. Two small steps. Three small steps. Four small steps.'
BASE_DENIAL = {'success': False, 'error': 'forbidden', 'message': 'Access denied', 'status': 403}


@pytest.fixture
def edition(db_session: Session) -> tuple[Book, Chapter]:
    book = Book(slug='text-access-receipt', title='Synthetic edition', author='Fixture author',
                chapters_cnt=1, rights_status='licensed', is_free_access=True)
    chapter = Chapter(book=book, chap_num=1, title='One', text_raw=BODY, words=12)
    db_session.add(chapter)
    db_session.flush()
    return book, chapter


@pytest.mark.parametrize('percent,expected', [(0, ''), (25, 'One small step.'), (100, BODY)])
def test_both_chapter_receipts_match_the_reader_projection(
    authenticated_client: FlaskClient, db_session: Session, edition: tuple[Book, Chapter],
    percent: int, expected: str,
) -> None:
    book, chapter = edition
    book.allowed_text_percent = percent
    db_session.commit()
    path = f'/api/books/{book.id}/chapters/1'
    response = authenticated_client.get(path)
    assert response.status_code == 200
    document = response.json
    assert document['id'] == chapter.id and document['text'] == expected
    assert document['text_truncated'] is (percent < 100)
    assert document['text_access'] == {
        'book_id': book.id, 'effective_percent': percent,
        'projection': 'reader', 'policy_revision': str(book.text_policy_revision),
    }
    encoded = authenticated_client.get(path, headers={'Accept-Encoding': 'gzip'})
    assert encoded.status_code == 200 and encoded.headers['Content-Encoding'] == 'gzip'
    assert json.loads(gzip.decompress(encoded.data)) == document
    by_id = authenticated_client.get(f'/api/chapters/{chapter.id}')
    assert by_id.status_code == 200
    assert by_id.json['chapter']['text_raw'] == expected
    assert by_id.json['chapter']['text_truncated'] == document['text_truncated']
    assert by_id.json['chapter']['text_access'] == document['text_access']


def test_admin_and_public_domain_receive_full_projection(
    app: Flask, test_user: User, admin_user: User, db_session: Session, edition: tuple[Book, Chapter],
) -> None:
    book, chapter = edition
    book.allowed_text_percent = 0
    db_session.commit()
    admin_token = create_access_token(identity=str(admin_user.id), additional_claims={'auth_version': admin_user.auth_version()})
    learner_token = create_access_token(identity=str(test_user.id), additional_claims={'auth_version': test_user.auth_version()})
    admin_headers = {'Authorization': f'Bearer {admin_token}'}
    learner_headers = {'Authorization': f'Bearer {learner_token}'}
    client = app.test_client()
    privileged = client.get(f'/api/books/{book.id}/chapters/1', headers=admin_headers)
    assert privileged.status_code == 200 and privileged.json['text'] == BODY
    assert privileged.json['text_access']['effective_percent'] == 100

    book.rights_status = 'public_domain'
    db_session.commit()
    for headers, projection in ((learner_headers, 'reader'), (admin_headers, 'admin')):
        by_number = client.get(f'/api/books/{book.id}/chapters/1', headers=headers)
        by_id = client.get(f'/api/chapters/{chapter.id}', headers=headers)
        assert by_number.status_code == by_id.status_code == 200
        receipt = {'book_id': book.id, 'effective_percent': 100,
                   'projection': projection, 'policy_revision': str(book.text_policy_revision)}
        assert by_number.json['text_access'] == by_id.json['chapter']['text_access'] == receipt
        assert by_number.json['text'] == by_id.json['chapter']['text_raw'] == BODY
        assert not by_number.json['text_truncated'] and not by_id.json['chapter']['text_truncated']


def test_only_numeric_chapter_text_rights_denial_has_receipt(
    app: Flask, authenticated_client: FlaskClient, db_session: Session, edition: tuple[Book, Chapter],
) -> None:
    book, chapter = edition
    book_id, chapter_id = book.id, chapter.id
    numeric = f'/api/books/{book_id}/chapters'
    slug = f'/api/books/{book.slug}/chapters'
    by_id = f'/api/chapters/{chapter_id}'
    for path in (numeric, slug):
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert response.json == [{'id': chapter_id, 'num': 1, 'title': 'One', 'words': 12, 'audio_url': None}]

    assert authenticated_client.get(numeric + '/99').status_code == 404
    book.expiration_date = date(2000, 1, 1)
    db_session.commit()
    denied = authenticated_client.get(numeric + '/1')
    assert denied.status_code == 403
    assert denied.json == BASE_DENIAL | {
        'text_access': {'book_id': book_id, 'policy_revision': str(book.text_policy_revision), 'decision': 'denied'},
    }
    for path in (numeric, slug, by_id):
        response = authenticated_client.get(path)
        assert response.status_code == 403 and response.json == BASE_DENIAL

    book.is_published = False
    db_session.commit()
    hidden = authenticated_client.get(numeric + '/1')
    assert hidden.status_code == 404 and 'text_access' not in hidden.json
    g.pop('_login_user', None)
    assert app.test_client().get(numeric + '/1').status_code == 401
