# ruff: noqa: RUF001
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app.auth.models import User
from app.family.models import FamilyInvitation, FamilyLink
from app.utils.db import db


class FamilyError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def digest(code):
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24}", code):
        raise FamilyError("invalid_invitation", "Приглашение недействительно или истекло.")
    return hmac.new(str(current_app.config["SECRET_KEY"]).encode(), code.encode(), hashlib.sha256).hexdigest()


def eligible(user):
    from app.auth.deletion_access import learning_suspended
    return bool(user and user.active and not learning_suspended(user.id))


def valid_link(link):
    if not link:
        return False
    parent, child = db.session.get(User, link.parent_id), db.session.get(User, link.child_id)
    return bool(eligible(parent) and eligible(child) and not child.is_admin
                and parent.has_auth_version(link.parent_version) and child.has_auth_version(link.child_version))


def create_invitation(parent, child_name):
    if not isinstance(child_name, str) or not 1 <= len(child_name.strip()) <= 64:
        raise FamilyError("invalid_input", "Укажи имя пользователя ребёнка на сайте.")
    child = User.query.filter_by(username=child_name.strip()).first()
    if (not eligible(parent) or not eligible(child) or child.id == parent.id or child.is_admin
            or (parent.birth_year and datetime.now(UTC).year - parent.birth_year < 18)):
        raise FamilyError("cannot_invite", "Не удалось создать приглашение. Проверь аккаунт и имя пользователя.")
    _check_roles(parent, child)
    FamilyInvitation.query.filter_by(parent_id=parent.id, child_id=child.id).delete()
    code = secrets.token_urlsafe(18)
    row = FamilyInvitation(code_hash=digest(code), parent_id=parent.id, child_id=child.id,
                           parent_version=parent.auth_version(), child_version=child.auth_version(),
                           expires_at=now() + timedelta(minutes=30))
    db.session.add(row)
    db.session.commit()
    return {"code": code, "child_username": child.username, "expires_at": row.expires_at.isoformat() + "Z"}


def _check_roles(parent, child):
    if FamilyLink.query.filter_by(child_id=parent.id).first() or FamilyLink.query.filter_by(parent_id=child.id).first():
        raise FamilyError("family_roles_conflict", "Этот аккаунт уже связан с семьёй в другой роли.", 409)
    existing = FamilyLink.query.filter_by(child_id=child.id).first()
    if existing and existing.parent_id != parent.id:
        raise FamilyError("already_linked", "У аккаунта уже есть семейная привязка.", 409)
    if not existing and FamilyLink.query.filter_by(parent_id=parent.id).count() >= 8:
        raise FamilyError("family_limit", "В семье может быть до восьми детских аккаунтов.", 409)


def invitation_for(child, code):
    row = db.session.get(FamilyInvitation, digest(code))
    if (not row or row.child_id != child.id or row.expires_at <= now() or row.accepted_at
            or not child.has_auth_version(row.child_version)):
        raise FamilyError("invalid_invitation", "Приглашение недействительно или истекло.")
    parent = db.session.get(User, row.parent_id)
    if not eligible(parent) or not eligible(child) or not parent.has_auth_version(row.parent_version):
        raise FamilyError("invalid_invitation", "Приглашение недействительно или истекло.")
    return row, parent


def accept_invitation(child, code):
    row, parent = invitation_for(child, code)
    # Lock the same user rows in a stable order: role checks and the member limit
    # must remain true under concurrent confirmations from different devices.
    User.query.filter(User.id.in_(sorted([parent.id, child.id]))).order_by(User.id).populate_existing().with_for_update().all()
    row = FamilyInvitation.query.filter_by(code_hash=row.code_hash).populate_existing().with_for_update().first()
    if (not row or row.accepted_at or row.expires_at <= now() or child.is_admin
            or not eligible(parent) or not eligible(child)
            or not parent.has_auth_version(row.parent_version) or not child.has_auth_version(row.child_version)):
        raise FamilyError("invalid_invitation", "Приглашение уже использовано или истекло.")
    _check_roles(parent, child)
    link = FamilyLink.query.filter_by(child_id=child.id).first()
    if link:
        db.session.delete(link)
        db.session.flush()
    link = FamilyLink(id=uuid4().hex, parent_id=parent.id, child_id=child.id,
                      parent_version=parent.auth_version(), child_version=child.auth_version())
    db.session.add(link)
    row.accepted_at = now()
    db.session.commit()
    return link


