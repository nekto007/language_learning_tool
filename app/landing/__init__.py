from flask import Blueprint

landing_bp = Blueprint('landing', __name__)

from app.landing import routes  # noqa: F401
from app.landing import rehearsal as rehearsal
