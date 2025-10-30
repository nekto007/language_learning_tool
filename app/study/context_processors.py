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
            'xp_to_next_level': 100
        }

    # Calculate XP progress to next level
    current_level_xp = (user_xp.level - 1) * 100
    next_level_xp = user_xp.level * 100
    xp_to_next = next_level_xp - user_xp.total_xp
    xp_progress_percent = ((user_xp.total_xp - current_level_xp) / 100) * 100

    return {
        'user_xp': user_xp.total_xp,
        'user_level': user_xp.level,
        'xp_to_next_level': xp_to_next,
        'xp_progress_percent': int(xp_progress_percent)
    }
