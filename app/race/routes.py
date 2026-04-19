from __future__ import annotations

from flask import render_template, url_for
from flask_login import current_user, login_required

from app.modules.decorators import module_required

from . import race_bp


@race_bp.route('/race')
@login_required
@module_required('words')
def today() -> str:
    """Render the dedicated daily race page with the full race UX.

    The dashboard only shows a compact strip pointing here; this page holds
    the 3-tasks block, nudge callout, full leaderboard, rival above/below
    tasks, CTA button, and finished-state summary.
    """
    from app.words.routes import (
        _build_daily_race_widget,
        _get_next_plan_action,
    )
    from app.daily_plan.service import get_daily_plan_unified
    from app.telegram.queries import get_daily_summary
    from config.settings import DEFAULT_TIMEZONE

    tz = current_user.timezone or DEFAULT_TIMEZONE
    daily_race = _build_daily_race_widget(current_user.id, tz)

    if daily_race is not None:
        try:
            daily_plan = get_daily_plan_unified(current_user.id, tz=tz)
            daily_summary = get_daily_summary(current_user.id, tz=tz)
            next_plan_title, next_plan_url = _get_next_plan_action(
                daily_plan, daily_summary
            )
            daily_race['next_action_title'] = next_plan_title
            daily_race['next_action_url'] = next_plan_url
        except Exception:
            daily_race.setdefault('next_action_title', None)
            daily_race.setdefault('next_action_url', None)

    return render_template(
        'race/today.html',
        daily_race=daily_race,
        dashboard_url=url_for('words.dashboard'),
    )
