from flask import redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.auth.routes import get_safe_redirect_url
from app.onboarding import onboarding_bp
from app.utils.db import db


@onboarding_bp.route('/onboarding', methods=['GET'])
@login_required
def wizard():
    """Show onboarding wizard for new users."""
    if current_user.onboarding_completed:
        return redirect(url_for('words.dashboard'))

    # Get CEFR levels for step 1
    from app.curriculum.models import CEFRLevel
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    return render_template('onboarding/wizard.html', levels=levels,
                           next_url=request.args.get('next', ''))


@onboarding_bp.route('/onboarding/complete', methods=['POST'])
@login_required
def complete():
    """Save onboarding choices and mark as completed."""
    if current_user.onboarding_completed:
        return redirect(url_for('words.dashboard'))

    current_user.onboarding_completed = True
    db.session.commit()

    # Redirect to originally requested page or dashboard
    next_url = request.form.get('next', '')
    safe_url = get_safe_redirect_url(next_url)
    return redirect(safe_url)
