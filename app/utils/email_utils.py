import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import render_template


class EmailSender:
    def __init__(self):
        self.email_host = os.environ.get('EMAIL_HOST')
        self.email_port = int(os.environ.get('EMAIL_PORT', 587))
        self.email_user = os.environ.get('EMAIL_HOST_USER')
        self.email_password = os.environ.get('EMAIL_HOST_PASSWORD')
        self.use_tls = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
        self.default_from_email = os.environ.get('DEFAULT_FROM_EMAIL')

    def send_email(self, subject, to_email, template_name, context=None):
        """
        Отправляет электронное письмо с использованием шаблона.

        Args:
            subject (str): Тема письма
            to_email (str): Адрес получателя
            template_name (str): Имя шаблона (без расширения)
            context (dict, optional): Словарь с контекстом для шаблона. По умолчанию None.

        Returns:
            bool: True, если отправка успешна, False в противном случае
        """
        if context is None:
            context = {}

        # Подготовка письма
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.default_from_email
        msg['To'] = to_email

        # Рендеринг HTML и текстового шаблона
        html_body = render_template(f'emails/{template_name}.html', **context)
        text_body = render_template(f'emails/{template_name}.txt', **context)

        # Добавление частей письма
        part1 = MIMEText(text_body, 'plain')
        part2 = MIMEText(html_body, 'html')
        msg.attach(part1)
        msg.attach(part2)

        try:
            # Подключение к SMTP-серверу
            with smtplib.SMTP(self.email_host, self.email_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.email_user, self.email_password)
                server.send_message(msg)
            return True
        except Exception as e:
            # В реальном приложении здесь должен быть логгер
            print(f"Error sending email: {str(e)}")
            return False


# Создаем экземпляр для использования в приложении
email_sender = EmailSender()