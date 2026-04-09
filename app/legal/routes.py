from flask import render_template

from . import legal_bp


@legal_bp.route('/privacy')
def privacy() -> str:
    """Render the privacy policy page."""
    return render_template('legal/privacy.html')
