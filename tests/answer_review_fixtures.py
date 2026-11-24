"""Database-backed Telegram administrators for answer review tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from app.auth.models import User
from app.telegram.models import TelegramUser
from app.utils.db import db


@contextmanager
def telegram_admin() -> Iterator[TelegramUser]:
    """Create an active site administrator with an active Telegram link."""
    suffix = uuid4().hex[:12]
    user = User(username=f"review_{suffix}", email=f"review_{suffix}@example.invalid",
                active=True, is_admin=True)
    user.set_password("disposable-answer-review-test-password")
    db.session.add(user)
    db.session.flush()
    user_id = user.id
    binding = TelegramUser(user_id=user_id, telegram_id=(uuid4().int % (2**52)) + 1, is_active=True)
    db.session.add(binding)
    db.session.commit()
    try:
        yield binding
    finally:
        db.session.rollback()
        TelegramUser.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        User.query.filter_by(id=user_id).delete(synchronize_session=False)
        db.session.commit()
