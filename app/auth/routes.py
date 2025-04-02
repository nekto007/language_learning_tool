import secrets
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import URLSafeTimedSerializer

from app.auth.forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from app.auth.models import User
from app.utils.db import db
from config.settings import Config

auth = Blueprint('auth', __name__)


def get_reset_token(user_id, expiration=3600):
    """Generate a secure password reset token."""
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)
    return serializer.dumps(user_id, salt='password-reset-salt')


def verify_reset_token(token, expiration=3600):
    """Verify the reset token and return the user ID."""
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)
    try:
        user_id = serializer.loads(
            token,
            salt='password-reset-salt',
            max_age=expiration
        )
        return user_id
    except:
        return None


@auth.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        token = get_reset_token(user.id)

        # Here you'd normally send an email with the token
        # For now, we'll just display the reset link on the page
        reset_url = url_for('auth.reset_password', token=token, _external=True)

        flash(f'A password reset link has been created. For testing: {reset_url}', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_request.html', form=form)


@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    user_id = verify_reset_token(token)
    if user_id is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('auth.reset_request'))

    user = User.query.get(user_id)
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.reset_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Generate a new salt
        user.salt = secrets.token_hex(16)
        user.set_password(form.password.data)

        db.session.commit()
        flash('Your password has been updated! You can now log in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            # Check if user is active
            if not user.is_active:
                flash('Your account is inactive. Please contact an administrator.', 'danger')
                return render_template('auth/login.html', form=form)

            # Log in the user
            login_user(user, remember=form.remember_me.data)

            # Update last login timestamp
            user.last_login = datetime.utcnow()
            db.session.commit()

            # Redirect to requested page or dashboard
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('words.dashboard')
            return redirect(next_page)
        else:
            flash('Invalid username or password', 'danger')

    return render_template('auth/login.html', form=form)


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            active=True  # Set user as active by default
        )
        user.set_password(form.password.data)

        try:
            db.session.add(user)
            db.session.commit()

            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed. Error: {str(e)}', 'danger')

    return render_template('auth/register.html', form=form)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
