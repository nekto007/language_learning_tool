from flask import Blueprint

modules_bp = Blueprint('modules', __name__)

from app.modules import routes
