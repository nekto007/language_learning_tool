"""Book metadata obeys the same publication/rights gates as chapter text.

Only synthetic rows in the existing guarded test database are used here.
"""
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from flask import has_request_context, jsonify

from app.books.access import visible_books_filter
from app.books.models import Book, Bookmark, Chapter, UserChapterProgress
from app.modules.models import SystemModule, UserModule
from app.words.models import CollectionWords, word_book_link
from tests.words.test_query_bounds import words_module_access as _words_module_access


@pytest.fixture
def words_module_access(db_session, test_user):
    return _words_module_access.__wrapped__(db_session, test_user)


def _background(app, function, user_id):
    def run():
        with app.app_context():
            assert not has_request_context()
            return function(user_id, tz='UTC')
    # The suite fixture pushes a request context on its own thread. A real
    # background thread verifies the bot never relies on that identity.
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(run).result(timeout=20)


def _grant(session, user, enabled):
    module = SystemModule.query.filter_by(code='books').first()
    if module is None:
        module = SystemModule(code='books', name='Books', is_active=True, is_default=False)
        session.add(module)
        session.flush()
    row = UserModule.query.filter_by(user_id=user.id, module_id=module.id).first()
    if row is None:
        row = UserModule(user_id=user.id, module_id=module.id)
        session.add(row)
    row.is_enabled = enabled
    session.flush()


@pytest.fixture
def privacy_books(db_session, test_user):
    _grant(db_session, test_user, False)
    marker = uuid4().hex[:8]
    books = {}
    for name, published, rights, expired in [
        ('public', True, 'public_domain', False),
        ('draft', False, 'public_domain', False),
        ('restricted', True, 'licensed', False),
        ('expired', True, 'licensed', True),
    ]:
        book = Book(title=f'{name}_{marker}', author='Synthetic', chapters_cnt=1,
                    is_published=published, rights_status=rights, level='A1',
                    expiration_date=(datetime.now(UTC).date() - timedelta(days=1)) if expired else None)
        db_session.add(book)
        books[name] = book
    word = CollectionWords(english_word=f'privacy_{marker}', russian_word='пример', level='A1', item_type='word')
    db_session.add(word)
    db_session.flush()
    for book in books.values():
        chapter = Chapter(book_id=book.id, chap_num=1, title='Synthetic chapter', words=3, text_raw='Synthetic text.')
        db_session.add(chapter)
        db_session.execute(word_book_link.insert().values(book_id=book.id, word_id=word.id, frequency=7))
    db_session.commit()
    return books, word


@pytest.mark.parametrize('actor,expected', [
    ('regular', {'public'}), ('entitled', {'public', 'restricted'}),
    ('admin', {'public', 'draft', 'restricted', 'expired'}), ('anonymous', set()),
])
def test_shared_visibility_matches_chapter_policy(app, db_session, test_user, privacy_books, actor, expected):
    from flask_login import AnonymousUserMixin
    books, _ = privacy_books
    if actor == 'entitled':
        _grant(db_session, test_user, True)
    if actor == 'admin':
        test_user.is_admin = True
    user = AnonymousUserMixin() if actor == 'anonymous' else test_user
    ids = {row.id for row in Book.query.filter(visible_books_filter(user)).all()}
    assert {key for key, book in books.items() if book.id in ids} == expected


@pytest.mark.parametrize('actor', ['regular', 'entitled', 'admin'])
def test_word_form_and_detail_hide_inaccessible_metadata(
    app, db_session, authenticated_client, test_user, privacy_books, words_module_access, monkeypatch, actor,
):
    from app.words.forms import WordFilterForm
    books, word = privacy_books
    test_user.is_admin = actor == 'admin'
    if actor == 'entitled':
        _grant(db_session, test_user, True)
    db_session.commit()
    expected = set(books) if actor == 'admin' else {'public', 'restricted'} if actor == 'entitled' else {'public'}
    with app.test_request_context():
        form = WordFilterForm(user=test_user)
    assert {name for name, book in books.items() if book.id in dict(form.book_id.choices)} == expected
    response = authenticated_client.get(f'/api/words/{word.id}')
    assert response.status_code == 200, response.json
    returned = {row['id'] for row in response.json['books']}
    assert {name for name, book in books.items() if book.id in returned} == expected
    assert all(row['frequency'] == 7 for row in response.json['books'])

    def rendered(template, **context):
        if template.endswith('details_optimized.html'):
            return jsonify(ids=[book.id for book, frequency in context['books']])
        return jsonify(ids=[book.id for item in context['words'].items for book in item.books])
    monkeypatch.setattr('app.words.routes.render_template', rendered)
    for path in (f'/words/{word.id}', f'/words?search={word.english_word}'):
        response = authenticated_client.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)
        returned = set(response.json['ids'])
        assert {name for name, book in books.items() if book.id in returned} == expected


@pytest.mark.parametrize('surface', ['/words', '/api/words'])
@pytest.mark.parametrize('kind', ['draft', 'restricted', 'expired'])
def test_guessing_hidden_book_does_not_reveal_its_vocabulary(
    authenticated_client, privacy_books, words_module_access, surface, kind,
):
    books, _ = privacy_books
    assert authenticated_client.get(f'{surface}?book_id={books[kind].id}').status_code == 404
    assert authenticated_client.get(f'{surface}?book_id={books["public"].id}').status_code == 200


@pytest.mark.parametrize('kind,status', [('draft', 404), ('restricted', 403), ('expired', 403)])
def test_bookmark_rejects_inaccessible_book_before_writing(authenticated_client, privacy_books, kind, status):
    books, _ = privacy_books
    before = Bookmark.query.count()
    response = authenticated_client.post('/api/bookmarks', json={'book_id': books[kind].id, 'name': 'Private note'})
    assert response.status_code == status, response.json
    assert Bookmark.query.count() == before


