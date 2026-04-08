from flask import redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required

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

    return render_template('onboarding/wizard.html', levels=levels)


@onboarding_bp.route('/onboarding/complete', methods=['POST'])
@login_required
def complete():
    """Save onboarding choices and mark as completed."""
    if current_user.onboarding_completed:
        return jsonify({'success': True, 'redirect': url_for('words.dashboard')})

    # Save selected level if provided
    level_code = request.form.get('level') or (request.json or {}).get('level')
    if level_code:
        from app.curriculum.models import CEFRLevel
        level = CEFRLevel.query.filter_by(code=level_code).first()
        # Level preference is noted but we don't store it on user for now
        # (no level_id column on users — the curriculum system handles this via modules)

    current_user.onboarding_completed = True
    db.session.commit()

    # Support both form POST and JSON
    if request.is_json:
        return jsonify({'success': True, 'redirect': url_for('words.dashboard')})
    return redirect(url_for('words.dashboard'))
