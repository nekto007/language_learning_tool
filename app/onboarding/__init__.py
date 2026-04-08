from flask import Blueprint

onboarding_bp = Blueprint('onboarding', __name__)

from . import routes  # noqa: E402, F401
