from flask import Blueprint

seo_bp = Blueprint('seo', __name__)

from app.seo import routes  # noqa: E402, F401
