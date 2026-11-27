"""A configured Grammar Lab example follows the visible, verified paragraph."""

from json import dumps
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from flask import Flask, g, url_for
from flask.testing import FlaskClient
from pytest import MonkeyPatch
from sqlalchemy.orm import scoped_session

from app.books.models import Book, Chapter
from app.grammar_lab.models import GrammarExercise, GrammarTopic


def _example_link(client: FlaskClient, path: str) -> str | None:
    response = client.get(path)
    assert response.status_code == 200
    link = BeautifulSoup(response.data, 'html.parser').select_one('[data-grammar-book-example]')
    return link['href'] if link else None


def test_example_links_follow_moved_quote_and_hide_removed_or_closed_text(
    app: Flask, authenticated_client: FlaskClient, db_session: scoped_session, monkeypatch: MonkeyPatch,
) -> None:
    quote = 'The visitors had brought some maps.'
    topic = GrammarTopic(slug='synthetic-perfect', title='Earlier action', title_ru='Earlier action',
                         level='B1', content={})
    item = Book(slug='synthetic-open', title='Open travel notes', author='Synthetic', level='B1',
                is_published=True, rights_status='public_domain', chapters_cnt=1)
    chapter = Chapter(book=item, chap_num=1, title='Departure', words=20, text_raw=f'{quote}\n\nWe left before dawn.')
    db_session.add_all([topic, item, chapter])
    db_session.flush()
    db_session.add(GrammarExercise(topic_id=topic.id, exercise_type='fill_blank',
                                   content={'question': 'She ___ a map earlier.', 'correct_answer': 'had drawn'}))
    db_session.commit()
    with app.test_request_context():
        theory = url_for('grammar_lab.topic_detail', slug=topic.slug)
        practice = url_for('grammar_lab.practice', topic_id=topic.id, return_url='/dashboard')
    assert _example_link(authenticated_client, theory) is None
    monkeypatch.setitem(app.config, 'GRAMMAR_BOOK_EXAMPLE',
                        dumps({'topic': topic.slug, 'book': item.slug, 'chapter': 1, 'quote': quote}))
    old = _example_link(authenticated_client, theory)
    from_practice = _example_link(authenticated_client, practice)
    assert parse_qs(urlsplit(from_practice).query)['from'] == [practice]
    assert parse_qs(urlsplit(old).query)['reader_paragraph'] == ['0']
    response = authenticated_client.get(from_practice)
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    example = page.find(id='reader-grammar-example')
    assert example['data-paragraph'] == '0'
    assert example.find('a')['href'] == theory
    assert page.select_one('.rdr-back-btn')['href'] == practice
    assert page.select_one('.rdr-back-btn')['aria-label'] == 'К практике'  # noqa: RUF001 -- Russian label.

    chapter.text_raw = 'A short opening.\n\n' + chapter.text_raw
    db_session.commit()
    moved = _example_link(authenticated_client, theory)
    assert parse_qs(urlsplit(moved).query)['reader_paragraph'] == ['1']
    reader = authenticated_client.get(old)
    assert reader.status_code == 200 and b'const requestedParagraph = 1;' in reader.data
    assert BeautifulSoup(reader.data, 'html.parser').select_one('#reader-grammar-example')['data-paragraph'] == '1'

    for text in ('Only the opening remains.', f'{quote}\n\n{quote}'):
        chapter.text_raw = text
        db_session.commit()
        assert _example_link(authenticated_client, theory) is None
        assert _example_link(authenticated_client, practice) is None
        reader = authenticated_client.get(old)
        assert reader.status_code == 200 and b'const requestedParagraph = null;' in reader.data
        assert not BeautifulSoup(reader.data, 'html.parser').select_one('#reader-grammar-example')

    chapter.text_raw = quote
    item.rights_status = 'companion_only'
    db_session.commit()
    assert _example_link(authenticated_client, theory) is None
    assert authenticated_client.get(old).status_code == 403
    item.rights_status = 'public_domain'
    item.is_published = False
    db_session.commit()
    assert _example_link(authenticated_client, theory) is None
    assert authenticated_client.get(old).status_code == 404
    g.pop('_login_user', None)
    guest = app.test_client()
    assert _example_link(guest, theory) is None
