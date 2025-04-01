from flask import Blueprint, request, jsonify
from flask_login import login_user, current_user
from app.auth.models import User
from app.utils.db import db
from datetime import datetime
import functools

api_auth = Blueprint('api_auth', __name__)


def api_login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({
                'success': False,
                'error': 'Authentication required',
                'status_code': 401
            }), 401
        return f(*args, **kwargs)

    return decorated_function


@api_auth.route('/login', methods=['POST'])
def api_login():
    if not request.is_json:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format',
            'status_code': 400
        }), 400

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({
            'success': False,
            'error': 'Missing username or password',
            'status_code': 400
        }), 400

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        login_user(user)
        user.last_login = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'user_id': user.id,
            'username': user.username
        })

    return jsonify({
        'success': False,
        'error': 'Invalid credentials',
        'status_code': 401
    }), 401
