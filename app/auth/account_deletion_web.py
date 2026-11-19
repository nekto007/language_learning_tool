"""Authenticated web fallback for the same verified deletion flow as iOS."""

from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app import limiter
from app.utils.db import db


def register_account_deletion_web(blueprint):
    @blueprint.route("/account-deletion", methods=["GET", "POST"])
    @login_required
    @limiter.limit("30 per minute")
    def account_deletion():
        from app.api.mobile_account import _user, start_verification, confirm_request, cancel_request
        from app.api.mobile_auth import AuthProblem
        from app.auth.account_deletion import AccountDeletionRequest

        if not current_user.active:
            abort(403)
        key = "account_deletion_challenge"
        challenge = session.get(key)
        if challenge and challenge.get("user_id") != current_user.id:
            session.pop(key, None)
            challenge = None
        error = None
        status = 200
        if request.method == "POST":
            try:
                user = _user()
                action = request.form.get("action")
                if action == "start":
                    challenge = {**start_verification(user), "user_id": user.id}
                    session[key] = challenge
                elif action == "confirm":
                    confirm_request(
                        user,
                        {
                            "challenge_id": request.form.get("challenge_id"),
                            "code": request.form.get("code"),
                            "password": request.form.get("password"),
                            "confirm": True,
                        },
                    )
                    session.pop(key, None)
                    flash(
                        "Заявка подтверждена. Администратор продолжит обработку; исходные сроки сохраняются.", "success"
                    )
                    return redirect(url_for("auth.account_deletion"))
                elif action == "cancel":
                    cancel_request(user, request.form.get("request_id"))
                    session.pop(key, None)
                    flash("Заявка отменена. Аккаунт сохранён.", "success")
                    return redirect(url_for("auth.account_deletion"))
                else:
                    raise AuthProblem("invalid_input", "Выбери действие для заявки.")
            except AuthProblem as problem:
                db.session.rollback()
                error, status = problem.message, problem.status
                if problem.code == "challenge_expired":
                    session.pop(key, None)
                    challenge = None
        row = AccountDeletionRequest.query.filter_by(user_id=current_user.id).first()
        response = make_response(
            render_template("auth/account_deletion.html", deletion=row, challenge=challenge, error=error), status
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response
