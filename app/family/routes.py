from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_jwt_extended import get_jwt

from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import private_response
from app.auth.models import User
from app.family.models import FamilyLink
from app.family.service import (FamilyError, accept_invitation, create_invitation, dashboard,
                                invitation_for, unlink, valid_link)
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_family = Blueprint("api_family", __name__)
family_web = Blueprint("family_web", __name__)
api_family.after_request(private_response)
family_web.after_request(private_response)


@api_family.errorhandler(FamilyError)
def error(problem):
    db.session.rollback()
    return jsonify(success=False, error=problem.code, message=problem.message), problem.status


def body(keys):
    value = request.get_json(silent=True)
    if ((request.content_length and request.content_length > 4000)
            or not isinstance(value, dict) or set(value) != set(keys)):
        raise FamilyError("invalid_input", "Проверь заполненные поля.")
    return value


@api_family.get("")
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def current():
    return jsonify(dashboard(current_user))


@api_family.post("/invitations")
@csrf.exempt
@api_bearer_required
@limiter.limit("5 per minute", key_func=get_authenticated_user_key)
def invite():
    value = create_invitation(current_user, body(["username"])["username"])
    return jsonify(success=True, invitation=value)


@api_family.post("/accept")
@csrf.exempt
@api_bearer_required
@limiter.limit("10 per minute", key_func=get_authenticated_user_key)
def accept():
    value = body(["code", "consent"])
    if value["consent"] is not True:
        raise FamilyError("consent_required", "Подтверди семейный доступ.")
    link = accept_invitation(current_user, value["code"])
    return jsonify(success=True, link_id=link.id)


@api_family.delete("/links/<identifier>")
@csrf.exempt
@api_bearer_required
def remove(identifier):
    unlink(current_user, identifier)
    return jsonify(success=True)


@api_family.post("/members/<int:child_id>/session")
@csrf.exempt
@api_bearer_required
@limiter.limit("20 per minute", key_func=get_authenticated_user_key)
def child_session(child_id):
    from app.utils.jwt_auth import create_tokens_for_user
    body([])
    link = FamilyLink.query.filter_by(parent_id=current_user.id, child_id=child_id).first()
    if not valid_link(link):
        raise FamilyError("family_access_unavailable", "Связь нужно подтвердить заново или снять приостановку аккаунта.", 403)
    child = db.session.get(User, child_id)
    return jsonify(success=True, **create_tokens_for_user(child, family_link=link),
                   user={"id": child.id, "username": child.username, "is_admin": False})


@api_family.get("/session")
@api_bearer_required
def session_status():
    from app.family.security import delegated_link
    link = delegated_link(get_jwt())
    if not link:
        raise FamilyError("family_access_unavailable", "Семейный вход недоступен.", 403)
    return jsonify(success=True, parent_id=link.parent_id, child_id=link.child_id, link_id=link.id)


@family_web.route("/family", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per minute", key_func=get_authenticated_user_key)
def index():
    invitation = None
    incoming = None
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "invite":
                invitation = create_invitation(current_user, request.form.get("username"))
            elif action == "preview":
                code = (request.form.get("code") or "").strip()
                _, parent = invitation_for(current_user, code)
                incoming = {"code": code, "parent_name": parent.username}
            elif action == "accept":
                if request.form.get("consent") != "yes":
                    raise FamilyError("consent_required", "Подтверди семейный доступ.")
                accept_invitation(current_user, request.form.get("code"))
                flash("Семейный доступ подключён.", "success")
                return redirect(url_for("family_web.index"), code=303)
            elif action == "unlink":
                unlink(current_user, request.form.get("link_id"))
                flash("Семейная связь отключена. Учётные записи и прогресс сохранены.", "success")
                return redirect(url_for("family_web.index"), code=303)
            else:
                raise FamilyError("invalid_input", "Неизвестное действие.")
        except FamilyError as problem:
            db.session.rollback()
            flash(problem.message, "warning")
    return render_template("auth/family.html", family=dashboard(current_user), invitation=invitation, incoming=incoming)
