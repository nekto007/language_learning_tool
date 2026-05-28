# app/admin/routes/acquisition_routes.py

"""Admin acquisition attribution dashboard."""

import logging

from flask import Blueprint, render_template, request

from app.admin.services.acquisition_metrics import (
    get_acquisition_overview,
    get_top_referrers,
)
from app.admin.utils.decorators import admin_required
from app.utils.db import db

acquisition_bp = Blueprint('acquisition_admin', __name__)

logger = logging.getLogger(__name__)

_ALLOWED_WINDOWS = (7, 14, 30, 60, 90)


@acquisition_bp.route('/acquisition')
@admin_required
def acquisition_index():
    days = request.args.get('days', 30, type=int)
    if days not in _ALLOWED_WINDOWS:
        days = 30

    overview = get_acquisition_overview(db.session, days=days)
    referrers = get_top_referrers(db.session, days=days, limit=10)

    return render_template(
        'admin/acquisition/index.html',
        overview=overview,
        referrers=referrers,
        days=days,
        windows=_ALLOWED_WINDOWS,
    )
