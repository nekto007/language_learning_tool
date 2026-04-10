import secrets
from datetime import datetime, timezone
from flask_babel import lazy_gettext as _l
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import URLSafeTimedSerializer

from app.auth.forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from app.auth.models import User, ReferralLog
from app.utils.db import db
from app.utils.email_utils import email_sender
from config.settings import Config

auth = Blueprint('auth', __name__)


def _check_referral_achievements(referrer_id: int) -> None:
    """Check and award referral achievements based on referral count."""
    from app.study.models import Achievement, UserAchievement
    from app.notifications.services import notify_achievement

    referral_count = User.query.filter_by(referred_by_id=referrer_id).count()

    milestones = [
        (1, 'first_referral', 'Первое приглашение', '👥', 50),
        (5, 'referrals_5', '5 приглашений', '🤝', 200),
        (10, 'referrals_10', '10 приглашений', '🌟', 500),
    ]

    for threshold, code, name, icon, xp_reward in milestones:
        if referral_count < threshold:
            continue

        # Check if achievement exists, create if not
        ach = Achievement.query.filter_by(code=code).first()
        if not ach:
            ach = Achievement(code=code, name=name, icon=icon, xp_reward=xp_reward, category='referral')
            db.session.add(ach)
            db.session.flush()

        # Check if already awarded
        already = UserAchievement.query.filter_by(user_id=referrer_id, achievement_id=ach.id).first()
        if already:
            continue

        ua = UserAchievement(user_id=referrer_id, achievement_id=ach.id)
        db.session.add(ua)

        # Award XP
        from app.study.models import UserXP
        xp = UserXP.get_or_create(referrer_id)
        xp.add_xp(xp_reward)

        # Notify
        notify_achievement(referrer_id, name, icon)


def _default_fallback() -> str:
    """Return words.dashboard if user has the module, else landing page."""
    from app.modules.service import ModuleService
    if current_user.is_authenticated and ModuleService.is_module_enabled_for_user(current_user.id, 'words'):
        return 'words.dashboard'
    return 'landing.index'


def get_safe_redirect_url(next_url, fallback=None):
    """
    Get a safe redirect URL, checking for security issues.

    SECURITY: Only allows relative paths (starting with /).
    Rejects absolute URLs, protocol-relative URLs (//evil.com),
    and any URL with a scheme or netloc to prevent open redirect attacks.
    """
    if fallback is None:
        fallback = _default_fallback()

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
            return redirect(url_for(_default_fallback()))

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
        return redirect(url_for(_default_fallback()))

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
            return redirect(url_for(_default_fallback()))

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
                    safe_next = get_safe_redirect_url(next_page) if next_page else None
                    if safe_next and safe_next != url_for('words.dashboard'):
                        return redirect(url_for('onboarding.wizard', next=safe_next))
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
            return redirect(url_for(_default_fallback()))

        # Capture ?ref= parameter and store in cookie so it survives form submission
        ref_code = request.args.get('ref', '').strip()
        if ref_code and len(ref_code) <= 16 and ref_code.isalnum() and request.method == 'GET':
            resp = make_response(render_template('auth/register.html', form=RegistrationForm()))
            resp.set_cookie('ref', ref_code, max_age=86400 * 30, httponly=True,
                           samesite='Lax', secure=not current_app.debug)
            return resp

        form = RegistrationForm()

        # Capture query params
        level_param = request.args.get('level', '')
        ref_param = request.args.get('ref', '')

        if form.validate_on_submit():
            user = User(
                username=form.username.data,
                email=form.email.data,
                active=True  # Set user as active by default
            )
            user.set_password(form.password.data)

            # Pre-fill onboarding level from param
            if level_param:
                user.onboarding_level = level_param.upper()

            # Handle referral code
            ref_code = ref_param or request.form.get('ref')
            if ref_code:
                referrer = User.query.filter_by(referral_code=ref_code).first()
                if referrer:
                    user.referred_by_id = referrer.id

            try:
                db.session.add(user)
                db.session.commit()

                # Process referral
                saved_ref = request.cookies.get('ref')
                if saved_ref and len(saved_ref) <= 16 and saved_ref.isalnum():
                    try:
                        referrer = User.query.filter_by(referral_code=saved_ref).first()
                        if referrer and referrer.id != user.id:
                            referral_log = ReferralLog(referrer_id=referrer.id, referred_id=user.id)
                            db.session.add(referral_log)
                            db.session.commit()
                    except (IntegrityError, SQLAlchemyError):
                        current_app.logger.warning(
                            "Referral processing failed for ref=%s", saved_ref, exc_info=True
                        )
                        db.session.rollback()  # Don't fail registration over referral

                # Grant default modules to the new user
                from app.modules.service import ModuleService
                modules_granted = False
                try:
                    ModuleService.grant_default_modules_to_user(user.id)
                    modules_granted = True
                except Exception:
                    current_app.logger.warning("Module granting failed for user=%s, retrying", user.id, exc_info=True)
                    db.session.rollback()
                    user = db.session.merge(user)
                    # Retry once after rollback
                    try:
                        ModuleService.grant_default_modules_to_user(user.id)
                        modules_granted = True
                    except Exception:
                        current_app.logger.error("Module granting failed on retry for user=%s", user.id, exc_info=True)
                        db.session.rollback()
                        user = db.session.merge(user)

                # Auto-login after registration
                login_user(user)
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()

                # Send welcome email (may be slow if mail server is unresponsive)
                try:
                    dashboard_url = url_for(_default_fallback(), _external=True)
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
                    current_app.logger.warning("Welcome email failed for user=%s", user.email, exc_info=True)

                flash('Добро пожаловать! Ваш аккаунт создан.', 'success')
                resp = redirect(url_for('onboarding.wizard'))
                resp.delete_cookie('ref')
                return resp
            except Exception as e:
                db.session.rollback()
                import logging
                logging.getLogger(__name__).error(f"Registration failed: {e}")
                flash('Регистрация не удалась. Попробуйте позже.', 'danger')

        # Social proof
        learner_count = User.query.filter_by(active=True).count()

        return render_template('auth/register.html', form=form,
                               learner_count=learner_count,
                               level_param=level_param,
                               ref_param=ref_param)
    
        return render_template('auth/register.html', form=form)

    return _register()


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('auth.login'))


