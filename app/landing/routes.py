from flask import redirect, render_template, url_for
from flask_login import current_user

from app.landing import landing_bp


@landing_bp.route('/')
def index():
    """
    Public landing page.
    Redirects authenticated users to dashboard.
    """
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    # Get platform statistics for social proof
    from app.auth.models import User
    from app.words.models import CollectionWords
    from app.curriculum.models import CEFRLevel

    stats = {
        'users': User.query.filter_by(active=True).count(),
        'words': CollectionWords.query.count(),
        'levels': 7,  # A0, A1, A2, B1, B2, C1, C2
    }

    return render_template('landing/index.html', stats=stats)
