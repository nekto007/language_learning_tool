from flask import redirect, render_template, url_for

from . import legal_bp


@legal_bp.route('/privacy')
def privacy() -> str:
    """Render the privacy policy page."""
    return render_template('legal/privacy.html')


@legal_bp.route('/privacy/')
def privacy_trailing_slash():
    """Redirect the trailing-slash variant to the canonical no-slash URL (SEO)."""
    return redirect(url_for('legal.privacy'), code=301)
