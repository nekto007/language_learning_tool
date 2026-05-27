"""In-app product feedback channel (bug / idea / question)."""

from flask import Blueprint

feedback_bp = Blueprint('feedback', __name__)

from app.feedback import routes  # noqa: E402, F401
