from flask import Blueprint

race_bp = Blueprint('race', __name__)

from . import routes  # noqa: E402, F401