def _get_profile_stats(user_id: int) -> dict:
    """Gather learning stats for profile page."""
    from app.study.models import UserWord, UserXP
    from app.curriculum.models import LessonProgress
    from app.achievements.models import UserStatistics
    from app.telegram.queries import get_current_streak
    from sqlalchemy import func

    # Words learned (any status means user is studying it)
    total_words = UserWord.query.filter_by(user_id=user_id).count()

    # Lessons completed
    lessons_completed = LessonProgress.query.filter_by(
        user_id=user_id, status='completed'
    ).count()

    # XP and level
    user_xp = UserXP.query.filter_by(user_id=user_id).first()
    xp_level = user_xp.level if user_xp else 1
    total_xp = user_xp.total_xp if user_xp else 0

    # Streak
    current_streak = get_current_streak(user_id)

    # Streak record from UserStatistics
    user_stats = UserStatistics.query.filter_by(user_id=user_id).first()
    longest_streak = user_stats.longest_streak_days if user_stats else current_streak

    return {
        'total_words': total_words,
        'lessons_completed': lessons_completed,
        'xp_level': xp_level,
        'total_xp': total_xp,
        'current_streak': current_streak,
        'longest_streak': max(longest_streak, current_streak),
    }


# Valid timezone choices for the settings form
TIMEZONE_CHOICES = [
    'Europe/Moscow', 'Europe/London', 'Europe/Berlin', 'Europe/Paris',
    'America/New_York', 'America/Chicago', 'America/Los_Angeles',
    'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Dubai', 'Asia/Kolkata',
    'Australia/Sydney', 'Pacific/Auckland', 'UTC',
]


@auth.route('/profile')
@login_required
def profile():
    """Profile view with learning stats and settings."""
    stats = _get_profile_stats(current_user.id)

    # Account age in days
    account_age_days = 0
    if current_user.created_at:
        delta = datetime.now(timezone.utc) - current_user.created_at.replace(tzinfo=timezone.utc) if current_user.created_at.tzinfo is None else datetime.now(timezone.utc) - current_user.created_at
        account_age_days = delta.days

    return render_template(
        'auth/profile.html',
        user=current_user,
        stats=stats,
        account_age_days=account_age_days,
        timezone_choices=TIMEZONE_CHOICES,
    )


