"""READ-ONLY: замер «после» для DP-033 (Task 4) на копии прода.

Проверяет два механизма фикса на реальных данных `user_id=39` — юзере из
замера (а), у которого 52 дня подряд висел недостижимый required-слот чтения:

1. **Билдер.** `build_reading_item` / `_reading_item_dict` больше не отдают
   слот, а `reading_preference_needs_setup` переключается в True.
2. **Снапшот.** `overlay_completion` по всем уже замороженным `plan_json`
   этого юзера выбрасывает слот чтения из required (самопочинка).

Ничего не пишет: сессия откатывается в конце, коммитов нет.
"""
import os

os.environ['POSTGRES_DB'] = 'learn_db_prod'
os.environ['POSTGRES_HOST'] = '127.0.0.1'
os.environ['POSTGRES_PORT'] = '5432'

from app import create_app  # noqa: E402
from app.utils.db import db  # noqa: E402

USER_ID = 39

app = create_app()
app.config['TESTING'] = True

with app.app_context():
    from app.auth.models import User
    from app.books.models import Book
    from app.daily_plan.items.reading import (
        book_access_ok_for_reading,
        build_reading_item,
        get_user_reading_preference,
        reading_preference_needs_setup,
    )
    from app.daily_plan.linear.models import UserReadingPreference  # noqa: F401
    from app.daily_plan.models import DailyPlanLog
    from app.daily_plan.plan_builder import _reading_item_dict
    from app.daily_plan.snapshot import _valid_snapshot, overlay_completion

    user = db.session.get(User, USER_ID)
    pref = get_user_reading_preference(USER_ID, db)
    book = db.session.get(Book, pref.book_id) if pref else None

    print(f'user={USER_ID} is_admin={getattr(user, "is_admin", None)}')
    if book is not None:
        print(
            f'preference book={book.id} "{book.title}" '
            f'rights={book.rights_status} published={book.is_published} '
            f'expires={book.expiration_date}'
        )

    print('--- 1. билдер ---')
    print(f'book_access_ok_for_reading   = {book_access_ok_for_reading(USER_ID, book, db)}')
    print(f'build_reading_item           = {build_reading_item(USER_ID, db)}')
    print(f'_reading_item_dict(required) = {_reading_item_dict(USER_ID, db)}')
    print(f'reading_preference_needs_setup = {reading_preference_needs_setup(USER_ID, db)}')

    print('--- 2. самопочинка замороженных снапшотов ---')
    rows = (
        db.session.query(DailyPlanLog)
        .filter(DailyPlanLog.user_id == USER_ID, DailyPlanLog.plan_json.isnot(None))
        .order_by(DailyPlanLog.plan_date)
        .all()
    )
    had_reading = 0
    still_reading = 0
    for row in rows:
        snap = _valid_snapshot(row.plan_json)
        if snap is None:
            continue
        frozen = [
            it for it in snap.get('items') or []
            if str(it.get('id') or '').startswith('reading:')
        ]
        if not frozen:
            continue
        had_reading += 1
        overlaid = overlay_completion(USER_ID, snap, db)
        if any(str(it.get('id') or '').startswith('reading:') for it in overlaid):
            still_reading += 1
    print(f'дней со слотом чтения в замороженном required : {had_reading}')
    print(f'из них слот переживает overlay_completion      : {still_reading}')

    db.session.rollback()
