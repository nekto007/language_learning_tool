from flask import redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.auth.routes import get_safe_redirect_url
from app.onboarding import onboarding_bp
from app.utils.db import db


def _get_dashboard_url() -> str:
    """Return dashboard URL, falling back to landing if user lacks the words module."""
    from app.modules.service import ModuleService
    if ModuleService.is_module_enabled_for_user(current_user.id, 'words'):
        return url_for('words.dashboard')
    return url_for('landing.index')


@onboarding_bp.route('/onboarding', methods=['GET'])
@login_required
def wizard():
    """Show onboarding wizard for new users."""
    if current_user.onboarding_completed:
        return redirect(_get_dashboard_url())

    return render_template('onboarding/wizard.html',
                           next_url=request.args.get('next', ''))


@onboarding_bp.route('/onboarding/complete', methods=['POST'])
@login_required
def complete():
    """Save onboarding choices and mark as completed."""
    if current_user.onboarding_completed:
        return redirect(_get_dashboard_url())

    # Save onboarding choices
    level = request.form.get('level', '').strip()
    focus = request.form.get('focus', '').strip()
    valid_levels = {'A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2'}
    valid_focuses = {'grammar', 'vocabulary', 'reading', 'all'}
    if level and level in valid_levels:
        current_user.onboarding_level = level
    if focus:
        parts = [p.strip() for p in focus.split(',') if p.strip()]
        if parts and all(p in valid_focuses for p in parts):
            current_user.onboarding_focus = ','.join(parts)
    current_user.onboarding_completed = True
    db.session.commit()

    # Redirect to originally requested page or dashboard
    next_url = request.form.get('next', '')
    dashboard_url = _get_dashboard_url()
    if next_url:
        safe_url = get_safe_redirect_url(next_url)
        # If user lacks words module, don't redirect to dashboard (would 403)
        if safe_url == url_for('words.dashboard'):
            safe_url = dashboard_url
    else:
        safe_url = dashboard_url
    return redirect(safe_url)