@auth.route('/profile', methods=['POST'])
@login_required
def profile_update():
    """Save profile settings: timezone, daily goal, notification preferences."""
    section = request.form.get('section', '')

    if section == 'settings':
        tz = request.form.get('timezone', '').strip()
        if tz in TIMEZONE_CHOICES:
            current_user.timezone = tz

        goal = request.form.get('daily_goal_minutes', '')
        if goal.isdigit():
            val = int(goal)
            if 5 <= val <= 120:
                current_user.daily_goal_minutes = val

    elif section == 'notifications':
        current_user.notify_email_reminders = 'notify_email_reminders' in request.form
        current_user.notify_in_app_achievements = 'notify_in_app_achievements' in request.form
        current_user.notify_in_app_streaks = 'notify_in_app_streaks' in request.form
        current_user.notify_in_app_weekly = 'notify_in_app_weekly' in request.form

    try:
        db.session.commit()
        flash('Настройки сохранены.', 'success')
    except Exception:
        db.session.rollback()
        flash('Ошибка при сохранении настроек.', 'danger')

    return redirect(url_for('auth.profile'))


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


@auth.route('/referrals')
@login_required
def referrals():
    """Referral dashboard: shows user's referral code, link, and referred users."""
    from datetime import timedelta

    # Ensure user has a referral code
    current_user.ensure_referral_code()

    # Get referred users
    referred_users = (
        User.query
        .filter_by(referred_by_id=current_user.id)
        .order_by(User.created_at.desc())
        .all()
    )

    referral_link = url_for('auth.register', ref=current_user.referral_code, _external=True)

    # Active referred users: those who logged in within last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    active_referred = 0
    for u in referred_users:
        if u.last_login:
            login_dt = u.last_login if u.last_login.tzinfo else u.last_login.replace(tzinfo=timezone.utc)
            if login_dt > thirty_days_ago:
                active_referred += 1

    # XP earned from referrals (100 XP per referred user)
    total_referral_xp = len(referred_users) * 100

    return render_template(
        'auth/referrals.html',
        referral_code=current_user.referral_code,
        referral_link=referral_link,
        referred_users=referred_users,
        referral_count=len(referred_users),
        active_referred=active_referred,
        total_referral_xp=total_referral_xp,
    )


@auth.route('/u/<username>', strict_slashes=False)
def public_profile(username: str):
    """Public user achievement showcase — no login required."""
    from flask import abort
    from app.study.models import UserXP, UserAchievement, Achievement
    from app.telegram.queries import get_current_streak
    from app.curriculum.models import LessonProgress
    from sqlalchemy import func

    user = User.query.filter_by(username=username, active=True).first()
    if not user:
        abort(404)

    # XP and level
    user_xp = UserXP.query.filter_by(user_id=user.id).first()
    level = user_xp.level if user_xp else 1
    total_xp = user_xp.total_xp if user_xp else 0

    # Streak
    streak = get_current_streak(user.id)

    # Achievements
    achievements = (
        db.session.query(Achievement, UserAchievement.earned_at)
        .join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
        .filter(UserAchievement.user_id == user.id)
        .order_by(UserAchievement.earned_at.desc())
        .all()
    )

    # Lessons completed
    lessons_completed = LessonProgress.query.filter_by(
        user_id=user.id, status='completed'
    ).count()

    meta_description = (
        f'{user.username} — Level {level}, '
        f'{streak}-day streak on LLT English. '
        f'{lessons_completed} lessons completed.'
    )

    return render_template(
        'auth/public_profile.html',
        profile_user=user,
        level=level,
        total_xp=total_xp,
        streak=streak,
        achievements=achievements,
        lessons_completed=lessons_completed,
        meta_description=meta_description,
    )


@auth.route('/streak/<username>', strict_slashes=False)
def public_streak(username: str):
    """Public streak page with activity calendar."""
    from flask import abort
    from app.achievements.streak_service import get_streak_calendar

    user = User.query.filter_by(username=username, active=True).first()
    if not user:
        abort(404)

    calendar = get_streak_calendar(user.id, days=90)

    meta_description = (
        f'{user.username} имеет стрик {calendar["current_streak"]} дней '
        f'на LLT English! Всего {calendar["total_active_days"]} дней активности.'
    )

    return render_template(
        'achievements/public_streak.html',
        profile_user=user,
        calendar=calendar,
        meta_description=meta_description,
    )


@auth.route('/unsubscribe')
def unsubscribe():
    """One-click email unsubscribe via token."""
    token = request.args.get('token')
    if not token:
        flash('Неверная ссылка для отписки.', 'danger')
        return redirect(url_for('landing.index'))

    user = User.query.filter_by(email_unsubscribe_token=token).first()
    if not user:
        flash('Неверная ссылка для отписки.', 'danger')
        return redirect(url_for('landing.index'))

    # Mark user as unsubscribed permanently
    user.email_unsubscribe_token = None
    user.email_opted_out = True
    db.session.commit()

    flash('Вы отписаны от рассылки.', 'success')
    return redirect(url_for('landing.index'))