def unlink(user, identifier):
    link = db.session.get(FamilyLink, identifier)
    if not link or user.id not in (link.parent_id, link.child_id):
        raise FamilyError("not_found", "Семейная связь не найдена.", 404)
    FamilyInvitation.query.filter_by(parent_id=link.parent_id, child_id=link.child_id).delete()
    db.session.delete(link)
    db.session.commit()


def member_summary(child):
    """Read existing learning records; never generate plans or mutate a child."""
    from app.curriculum.models import LessonProgress, Lessons, Module, CEFRLevel, LessonAttempt
    from app.study.models import StudySession
    from app.grammar_lab.models import GrammarAttempt
    from app.books.reading_session import UserReadingSession
    from app.daily_plan.models import DailyPlanLog
    from app.utils.time_utils import get_user_local_date

    try:
        zone = ZoneInfo(child.timezone or "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    today = datetime.now(UTC).astimezone(zone).date()
    since = datetime.combine(today - timedelta(days=6), datetime.min.time(), zone).astimezone(UTC).replace(tzinfo=None)
    dates = []
    for model, column, extra in [
        (LessonAttempt, LessonAttempt.completed_at, LessonAttempt.total_questions > 0),
        (LessonProgress, LessonProgress.completed_at, LessonProgress.status == "completed"),
        (StudySession, StudySession.end_time, StudySession.words_studied > 0),
        (GrammarAttempt, GrammarAttempt.created_at, GrammarAttempt.id > 0),
        (UserReadingSession, UserReadingSession.ended_at, UserReadingSession.offset_delta > 0),
    ]:
        dates.extend(value for (value,) in db.session.query(column).filter(model.user_id == child.id, column >= since, extra).all())
    dates = [value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
             for value in dates]
    local_dates = {value.astimezone(zone).date() for value in dates}
    recent = (db.session.query(Lessons.title, Module.title, CEFRLevel.code)
              .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
              .join(Module, Lessons.module_id == Module.id).join(CEFRLevel, Module.level_id == CEFRLevel.id)
              .filter(LessonProgress.user_id == child.id, LessonProgress.status.in_(["in_progress", "completed"]))
              .order_by(LessonProgress.last_activity.desc(), Lessons.id.desc()).first())
    log = DailyPlanLog.query.filter_by(user_id=child.id, plan_date=get_user_local_date(child.id, db)).first()
    return {
        "day_secured": bool(log.secured_at) if log else None,
        "lesson_title": recent[0] if recent else None, "module_title": recent[1] if recent else None,
        "level": recent[2] if recent else child.onboarding_level,
        "active_days": [day.isoformat() for day in sorted(local_dates) if day <= today],
        "today_active": today in local_dates,
        "last_activity": max(dates).isoformat() if dates else None,
    }


def dashboard(user):
    members = []
    for link in FamilyLink.query.filter_by(parent_id=user.id).order_by(FamilyLink.created_at).all():
        child = db.session.get(User, link.child_id)
        if not child:
            continue
        available = valid_link(link)
        members.append({"id": child.id, "username": child.username, "link_id": link.id,
                        "available": available, "summary": member_summary(child) if available else None})
    parent_link = FamilyLink.query.filter_by(child_id=user.id).first()
    parent = db.session.get(User, parent_link.parent_id) if parent_link else None
    return {"success": True, "members": members,
            "parent": {"id": parent.id, "username": parent.username, "link_id": parent_link.id} if parent else None}
