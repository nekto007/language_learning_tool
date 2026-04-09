"""API routes for notification center."""
from flask import jsonify, request
from flask_login import current_user, login_required

from app.notifications import notifications_bp
from app.notifications.models import Notification
from app.notifications.services import get_unread_count
from app.utils.db import db


@notifications_bp.route('/list')
@login_required
def list_notifications():
    """Get recent notifications for current user."""
    limit = request.args.get('limit', 20, type=int)
    notifications = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )
    return jsonify({
        'success': True,
        'notifications': [n.to_dict() for n in notifications],
        'unread_count': get_unread_count(current_user.id),
    })


@notifications_bp.route('/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_read(notif_id: int):
    """Mark a single notification as read."""
    notif = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first()
    if not notif:
        return jsonify({'success': False, 'error': 'Not found'}), 404

    notif.read = True
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/read-all', methods=['POST'])
@login_required
def mark_all_read():
    """Mark all notifications as read."""
    Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/unread-count')
@login_required
def unread_count():
    """Get unread notification count (for badge)."""
    return jsonify({
        'success': True,
        'count': get_unread_count(current_user.id),
    })
