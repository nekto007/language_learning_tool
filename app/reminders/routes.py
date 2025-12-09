"""
Система отправки напоминаний пользователям языкового приложения
"""
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc

from app.auth.models import User
from app.reminders.models import ReminderLog
from app.utils.db import db

reminders = Blueprint('reminders', __name__, url_prefix='/admin/reminders')

# Настройка логирования
logger = logging.getLogger(__name__)

# Конфигурация email
EMAIL_HOST = os.environ.get('EMAIL_HOST')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 25))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL')


def get_user_by_id(user_id):
    """
    Получает пользователя по ID.
    Используется в шаблонах как вспомогательная функция.
    """
    return User.query.get(user_id)


@reminders.app_template_filter()
def get_user_by_id_filter(user_id):
    return get_user_by_id(user_id)


@reminders.context_processor
def utility_processor():
    return dict(get_user_by_id=get_user_by_id)


def send_email(to_email, subject, html_content, from_email=DEFAULT_FROM_EMAIL):
    """
    Отправляет электронное письмо пользователю.

    Args:
        to_email (str): Email получателя
        subject (str): Тема письма
        html_content (str): HTML-содержимое письма
        from_email (str): От кого (по умолчанию берётся из настроек)

    Returns:
        bool: True если отправка успешна, иначе False
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email

        part = MIMEText(html_content, 'html')
        msg.attach(part)

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            if EMAIL_USE_TLS:
                server.starttls()

            if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
            server.send_message(msg)

        logger.info(f"Письмо успешно отправлено на {to_email}")
        return True

    except Exception as e:
        logger.error(f"Ошибка при отправке письма на {to_email}: {str(e)}")
        return False


def get_inactive_users(days=7):
    """
    Получает список пользователей, которые не входили в систему более указанного количества дней.
    Если days=0, возвращает всех активных пользователей.

    Args:
        days (int): Количество дней неактивности (0 = все пользователи)

    Returns:
        list: Список пользователей
    """
    if days == 0:
        # Вернуть всех активных пользователей
        return User.query.filter(User.active == True).all()

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    inactive_users = User.query.filter(
        (User.last_login < cutoff_date) | (User.last_login.is_(None))
    ).filter(User.active == True).all()

    return inactive_users


@reminders.route('/', methods=['GET'])
@login_required
def reminder_dashboard():
    """
    Панель управления напоминаниями для администраторов.
    """
    if not current_user.is_admin:
        flash('Доступ запрещен. Требуются права администратора.', 'danger')
        return redirect(url_for('main.index'))

    # Получаем параметры фильтрации из запроса
    inactive_days = request.args.get('inactive_days', 7, type=int)

    # Получаем неактивных пользователей
    inactive_users = get_inactive_users(days=inactive_days)

    # Получаем статистику по отправленным напоминаниям
    reminders_sent = ReminderLog.query.order_by(desc(ReminderLog.sent_at)).limit(50).all()

    now = datetime.now(timezone.utc)

    return render_template(
        'admin/reminders/dashboard.html',
        inactive_users=inactive_users,
        inactive_days=inactive_days,
        reminders_sent=reminders_sent,
        now=now
    )


@reminders.route('/send', methods=['POST'])
@login_required
def send_reminders():
    """
    Отправляет напоминания выбранным пользователям.
    """
    if not current_user.is_admin:
        flash('Доступ запрещен. Требуются права администратора.', 'danger')
        return redirect(url_for('main.index'))

    user_ids = request.form.getlist('user_ids')
    reminder_template = request.form.get('reminder_template', 'default')
    custom_subject = request.form.get('custom_subject', 'Пора вернуться к изучению английского!')

    if not user_ids:
        flash('Не выбрано ни одного пользователя для отправки напоминаний.', 'warning')
        return redirect(url_for('reminders.reminder_dashboard'))

    users = User.query.filter(User.id.in_(user_ids)).all()
    success_count = 0

    now = datetime.now(timezone.utc)

    for user in users:
        # Формируем HTML-содержимое письма на основе шаблона
        html_content = render_template(
            f'emails/reminders/{reminder_template}.html',
            user=user,
            now=now
        )

        # Отправляем письмо
        if send_email(user.email, custom_subject, html_content):
            # Записываем лог отправки
            log = ReminderLog(
                user_id=user.id,
                template=reminder_template,
                subject=custom_subject,
                sent_by=current_user.id
            )
            db.session.add(log)
            success_count += 1

    # Сохраняем изменения в базе данных
    db.session.commit()

    if success_count > 0:
        flash(f'Успешно отправлено {success_count} напоминаний из {len(users)}.', 'success')
    else:
        flash('Не удалось отправить напоминания. Проверьте настройки SMTP.', 'danger')

    # Возвращаемся на исходную страницу, если она указана
    next_url = request.form.get('next') or request.referrer
    if next_url:
        return redirect(next_url)
    return redirect(url_for('reminders.reminder_dashboard'))


def generate_unsubscribe_token(user):
    """
    Генерирует токен для отписки от рассылки.
    В реальном приложении вы бы использовали более сложную логику
    с секретным ключом для создания подписанного токена.

    Args:
        user (User): Пользователь, для которого генерируется токен

    Returns:
        str: Токен для отписки
    """
    # Простая реализация для примера
    import hashlib
    from time import time

    token_data = f"{user.id}:{user.email}:{int(time())}"
    return hashlib.sha256(token_data.encode()).hexdigest()


@reminders.route('/templates', methods=['GET'])
@login_required
def list_templates():
    """
    Отображает список доступных шаблонов напоминаний.
    """
    if not current_user.is_admin:
        flash('Доступ запрещен. Требуются права администратора.', 'danger')
        return redirect(url_for('main.index'))

    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../templates/emails/reminders')
    template_files = [f.replace('.html', '') for f in os.listdir(templates_dir) if f.endswith('.html')]

    return render_template('admin/reminders/templates.html', templates=template_files)


@reminders.route('/preview/<template_name>', methods=['GET'])
@login_required
def preview_template(template_name):
    """
    Предварительный просмотр шаблона напоминания.
    """
    if not current_user.is_admin:
        flash('Доступ запрещен. Требуются права администратора.', 'danger')
        return redirect(url_for('main.index'))

    try:
        now = datetime.now(timezone.utc)
        unsubscribe_token = "sample_token"

        html = render_template(f'emails/reminders/{template_name}.html', user=current_user,
                               unsubscribe_token=unsubscribe_token, now=now)
        response = make_response(html)
        # Allow iframe embedding from same origin for preview
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
    except Exception as e:
        # Return error directly in iframe instead of redirect
        error_html = f'''
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; color: #721c24; background: #f8d7da;">
            <h3>Ошибка при загрузке шаблона</h3>
            <p>{str(e)}</p>
        </body>
        </html>
        '''
        response = make_response(error_html, 500)
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response


