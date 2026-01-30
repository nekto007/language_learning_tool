"""
Context processors for study module.
Makes XP and achievements data available in all templates.
"""
from flask import g
from flask_login import current_user
from app.study.models import UserXP


def inject_xp_data():
    """Inject user XP data into template context"""
    if not current_user.is_authenticated:
        return {}

    # Get user XP
    user_xp = UserXP.query.filter_by(user_id=current_user.id).first()

    if not user_xp:
        return {
            'user_xp': 0,
            'user_level': 1,
            'xp_to_next_level': 100,
            'xp_progress_percent': 0
        }

    # Use progressive level system from UserXP model
    return {
        'user_xp': user_xp.total_xp,
        'user_level': user_xp.level,
        'xp_to_next_level': user_xp.xp_needed_for_next - user_xp.xp_current_level,
        'xp_progress_percent': int(user_xp.level_progress_percent)
    }
