"""Three daytime reminders, only until the first learning activity."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.notifications.apns import APNsClient, configured
from app.notifications.push_models import PushDelivery, PushDevice, PushPreference
from app.utils.activity_tracker import has_learning_activity
from app.utils.db import db
from app.utils.time_utils import _study_day_date, study_day_start_utc
from config.settings import DEFAULT_TIMEZONE

MESSAGES = (
    ('Время для английского', 'Начни с небольшого занятия. Твой план на сегодня уже ждёт.'),
    ('Найдётся несколько минут?', 'Сегодня ты ещё не занимался. Открой план и сделай первый шаг.'),
    ('Немного английского на вечер', 'Ещё можно позаниматься сегодня. Начни с одного короткого задания.'),
)


def due_slot(hours, local_now):
    """Only the current half-hour window; never replay missed notifications."""
    for index, hour in enumerate(hours):
        if local_now.hour == hour and local_now.minute < 30:
            return index
    return None


def _eligible(user, now):
    from app.auth.deletion_access import learning_suspended
    if learning_suspended(user.id):
        return None
    try:
        tz = ZoneInfo(user.timezone or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = now.astimezone(tz)
    day = _study_day_date(local)
    if user.plan_paused_until and user.plan_paused_until > day:
        return None
    start = study_day_start_utc(tz.key, day)
    end = study_day_start_utc(tz.key, day + timedelta(days=1))
    if has_learning_activity(user.id, start, end):
        return None
    return local, day


def send_due_reminders(now=None, sender_factory=APNsClient):
    """Run in the dedicated scheduler; unique claims also protect overlapping processes.

    Claims are committed BEFORE network I/O. At-most-once is intentional: a
    crash/timeout can lose a reminder, but cannot annoy a user with duplicates.
    """
    if not configured():
        return 0
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(timezone.utc)
    accepted = 0
    candidates = db.session.query(PushPreference.user_id).filter_by(enabled=True).all()
    with sender_factory() as sender:
        for (user_id,) in candidates:
            user = db.session.get(User, user_id)
            if user is None or not user.is_active:
                continue
            eligibility = _eligible(user, now)
            if eligibility is None:
                continue
            local, day = eligibility
            preference = db.session.get(PushPreference, user_id)
            slot = due_slot(preference.hours, local)
            if slot is None:
                continue
            devices = PushDevice.query.filter_by(user_id=user_id, active=True).filter(
                PushDevice.auth_version == str(user.auth_version()),
                PushDevice.updated_at >= now.replace(tzinfo=None) - timedelta(days=90)).all()
            if not devices:
                continue
            claim = PushDelivery(user_id=user_id, study_date=day, slot=slot)
            db.session.add(claim)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                continue
            # Re-read after the committed claim: an opt-out or activity during
            # this tick must take effect before the actual send.
            db.session.refresh(preference)
            db.session.refresh(user)
            if not preference.enabled or not user.is_active:
                continue
            updated_eligibility = _eligible(user, now)
            if updated_eligibility is None:
                continue
            local, updated_day = updated_eligibility
            if updated_day != day or due_slot(preference.hours, local) != slot:
                # Nothing was sent. A later valid window can use this key.
                db.session.delete(claim)
                db.session.commit()
                continue
            for device in devices:
                db.session.refresh(device)
                if not device.active or device.user_id != user_id or device.auth_version != str(user.auth_version()):
                    continue
                title, body = MESSAGES[slot]
                result = sender.send(device, title=title, body=body,
                    collapse_id=f'study-{day}-{slot}',
                    account_key='account:' + user.username,
                    expires_at=int(local.replace(minute=30, second=0, microsecond=0).timestamp()))
                if result.invalid_device:
                    device.active = False
                if result.accepted:
                    claim.accepted += 1
                    accepted += 1
                db.session.commit()
    # Bound operational history without depending on a second maintenance job.
    PushDelivery.query.filter(PushDelivery.created_at < now.replace(tzinfo=None)-timedelta(days=90)).delete()
    db.session.commit()
    return accepted
