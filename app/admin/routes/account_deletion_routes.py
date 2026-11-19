"""Manual deletion approval after a 7-day cooling-off period, due by day 14."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from flask_login import AnonymousUserMixin, current_user, logout_user
from app.admin.utils.decorators import admin_required, admin_audit_required
from app.api.mobile_auth import AuthProblem
from app.auth.account_deletion import AccountDeletionRequest, complete_account_deletion
from app.auth.mobile_models import utcnow
from app.auth.mobile_mail import nudge_auth_mail
from app.utils.db import db

account_deletion_bp = Blueprint("account_deletion_admin", __name__)


def page(error=None, status_code=200):
    state = request.args.get("status", "pending")
    if state not in ("pending", "cancelled", "completed"):
        state = "pending"
    query = AccountDeletionRequest.query.filter_by(status=state)
    identifier = request.args.get("request_id", "")
    if identifier:
        query = query.filter_by(id=identifier)
    pagination = query.order_by(
        AccountDeletionRequest.requested_at.asc()
    ).paginate(page=request.args.get("page", 1, type=int), per_page=30, error_out=False)
    return render_template("admin/account_deletions.html", pagination=pagination,
        selected_status=state, now=utcnow(), error=error, request_id=identifier), status_code


@account_deletion_bp.get("/account-deletions")
@admin_required
def index():
    return page()


@account_deletion_bp.post("/account-deletions/<identifier>/complete")
@admin_audit_required("account.deletion.approve", target_type="account_deletion")
def complete(identifier):
    row = db.session.get(AccountDeletionRequest, identifier)
    if row is None or row.status != "pending" or row.user is None:
        return page("Заявка закрыта или не найдена. Аккаунт не изменён.", 409)
    if request.form.get("confirmation") != row.user.username:
        return page("Для подтверждения введи точное имя пользователя.", 400)
    own_account = row.user_id == current_user.id
    try:
        complete_account_deletion(identifier, current_user)
    except AuthProblem as error:
        db.session.rollback()
        return page(error.message, error.status)
    if own_account:
        g._login_user = AnonymousUserMixin()
        logout_user()
        return redirect(url_for("auth.login"))
    nudge_auth_mail()
    flash("Аккаунт удалён после ручного подтверждения. Письмо-подтверждение поставлено в очередь.", "success")
    return redirect(url_for("account_deletion_admin.index"))
