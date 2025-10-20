import secrets
from datetime import datetime, timezone
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


def get_safe_redirect_url(next_url, fallback='words.dashboard'):
    """
    Get a safe redirect URL, checking for security issues
    """
    if not next_url:
        return url_for(fallback)
    
    from urllib.parse import urlparse
    from flask import request, url_for
    
    parsed = urlparse(next_url)
    
    # Only allow relative URLs or same-origin URLs
    if parsed.netloc and parsed.netloc != request.host:
        return url_for(fallback)
    
    # Only allow http/https schemes or no scheme (relative URLs)
    if parsed.scheme and parsed.scheme not in ['http', 'https']:
        return url_for(fallback)
    
    # Ensure it starts with / for relative URLs
    if not parsed.netloc and not next_url.startswith('/'):
        return url_for(fallback)
    
    return next_url


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
            # Check if input is email or username
            login_input = form.username_or_email.data.strip()
            
            if '@' in login_input:
                # It's an email
                user = User.query.filter_by(email=login_input).first()
            else:
                # It's a username
                user = User.query.filter_by(username=login_input).first()
                
            if user and user.check_password(form.password.data):
                # Check if user is active
                if not user.is_active:
                    flash('Ваша учетная запись неактивна. Пожалуйста, обратитесь к администратору.', 'danger')
                    return render_template('auth/login.html', form=form)

                # Log in the user
                login_user(user, remember=form.remember_me.data)

                # Update last login timestamp
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()

                # Redirect to requested page or dashboard
                # Check both GET args and POST form data for next parameter
                next_page = request.args.get('next') or request.form.get('next')
                safe_url = get_safe_redirect_url(next_page)
                return redirect(safe_url)
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

                # Grant default modules to the new user
                from app.modules.service import ModuleService
                try:
                    ModuleService.grant_default_modules_to_user(user.id)
                except Exception as module_error:
                    # Log the error but don't fail registration
                    print(f"Warning: Failed to grant default modules to user {user.id}: {module_error}")

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


@auth.route('/profile')
@login_required
def profile():
    """Basic profile view"""
    return render_template('auth/profile.html', user=current_user)


@auth.route('/profile', methods=['POST'])
@login_required  
def profile_update():
    """Basic profile update"""
    username_or_email = request.form.get('username_or_email')
    email = request.form.get('email')
    
    if username_or_email:
        current_user.username = username_or_email
    if email:
        current_user.email = email
        
    try:
        db.session.commit()
        flash('Профиль обновлен успешно.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ошибка при обновлении профиля.', 'danger')
    
    return render_template('auth/profile.html', user=current_user)


@auth.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Basic password change"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_user.check_password(current_password):
            flash('Текущий пароль неверен.', 'danger')
        elif new_password != confirm_password:
            flash('Новые пароли не совпадают.', 'danger')  
        else:
            current_user.set_password(new_password)
            try:
                db.session.commit()
                flash('Пароль изменен успешно.', 'success')
            except Exception as e:
                db.session.rollback()
                flash('Ошибка при изменении пароля.', 'danger')
    
    return render_template('auth/change_password.html')