@pytest.mark.parametrize('actor', ['regular', 'entitled', 'admin'])
def test_bookmark_positive_and_ownership_is_current_account(
    db_session, authenticated_client, test_user, privacy_books, actor,
):
    books, _ = privacy_books
    test_user.is_admin = actor == 'admin'
    if actor == 'entitled':
        _grant(db_session, test_user, True)
    db_session.commit()
    book = books[{'admin': 'draft', 'entitled': 'restricted', 'regular': 'public'}[actor]]
    response = authenticated_client.post('/api/bookmarks', json={'book_id': book.id, 'name': 'My note', 'user_id': -1})
    assert response.status_code == 200, response.json
    row = db_session.get(Bookmark, response.json['id'])
    assert (row.user_id, row.book_id) == (test_user.id, book.id)


@pytest.mark.parametrize('admin', [False, True])
def test_draft_queue_does_not_bypass_publication_gate(
    db_session, authenticated_client, test_user, privacy_books, admin,
):
    from app.study.models import UserWord
    books, word = privacy_books
    test_user.is_admin = admin
    db_session.commit()
    response = authenticated_client.post(f'/books/{books["draft"].id}/add-to-queue')
    assert response.status_code == (302 if admin else 404)
    assert (UserWord.query.filter_by(user_id=test_user.id, word_id=word.id).first() is not None) == admin


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('actor,expected', [
    ('regular', {'public'}), ('entitled', {'public', 'restricted'}),
    ('admin', {'public', 'draft', 'restricted', 'expired'}),
])
def test_background_plan_suggestions_and_counts_use_recipient_rights(
    app, db_session, test_user, privacy_books, version, actor, expected,
):
    from app.telegram.queries import get_daily_plan, get_daily_plan_v2
    books, _ = privacy_books
    test_user.is_admin = actor == 'admin'
    if actor == 'entitled':
        _grant(db_session, test_user, True)
    db_session.commit()
    plan = _background(app, get_daily_plan if version == 1 else get_daily_plan_v2, test_user.id)
    available = plan['onboarding']['available_books']
    returned = {row['id'] for row in available}
    assert {key for key, book in books.items() if book.id in returned} == expected
    assert plan['onboarding']['total_books'] == len(expected)
    suggested = {row['id'] for row in plan['suggested_books']}
    assert suggested <= returned


@pytest.mark.parametrize('version', [1, 2])
def test_background_continuation_skips_revoked_started_books(app, db_session, test_user, privacy_books, version):
    from app.telegram.queries import get_daily_plan, get_daily_plan_v2
    books, _ = privacy_books
    for name in ('draft', 'restricted', 'expired'):
        chapter = Chapter.query.filter_by(book_id=books[name].id).one()
        db_session.add(UserChapterProgress(user_id=test_user.id, chapter_id=chapter.id, offset_pct=.1,
                                          updated_at=datetime.now(UTC) - timedelta(days=1)))
    db_session.commit()
    plan = _background(app, get_daily_plan if version == 1 else get_daily_plan_v2, test_user.id)
    assert plan['book_to_read'] is None
    assert {row['id'] for row in plan['suggested_books']} == {books['public'].id}


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('kind', ['public', 'draft', 'restricted', 'expired'])
@pytest.mark.parametrize('actor', ['regular', 'entitled', 'admin'])
def test_background_course_metadata_obeys_parent_book_gate(
    app, db_session, test_user, privacy_books, version, kind, actor,
):
    from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule
    from app.curriculum.daily_lessons import DailyLesson
    from app.telegram.queries import get_daily_plan, get_daily_plan_v2
    books, _ = privacy_books
    book = books[kind]
    test_user.is_admin = actor == 'admin'
    if actor == 'entitled':
        _grant(db_session, test_user, True)
    course = BookCourse(book_id=book.id, title=book.title, level='A1')
    db_session.add(course)
    db_session.flush()
    module = BookCourseModule(course_id=course.id, module_number=1, title='Synthetic module')
    db_session.add(module)
    db_session.flush()
    chapter = Chapter.query.filter_by(book_id=book.id).one()
    db_session.add_all([
        DailyLesson(book_course_module_id=module.id, slice_number=1, day_number=1,
                    lesson_type='reading', chapter_id=chapter.id),
        BookCourseEnrollment(user_id=test_user.id, course_id=course.id, status='active'),
    ])
    db_session.commit()
    plan = _background(app, get_daily_plan if version == 1 else get_daily_plan_v2, test_user.id)
    allowed = actor == 'admin' or kind == 'public' or (actor == 'entitled' and kind == 'restricted')
    assert (plan['book_course_lesson'] is not None) == allowed
    if allowed:
        assert plan['book_course_lesson']['course_title'] == book.title
    else:
        assert book.title not in str(plan)


def test_bookmark_listing_is_account_scoped(db_session, authenticated_client, test_user, privacy_books):
    from app.auth.models import User
    books, _ = privacy_books
    other = User(username='other_' + uuid4().hex[:8], email=uuid4().hex + '@example.invalid', active=True)
    other.set_password('synthetic-book-privacy-test-only')
    db_session.add(other)
    db_session.flush()
    db_session.add_all([
        Bookmark(user_id=other.id, book_id=books['public'].id, name='foreign secret', context='foreign context'),
        Bookmark(user_id=test_user.id, book_id=books['public'].id, name='own note', context='own context'),
    ])
    db_session.commit()
    response = authenticated_client.get(f'/api/bookmarks/{books["public"].id}')
    assert response.status_code == 200
    assert [row['name'] for row in response.json] == ['own note']
    assert 'foreign' not in response.get_data(as_text=True)
