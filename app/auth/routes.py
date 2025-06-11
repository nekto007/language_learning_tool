import secrets
from datetime import datetime
from flask_babel import lazy_gettext as _l
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import URLSafeTimedSerializer

from app.auth.forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from app.auth.models import User
from app.utils.db import db
from app.utils.email_utils import email_sender
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
    # Import limiter here to avoid circular imports
    from app import limiter
    
    # Apply rate limiting to password reset requests
    @limiter.limit("3 per minute")
    def _reset_request():
        if current_user.is_authenticated:
            return redirect(url_for('words.dashboard'))

        form = RequestResetForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user:
                token = get_reset_token(user.id)
                reset_url = url_for('auth.reset_password', token=token, _external=True)

                # Отправляем электронное письмо
                email_sent = email_sender.send_email(
                    subject="Сброс пароля",
                    to_email=user.email,
                    template_name="password_reset",
                    context={
                        "username": user.username,
                        "reset_url": reset_url
                    }
                )

                if email_sent:
                    flash('На вашу электронную почту была отправлена инструкция по сбросу пароля.', 'info')
                else:
                    flash('Возникла проблема при отправке электронного письма. Пожалуйста, попробуйте позже.', 'danger')
            else:
                # Всегда показываем положительное сообщение из соображений безопасности
                flash('На вашу электронную почту была отправлена инструкция по сбросу пароля.', 'info')

            return redirect(url_for('auth.login'))

        return render_template('auth/reset_request.html', form=form)
    
    return _reset_request()


@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    user_id = verify_reset_token(token)
    if user_id is None:
        flash('Недействительная или истекшая ссылка для сброса пароля', 'warning')
        return redirect(url_for('auth.reset_request'))

    user = User.query.get(user_id)
    if not user:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('auth.reset_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Generate a new salt
        user.salt = secrets.token_hex(16)
        user.set_password(form.password.data)

        db.session.commit()
        flash('Ваш пароль был обновлен! Теперь вы можете войти с новым паролем.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    # Import limiter here to avoid circular imports
    from app import limiter
    
    # Apply rate limiting to login attempts
    @limiter.limit("5 per minute")
    def _login():
        if current_user.is_authenticated:
            return redirect(url_for('words.dashboard'))

        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and user.check_password(form.password.data):
                # Check if user is active
                if not user.is_active:
                    flash('Ваша учетная запись неактивна. Пожалуйста, обратитесь к администратору.', 'danger')
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
                flash(_l('Invalid email or password'), 'danger')
                return render_template('auth/login.html', form=form), 401

        return render_template('auth/login.html', form=form)
    
    return _login()


@auth.route('/register', methods=['GET', 'POST'])
def register():
    # Import limiter here to avoid circular imports
    from app import limiter
    
    # Apply rate limiting to registration attempts
    @limiter.limit("3 per minute")
    def _register():
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

                flash('Регистрация успешна! Теперь вы можете войти в систему.', 'success')
                return redirect(url_for('auth.login'))
            except Exception as e:
                db.session.rollback()
                flash(f'Регистрация не удалась. Ошибка: {str(e)}', 'danger')

        return render_template('auth/register.html', form=form)
    
    return _register()


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('auth.login'))