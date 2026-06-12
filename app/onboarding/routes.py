from flask import jsonify, redirect, render_template, request, session, url_for
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

    # Sanitize ?next= on intake — the wizard form re-submits this value as
    # a POST field, so an open-redirect via the query-string would leak
    # into /onboarding/complete.
    raw_next = request.args.get('next', '')
    safe_next = get_safe_redirect_url(raw_next) if raw_next else ''
    if safe_next == _get_dashboard_url():
        safe_next = ''

    from app.onboarding.placement import placement_available
    return render_template(
        'onboarding/wizard.html',
        next_url=safe_next,
        placement_enabled=placement_available(),
    )


@onboarding_bp.route('/onboarding/placement/start', methods=['POST'])
@login_required
def placement_start():
    """Начать placement-тест: первый вопрос адаптивной лесенки."""
    from app.onboarding.placement import start_placement

    payload = start_placement(session)
    if payload is None:
        return jsonify({'success': False, 'error': 'no_content'}), 409
    return jsonify({'success': True, **payload})


@onboarding_bp.route('/onboarding/placement/answer', methods=['POST'])
@login_required
def placement_answer():
    """Принять ответ; вернуть следующий вопрос или рекомендацию уровня."""
    from app.onboarding.placement import submit_placement_answer

    data = request.get_json(silent=True) or {}
    try:
        exercise_id = int(data.get('exercise_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'invalid_input'}), 400
    answer = data.get('answer')
    if not isinstance(answer, str) or len(answer) > 200:
        return jsonify({'success': False, 'error': 'invalid_input'}), 400

    result = submit_placement_answer(session, exercise_id, answer)
    if result is None:
        return jsonify({'success': False, 'error': 'no_active_test'}), 409
    return jsonify({'success': True, **result})


@onboarding_bp.route('/onboarding/complete', methods=['POST'])
@login_required
def complete():
    """Save onboarding choices and mark as completed."""
    if current_user.onboarding_completed:
        return redirect(_get_dashboard_url())

    # Save onboarding choices
    level = request.form.get('level', '').strip()
    focus = request.form.get('focus', '').strip()
    valid_levels = {'A1', 'A2', 'B1', 'B2', 'C1'}
    valid_focuses = {'grammar', 'vocabulary', 'reading', 'all'}
    if level and level in valid_levels:
        current_user.onboarding_level = level
    if focus:
        parts = [p.strip() for p in focus.split(',') if p.strip()]
        if parts and all(p in valid_focuses for p in parts):
            current_user.onboarding_focus = ','.join(parts)
    was_completed = current_user.onboarding_completed
    current_user.onboarding_completed = True
    db.session.commit()

    if not was_completed:
        # Fire GA4 onboarding_done on the dashboard page render. Skipped on
        # re-saves of the wizard so the event represents a true funnel step.
        from app.utils.gtag_events import queue_gtag_event
        queue_gtag_event(
            'onboarding_done',
            {
                'level': current_user.onboarding_level or '',
                'focus': current_user.onboarding_focus or '',
            },
        )

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
