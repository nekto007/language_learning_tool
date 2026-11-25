from flask import redirect, render_template, url_for

from app.public_copy import copy_for_public_view

from . import legal_bp


@legal_bp.route('/privacy')
def privacy() -> str:
    """Render the privacy policy page."""
    return copy_for_public_view('privacy', render_template('legal/privacy.html'))


@legal_bp.route('/privacy/')
def privacy_trailing_slash():
    """Redirect the trailing-slash variant to the canonical no-slash URL (SEO)."""
    return redirect(url_for('legal.privacy'), code=301)


@legal_bp.route('/support/mobile')
def mobile_support() -> str:
    """Public help, including deletion instructions, without signing in."""
    return copy_for_public_view('support', render_template('legal/mobile_support.html'))
