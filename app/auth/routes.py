import secrets
from datetime import datetime, timezone
from flask_babel import lazy_gettext as _l
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import URLSafeTimedSerializer

from app.auth.forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from app.auth.models import User, ReferralLog
from app.utils.db import db
from app.utils.email_utils import email_sender
from config.settings import Config

auth = Blueprint('auth', __name__)


def get_safe_redirect_url(next_url, fallback='words.dashboard'):
    """
    Get a safe redirect URL, checking for security issues.

    SECURITY: Only allows relative paths (starting with /).
    Rejects absolute URLs, protocol-relative URLs (//evil.com),
    and any URL with a scheme or netloc to prevent open redirect attacks.
    """
    if not next_url:
        return url_for(fallback)

    from urllib.parse import urlparse

    parsed = urlparse(next_url)

    # SECURITY: Reject any URL with scheme or netloc (absolute URLs)
    if parsed.scheme or parsed.netloc:
        return url_for(fallback)

    # SECURITY: Only allow paths starting with / (reject protocol-relative //evil.com)
    if not next_url.startswith('/'):
        return url_for(fallback)

    # SECURITY: Reject backslash tricks (e.g. /\evil.com interpreted as //evil.com)
    if '\\' in next_url:
        return url_for(fallback)

    return next_url


def _get_reset_salt(user: User) -> str:
    """Per-user salt derived from password hash — token auto-invalidates on password change."""
    import hashlib
    pw_hash = user.password_hash or ''
    return 'password-reset-' + hashlib.sha256(pw_hash.encode()).hexdigest()[:16]


def get_reset_token(user_id: int, expiration: int = 3600) -> str:
    """Generate a secure, per-user password reset token."""
    user = User.query.get(user_id)
    if not user:
        raise ValueError(f'User {user_id} not found')
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)
    return serializer.dumps(user_id, salt=_get_reset_salt(user))


def verify_reset_token(token: str, expiration: int = 3600):
    """Verify reset token. Returns user_id or None.

    Token is invalidated when password changes (salt includes password hash).
    """
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)
    # First decode without salt to get user_id, then verify with per-user salt
    try:
        user_id = serializer.loads(token, salt='password-reset-probe', max_age=expiration)
    except Exception:
        # Try all users is not feasible; decode payload without verification to get user_id
        try:
            from itsdangerous import URLSafeTimedSerializer as S
            s = S(Config.SECRET_KEY)
            # loads with any salt just to extract the payload — we re-verify below
            user_id = s.loads_unsafe(token)[1]
        except Exception:
            return None

    if not isinstance(user_id, int):
        return None

    user = User.query.get(user_id)
    if not user:
        return None

    # Now verify with the correct per-user salt
    try:
        verified_id = serializer.loads(token, salt=_get_reset_salt(user), max_age=expiration)
        return verified_id
    except Exception:
        return None


@auth.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    # Import limiter here to avoid circular imports
    from app import limiter
    
    # Apply rate limiting to password reset requests
    @limiter.limit("10 per minute")
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
    @limiter.limit("10 per minute")
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

                # Redirect to onboarding if not completed, preserving next param
                if not user.onboarding_completed:
                    if next_page:
                        return redirect(url_for('onboarding.wizard', next=next_page))
                    return redirect(url_for('onboarding.wizard'))

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
    @limiter.limit("10 per minute")
    def _register():
        if current_user.is_authenticated:
            return redirect(url_for('words.dashboard'))

        # Capture ?ref= parameter and store in cookie so it survives form submission
        ref_code = request.args.get('ref')
        if ref_code and request.method == 'GET':
            resp = make_response(render_template('auth/register.html', form=RegistrationForm()))
            resp.set_cookie('ref', ref_code, max_age=86400 * 30, httponly=True,
                           samesite='Lax', secure=not current_app.debug)
            return resp

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

                # Process referral
                saved_ref = request.cookies.get('ref')
                if saved_ref:
                    try:
                        referrer = User.query.filter_by(referral_code=saved_ref).first()
                        if referrer and referrer.id != user.id:
                            referral_log = ReferralLog(referrer_id=referrer.id, referred_id=user.id)
                            db.session.add(referral_log)
                            db.session.commit()
                    except Exception:
                        current_app.logger.warning(
                            "Referral processing failed for ref=%s", saved_ref, exc_info=True
                        )
                        db.session.rollback()  # Don't fail registration over referral

                # Grant default modules to the new user
                from app.modules.service import ModuleService
                try:
                    ModuleService.grant_default_modules_to_user(user.id)
                except Exception as module_error:
                    # Log the error but don't fail registration
                    print(module_error)

                # Auto-login after registration
                login_user(user)
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()

                # Send welcome email (non-blocking)
                try:
                    dashboard_url = url_for('words.dashboard', _external=True)
                    email_sender.send_email(
                        subject="Добро пожаловать в Language Learning Tool!",
                        to_email=user.email,
                        template_name="welcome",
                        context={
                            "username": user.username,
                            "dashboard_url": dashboard_url,
                        }
                    )
                except Exception:
                    pass  # Don't fail registration if email fails

                flash('Добро пожаловать! Ваш аккаунт создан.', 'success')
                resp = redirect(url_for('onboarding.wizard'))
                resp.delete_cookie('ref')
                return resp
            except Exception as e:
                db.session.rollback()
                import logging
                logging.getLogger(__name__).error(f"Registration failed: {e}")
                flash('Регистрация не удалась. Попробуйте позже.', 'danger')

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