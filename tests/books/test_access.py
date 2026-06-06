"""Tests for per-book rights / module access control.

Covers ``app/books/access.py``:

* ``can_user_access_book`` for the four combinations:
  - admin bypass
  - public_domain → always accessible
  - licensed/companion_only → require ``books`` module
  - licensed + expired → blocked even with module
* ``accessible_books_filter`` — query expression returns the right rows
* Default ``rights_status`` on freshly-created Book is ``companion_only``
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.books.access import accessible_books_filter, can_user_access_book
from app.books.models import Book
from app.modules.models import SystemModule, UserModule


@pytest.fixture
def _books_module(db_session):
    mod = SystemModule.query.filter_by(code='books').first()
    if mod is None:
        mod = SystemModule(
            code='books', name='Книги', description='', icon='book-open',
            is_active=True, is_default=False, order=10,
        )
        db_session.add(mod)
        db_session.flush()
    return mod


def _enable_books_for(db_session, user, module):
    existing = UserModule.query.filter_by(
        user_id=user.id, module_id=module.id,
    ).first()
    if existing:
        existing.is_enabled = True
    else:
        db_session.add(UserModule(
            user_id=user.id, module_id=module.id,
            is_enabled=True, granted_by_admin=True,
        ))
    db_session.flush()


def _make_book(db_session, *, title='B', rights_status='companion_only', **extra):
    book = Book(
        title=title, author='A', level='A1', chapters_cnt=1,
        rights_status=rights_status, **extra,
    )
    db_session.add(book)
    db_session.flush()
    return book


class TestDefaults:
    def test_freshly_created_book_defaults_to_companion_only(self, db_session):
        book = Book(title='Fresh', author='A', level='A1', chapters_cnt=1)
        db_session.add(book)
        db_session.flush()
        assert book.rights_status == 'companion_only'
        assert book.audio_rights_status == 'companion_only'
        assert book.allowed_text_percent == 100
        assert book.commercial_use_allowed is False
        assert book.territory == 'worldwide'
        assert book.expiration_date is None


class TestCanUserAccessBook:
    def test_admin_passes_regardless_of_rights(self, app, db_session, admin_user):
        book = _make_book(db_session, rights_status='companion_only')
        assert can_user_access_book(admin_user, book) is True

    def test_public_domain_accessible_without_module(self, app, db_session, test_user, _books_module):
        # test_user has NO books module by default.
        book = _make_book(db_session, rights_status='public_domain')
        assert can_user_access_book(test_user, book) is True

    def test_companion_only_blocked_without_module(self, app, db_session, test_user, _books_module):
        book = _make_book(db_session, rights_status='companion_only')
        assert can_user_access_book(test_user, book) is False

    def test_licensed_blocked_without_module(self, app, db_session, test_user, _books_module):
        book = _make_book(db_session, rights_status='licensed')
        assert can_user_access_book(test_user, book) is False

    def test_companion_only_allowed_with_module(self, app, db_session, test_user, _books_module):
        _enable_books_for(db_session, test_user, _books_module)
        book = _make_book(db_session, rights_status='companion_only')
        assert can_user_access_book(test_user, book) is True

    def test_expired_licence_blocked_even_with_module(self, app, db_session, test_user, _books_module):
        _enable_books_for(db_session, test_user, _books_module)
        book = _make_book(
            db_session, rights_status='licensed',
            expiration_date=date.today() - timedelta(days=1),
        )
        assert can_user_access_book(test_user, book) is False

    def test_expired_public_domain_still_accessible(self, app, db_session, test_user, _books_module):
        # public_domain ignores expiration_date — copyright term is over.
        book = _make_book(
            db_session, rights_status='public_domain',
            expiration_date=date.today() - timedelta(days=365),
        )
        assert can_user_access_book(test_user, book) is True


class TestAccessibleBooksFilter:
    def test_no_module_user_sees_only_public_domain(self, app, db_session, test_user, _books_module):
        public = _make_book(db_session, title='PUB', rights_status='public_domain')
        _make_book(db_session, title='COM', rights_status='companion_only')
        _make_book(db_session, title='LIC', rights_status='licensed')

        rows = Book.query.filter(accessible_books_filter(test_user)).all()
        ids = {b.id for b in rows}
        assert public.id in ids
        assert len(ids) == 1

    def test_module_user_sees_all_non_expired(self, app, db_session, test_user, _books_module):
        _enable_books_for(db_session, test_user, _books_module)
        public = _make_book(db_session, title='PUB', rights_status='public_domain')
        companion = _make_book(db_session, title='COM', rights_status='companion_only')
        licensed = _make_book(db_session, title='LIC', rights_status='licensed')
        expired = _make_book(
            db_session, title='EXP', rights_status='licensed',
            expiration_date=date.today() - timedelta(days=1),
        )

        rows = Book.query.filter(accessible_books_filter(test_user)).all()
        ids = {b.id for b in rows}
        assert {public.id, companion.id, licensed.id} <= ids
        assert expired.id not in ids

    def test_admin_filter_sees_everything(self, app, db_session, admin_user):
        public = _make_book(db_session, title='PUB', rights_status='public_domain')
        companion = _make_book(db_session, title='COM', rights_status='companion_only')
        expired = _make_book(
            db_session, title='EXP', rights_status='licensed',
            expiration_date=date.today() - timedelta(days=1),
        )

        rows = Book.query.filter(accessible_books_filter(admin_user)).all()
        ids = {b.id for b in rows}
        assert {public.id, companion.id, expired.id} <= ids


class TestLicenseExpiryDateBasis:
    """license_is_expired (model) and accessible_books_filter (query) must use
    the SAME date basis — UTC — so the catalog and the open-book gate agree
    (finding #16). Both treat the expiration_date day itself as still valid."""

    def test_model_and_filter_agree_on_utc_boundary(
        self, app, db_session, test_user, _books_module
    ):
        from datetime import datetime, timezone

        _enable_books_for(db_session, test_user, _books_module)
        utc_today = datetime.now(timezone.utc).date()

        expiring_today = _make_book(
            db_session, title='TODAY', rights_status='licensed',
            expiration_date=utc_today,
        )
        expired_yesterday = _make_book(
            db_session, title='YESTERDAY', rights_status='licensed',
            expiration_date=utc_today - timedelta(days=1),
        )
        db_session.commit()

        # Model check (used by can_user_access_book on /read open).
        assert expiring_today.license_is_expired is False
        assert expired_yesterday.license_is_expired is True

        # Filter (used by the catalog listing) must agree row-for-row.
        ids = {b.id for b in Book.query.filter(accessible_books_filter(test_user)).all()}
        assert expiring_today.id in ids
        assert expired_yesterday.id not in ids

        # And can_user_access_book mirrors the model property.
        assert can_user_access_book(test_user, expiring_today) is True
        assert can_user_access_book(test_user, expired_yesterday) is False
