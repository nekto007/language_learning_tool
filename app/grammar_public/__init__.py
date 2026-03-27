from flask import Blueprint

grammar_public_bp = Blueprint('grammar_public', __name__, url_prefix='/grammar')

from . import routes  # noqa: E402, F401
