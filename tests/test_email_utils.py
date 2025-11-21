"""Unit tests for email_utils.py"""
import pytest
from unittest.mock import patch, MagicMock, call
from app.utils.email_utils import EmailSender


class TestEmailSenderInit:
    """Test EmailSender initialization"""

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_PORT': '587',
        'EMAIL_HOST_USER': 'user@example.com',
        'EMAIL_HOST_PASSWORD': 'password123',
        'EMAIL_USE_TLS': 'true',
        'DEFAULT_FROM_EMAIL': 'noreply@example.com'
    })
    def test_email_sender_init_with_env_vars(self):
        """Test EmailSender initialization with environment variables"""
        sender = EmailSender()

        assert sender.email_host == 'smtp.example.com'
        assert sender.email_port == 587
        assert sender.email_user == 'user@example.com'
        assert sender.email_password == 'password123'
        assert sender.use_tls is True
        assert sender.default_from_email == 'noreply@example.com'

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.test.com',
        'EMAIL_USE_TLS': 'false'
    }, clear=True)
    def test_email_sender_init_with_defaults(self):
        """Test EmailSender with default values"""
        sender = EmailSender()

        assert sender.email_host == 'smtp.test.com'
        assert sender.email_port == 587  # Default port
        assert sender.use_tls is False

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_PORT': '25'
    }, clear=True)
    def test_email_sender_init_custom_port(self):
        """Test EmailSender with custom port"""
        sender = EmailSender()

        assert sender.email_port == 25


class TestSendEmail:
    """Test send_email method"""

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_PORT': '587',
        'EMAIL_HOST_USER': 'user@example.com',
        'EMAIL_HOST_PASSWORD': 'password123',
        'EMAIL_USE_TLS': 'true',
        'DEFAULT_FROM_EMAIL': 'noreply@example.com'
    })
    @patch('app.utils.email_utils.smtplib.SMTP')
    @patch('app.utils.email_utils.render_template')
    def test_send_email_success(self, mock_render, mock_smtp, app):
        """Test successfully sending email"""
        # Mock templates
        mock_render.side_effect = lambda template, **context: f"Rendered {template}"

        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        sender = EmailSender()

        with app.app_context():
            result = sender.send_email(
                subject='Test Subject',
                to_email='recipient@example.com',
                template_name='welcome',
                context={'name': 'John'}
            )

        assert result is True

        # Verify SMTP calls
        mock_smtp.assert_called_once_with('smtp.example.com', 587)
        mock_server.set_debuglevel.assert_called_once_with(1)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with('user@example.com', 'password123')
        mock_server.send_message.assert_called_once()

        # Verify render_template calls
        assert mock_render.call_count == 2
        mock_render.assert_any_call('emails/welcome.html', name='John')
        mock_render.assert_any_call('emails/welcome.txt', name='John')

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_PORT': '587',
        'EMAIL_HOST_USER': 'user@example.com',
        'EMAIL_HOST_PASSWORD': 'password123',
        'EMAIL_USE_TLS': 'false',
        'DEFAULT_FROM_EMAIL': 'noreply@example.com'
    })
    @patch('app.utils.email_utils.smtplib.SMTP')
    @patch('app.utils.email_utils.render_template')
    def test_send_email_without_tls(self, mock_render, mock_smtp, app):
        """Test sending email without TLS"""
        mock_render.side_effect = lambda template, **context: f"Rendered {template}"

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        sender = EmailSender()

        with app.app_context():
            result = sender.send_email(
                subject='Test Subject',
                to_email='recipient@example.com',
                template_name='test'
            )

        assert result is True
        # Verify starttls was NOT called
        mock_server.starttls.assert_not_called()

    @patch.dict('os.environ', {}, clear=True)
    @patch('app.utils.email_utils.render_template')
    def test_send_email_missing_config(self, mock_render, app):
        """Test sending email with missing configuration"""
        mock_render.side_effect = lambda template, **context: f"Rendered {template}"

        sender = EmailSender()

        with app.app_context():
            result = sender.send_email(
                subject='Test',
                to_email='test@example.com',
                template_name='test'
            )

        assert result is False

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_HOST_USER': 'user@example.com',
        'EMAIL_HOST_PASSWORD': 'password123',
        'DEFAULT_FROM_EMAIL': 'noreply@example.com'
    })
    @patch('app.utils.email_utils.smtplib.SMTP')
    @patch('app.utils.email_utils.render_template')
    def test_send_email_smtp_error(self, mock_render, mock_smtp, app):
        """Test handling SMTP connection error"""
        mock_render.side_effect = lambda template, **context: f"Rendered {template}"

        # Simulate SMTP error
        mock_smtp.side_effect = Exception("SMTP connection failed")

        sender = EmailSender()

        with app.app_context():
            result = sender.send_email(
                subject='Test',
                to_email='test@example.com',
                template_name='test'
            )

        assert result is False

    @patch.dict('os.environ', {
        'EMAIL_HOST': 'smtp.example.com',
        'EMAIL_PORT': '587',
        'EMAIL_HOST_USER': 'user@example.com',
        'EMAIL_HOST_PASSWORD': 'password123',
        'DEFAULT_FROM_EMAIL': 'noreply@example.com'
    })
    @patch('app.utils.email_utils.smtplib.SMTP')
    @patch('app.utils.email_utils.render_template')
    def test_send_email_login_error(self, mock_render, mock_smtp, app):
        """Test handling SMTP login error"""
        mock_render.side_effect = lambda template, **context: f"Rendered {template}"

        mock_server = MagicMock()
        mock_server.login.side_effect = Exception("Authentication failed")
        mock_smtp.return_value.__enter__.return_value = mock_server

        sender = EmailSender()

        with app.app_context():
            result = sender.send_email(
                subject='Test',
                to_email='test@example.com',
                template_name='test'
            )

        assert result is False


class TestEmailSenderInstance:
    """Test the module-level email_sender instance"""

    def test_email_sender_instance_exists(self):
        """Test that email_sender instance is created"""
        from app.utils.email_utils import email_sender

        assert email_sender is not None
        assert isinstance(email_sender, EmailSender)
