"""DP-033: the required reading slot must be gated by real book access.

The builder used to compose the slot from the ``UserReadingPreference`` alone,
so three states produced a required item that leads straight into 403/404:

* a ``licensed`` book whose ``expiration_date`` has passed,
* any non-public-domain book after the ``books`` module was revoked,
* an unpublished draft.

``day_secured`` depends on every required item, so such a slot freezes the
streak, the ranks and the perfect-day bonus for the whole day.

The snapshot freezes required composition, so the builder gate only covers the
day the plan is composed. Access revoked *mid-day* is handled by
``overlay_completion``, which drops the now-unreachable slot instead of
crediting it.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.books.models import Book, Chapter
from app.daily_plan.items.reading import (
    _book_is_actionable_for_reading,
    book_access_ok_for_reading,
    build_reading_item,
    reading_preference_needs_setup,
)
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.snapshot import SNAPSHOT_VERSION, overlay_completion
from app.modules.models import SystemModule, UserModule
from app.utils.db import db as app_db
from tests.support_dates import study_today


@pytest.fixture
def books_module(db_session):
    mod = SystemModule.query.filter_by(code='books').first()
    if mod is None:
        mod = SystemModule(
            code='books', name='Книги', description='', icon='book-open',
            is_active=True, is_default=False, order=10,
        )
        db_session.add(mod)
        db_session.flush()
    return mod


def _grant_books_module(db_session, user, module):
    row = UserModule.query.filter_by(user_id=user.id, module_id=module.id).first()
    if row is None:
        row = UserModule(
            user_id=user.id, module_id=module.id,
            is_enabled=True, granted_by_admin=True,
        )
        db_session.add(row)
    else:
        row.is_enabled = True
    db_session.flush()


def _revoke_books_module(db_session, user, module):
    row = UserModule.query.filter_by(user_id=user.id, module_id=module.id).first()
    if row is not None:
        row.is_enabled = False
        db_session.flush()


def _make_book(db_session, *, rights_status='public_domain', is_published=True, **extra):
    book = Book(
        title='Тестовая книга', author='A', level='A1', chapters_cnt=1,
        rights_status=rights_status, is_published=is_published, **extra,
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(Chapter(
        book_id=book.id, chap_num=1, title='Глава 1',
        words=200, text_raw='word ' * 200,
    ))
    db_session.flush()
    return book


def _select_book(db_session, user, book, *, days_ago=1):
    """Pick ``book`` for ``user``, selected ``days_ago`` days back.

    Backdating matters for the required path: a book picked *today* is held
    back to optional by ``book_selected_today``, which would make the required
    slot vanish for a reason that has nothing to do with the access gate.
    """
    from app.utils.time_utils import get_user_local_day_bounds

    today_start, _ = get_user_local_day_bounds(user.id, app_db)
    selected_at = today_start - timedelta(days=days_ago - 1, seconds=1)
    pref = UserReadingPreference.query.filter_by(user_id=user.id).first()
    if pref is None:
        pref = UserReadingPreference(
            user_id=user.id, book_id=book.id, selected_at=selected_at,
        )
        db_session.add(pref)
    else:
        pref.book_id = book.id
        pref.selected_at = selected_at
    db_session.flush()
    return pref


def _reading_snapshot(book):
    return {
        'version': SNAPSHOT_VERSION,
        'date': study_today().isoformat(),
        'tier': 'normal',
        'rolled_over_from': None,
        'items': [
            {
                'id': 'curriculum:1',
                'kind': 'curriculum',
                'title': 'Урок',
                'data': {'lesson_id': 999999},
            },
            {
                'id': f'reading:book:{book.id}',
                'kind': 'reading',
                'title': book.title,
                'url': f'/read/{book.id}?from=linear_plan&slot=reading',
                'data': {'book_id': book.id},
            },
        ],
    }


class TestBuilderGate:
    """Три состояния, в которых слот вёл в 403/404 и день не закрывался."""

    def test_expired_licence_yields_no_reading_slot(
        self, app, db_session, test_user, books_module,
    ):
        _grant_books_module(db_session, test_user, books_module)
        book = _make_book(
            db_session,
            rights_status='licensed',
            expiration_date=study_today() - timedelta(days=1),
        )
        _select_book(db_session, test_user, book)

        assert book_access_ok_for_reading(test_user.id, book, app_db) is False
        assert _book_is_actionable_for_reading(test_user.id, book.id, app_db) is False
        assert build_reading_item(test_user.id, app_db) is None
        # The plan asks for a new book instead of freezing on a dead slot.
        assert reading_preference_needs_setup(test_user.id, app_db) is True

    def test_revoked_books_module_yields_no_reading_slot(
        self, app, db_session, test_user, books_module,
    ):
        book = _make_book(db_session, rights_status='companion_only')
        _grant_books_module(db_session, test_user, books_module)
        _select_book(db_session, test_user, book)
        # Sanity: with the module the slot exists at all.
        assert build_reading_item(test_user.id, app_db) is not None

        _revoke_books_module(db_session, test_user, books_module)
        assert book_access_ok_for_reading(test_user.id, book, app_db) is False
        assert build_reading_item(test_user.id, app_db) is None
        assert reading_preference_needs_setup(test_user.id, app_db) is True

    def test_unpublished_draft_yields_no_reading_slot(
        self, app, db_session, test_user, books_module,
    ):
        book = _make_book(db_session, rights_status='public_domain', is_published=False)
        _select_book(db_session, test_user, book)

        assert book_access_ok_for_reading(test_user.id, book, app_db) is False
        assert build_reading_item(test_user.id, app_db) is None
        assert reading_preference_needs_setup(test_user.id, app_db) is True

    def test_accessible_public_domain_book_still_builds(
        self, app, db_session, test_user, books_module,
    ):
        """Страж на нерегрессию: доступная книга слот по-прежнему даёт."""
        book = _make_book(db_session, rights_status='public_domain')
        _select_book(db_session, test_user, book)

        assert book_access_ok_for_reading(test_user.id, book, app_db) is True
        item = build_reading_item(test_user.id, app_db)
        assert item is not None
        assert item.data['book_id'] == book.id
        assert reading_preference_needs_setup(test_user.id, app_db) is False

    def test_admin_still_reads_own_draft(
        self, app, db_session, admin_user, books_module,
    ):
        """Админ видит черновики на роутах — план не должен быть строже."""
        book = _make_book(db_session, rights_status='companion_only', is_published=False)
        _select_book(db_session, admin_user, book)

        assert book_access_ok_for_reading(admin_user.id, book, app_db) is True
        assert build_reading_item(admin_user.id, app_db) is not None


class TestNoAccessibleBooksAtAll:
    """Подслучай на P0: без модуля `books` и без public-domain каталога
    переписать preference не на что — день обязан остаться закрываемым."""

    def test_day_is_closable_when_every_book_is_forbidden(
        self, app, db_session, test_user, books_module,
    ):
        _revoke_books_module(db_session, test_user, books_module)
        book = _make_book(db_session, rights_status='companion_only')
        _select_book(db_session, test_user, book)

        from app.daily_plan.plan_builder import _reading_item_dict

        # Ни билдер слота, ни снапшот required не получают недостижимый пункт.
        assert _reading_item_dict(test_user.id, app_db) is None
        assert build_reading_item(test_user.id, app_db) is None
        # Карточка выбора книги живёт в секции setup и day_secured не гейтит.
        from app.daily_plan.items.setup import build_setup_book_item
        assert build_setup_book_item().section == 'setup'


class TestSnapshotSelfHeal:
    """Гейт билдера закрывает только новый день.

    Доступ может пропасть внутри дня, когда required уже заморожен.
    """

    def test_revoked_midday_slot_is_dropped_from_required(
        self, app, db_session, test_user, books_module,
    ):
        book = _make_book(db_session, rights_status='companion_only')
        _grant_books_module(db_session, test_user, books_module)
        snapshot = _reading_snapshot(book)

        # До отзыва слот в required присутствует.
        before = overlay_completion(test_user.id, snapshot, app_db)
        assert [it['id'] for it in before] == ['curriculum:1', f'reading:book:{book.id}']

        _revoke_books_module(db_session, test_user, books_module)

        after = overlay_completion(test_user.id, snapshot, app_db)
        ids = [it['id'] for it in after]
        assert f'reading:book:{book.id}' not in ids, (
            'слот, чей доступ отозван, обязан покинуть required'
        )
        # Остальные required остаются — день закрывается по ним.
        assert ids == ['curriculum:1']

    def test_dropped_slot_is_not_credited_as_completed(
        self, app, db_session, test_user, books_module,
    ):
        """Пометить completed нельзя — это фальшивый кредит и ложный perfect-day."""
        book = _make_book(db_session, rights_status='companion_only')
        _grant_books_module(db_session, test_user, books_module)
        _revoke_books_module(db_session, test_user, books_module)

        out = overlay_completion(test_user.id, _reading_snapshot(book), app_db)
        assert all(it['kind'] != 'reading' for it in out)

    def test_expired_licence_midday_drops_slot(
        self, app, db_session, test_user, books_module,
    ):
        _grant_books_module(db_session, test_user, books_module)
        book = _make_book(db_session, rights_status='licensed')
        snapshot = _reading_snapshot(book)
        assert any(it['kind'] == 'reading' for it in overlay_completion(
            test_user.id, snapshot, app_db,
        ))

        book.expiration_date = study_today() - timedelta(days=1)
        db_session.flush()

        assert all(it['kind'] != 'reading' for it in overlay_completion(
            test_user.id, snapshot, app_db,
        ))

    def test_accessible_book_survives_overlay(
        self, app, db_session, test_user, books_module,
    ):
        book = _make_book(db_session, rights_status='public_domain')
        out = overlay_completion(test_user.id, _reading_snapshot(book), app_db)
        assert [it['id'] for it in out] == ['curriculum:1', f'reading:book:{book.id}']

    def test_vanished_book_row_is_dropped(
        self, app, db_session, test_user, books_module,
    ):
        """Удалённая книга недостижима ровно так же — слот не должен висеть."""
        snapshot = {
            'version': SNAPSHOT_VERSION,
            'date': study_today().isoformat(),
            'tier': 'normal',
            'rolled_over_from': None,
            'items': [{
                'id': 'reading:book:987654',
                'kind': 'reading',
                'title': 'Пропавшая книга',
                'data': {'book_id': 987654},
            }],
        }
        assert overlay_completion(test_user.id, snapshot, app_db) == []
