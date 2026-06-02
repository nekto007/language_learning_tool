"""Per-book access control built on top of the ``books`` module gate.

Rules:

* Admins always pass.
* ``rights_status='public_domain'`` books are accessible to every registered
  user, regardless of whether the optional ``books`` module is enabled for
  them. Public-domain titles have no expiration concept.
* ``licensed`` and ``companion_only`` titles still require the admin-granted
  ``books`` module *and* a non-expired licence.

Use :func:`can_user_access_book` for ad-hoc checks and
:func:`accessible_books_filter` to build a query expression that prunes a
``Book`` listing down to what the current user is allowed to see.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_

from app.books.models import Book
from app.modules.service import ModuleService

# Books module code lives in ``app/modules/migrations.py`` initial seed.
BOOKS_MODULE_CODE = 'books'


def books_section_visible(user) -> bool:
    """Should the user see the /books navigation link / catalog at all?

    A user with the ``books`` module is the obvious case. Users without the
    module still see the section if there is at least one published
    public-domain book — that single row is enough to make the catalog
    non-empty for them.
    """
    if getattr(user, 'is_admin', False):
        return True
    if _user_has_books_module(user):
        return True
    return Book.query.filter_by(
        is_published=True, rights_status='public_domain',
    ).first() is not None


def _user_has_books_module(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    return ModuleService.is_module_enabled_for_user(user.id, BOOKS_MODULE_CODE)


def can_user_access_book(user, book: Book) -> bool:
    """Return True if ``user`` is allowed to read ``book``.

    Does NOT consider ``Book.is_published`` — drafts are still hidden via
    the existing ``is_published`` check on the route layer. This function
    only answers the rights / module question.
    """
    if book is None:
        return False
    if getattr(user, 'is_admin', False):
        return True
    if book.rights_status == 'public_domain':
        return True
    # licensed / companion_only paths
    if book.license_is_expired:
        return False
    return _user_has_books_module(user)


def accessible_books_filter(user) -> Any:
    """SQLAlchemy ``where`` expression matching books ``user`` can access.

    Combine with an ``is_published`` filter at the call site when listing for
    non-admins. Always returns an expression — never ``None`` — so the caller
    can ``query.where(accessible_books_filter(user))`` unconditionally.
    """
    if getattr(user, 'is_admin', False):
        # Admin: every row.
        return Book.id == Book.id

    public_domain = Book.rights_status == 'public_domain'
    if _user_has_books_module(user):
        licensed_ok = or_(
            Book.expiration_date.is_(None),
            Book.expiration_date >= date.today(),
        )
        return or_(public_domain, licensed_ok)
    return public_domain
