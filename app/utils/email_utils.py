"""SMTP submission with safe outcomes and separate authentication transport."""

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr

from flask import current_app, render_template

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailSubmission:
    """SMTP handoff only. Acceptance never means inbox delivery."""

    accepted: bool
    message_id: str
    error: str | None = None
    smtp_code: int | None = None
    retryable: bool = True


class EmailSender:
    def __init__(self, *, auth=False):
        # Switch the entire transport together; never inherit another provider's
        # credentials when only AUTH_EMAIL_HOST is configured.
        self.dedicated_auth = auth and bool(os.environ.get('AUTH_EMAIL_HOST'))
        prefix = 'AUTH_EMAIL' if self.dedicated_auth else 'EMAIL'
        self.email_host = os.environ.get(prefix + '_HOST')
        self.email_port = int(os.environ.get(prefix + '_PORT') or 587)
        self.email_user = os.environ.get(prefix + '_HOST_USER')
        self.email_password = os.environ.get(prefix + '_HOST_PASSWORD')
        self.use_ssl = os.environ.get(prefix + '_USE_SSL', 'False').lower() == 'true'
        tls_default = 'True' if self.dedicated_auth and not self.use_ssl else 'False'
        self.use_tls = os.environ.get(prefix + '_USE_TLS', tls_default).lower() == 'true'
        self.default_from_email = (
            os.environ.get('AUTH_DEFAULT_FROM_EMAIL') if self.dedicated_auth else None
        ) or os.environ.get('DEFAULT_FROM_EMAIL')
        self.smtp_debug_level = int(os.environ.get('SMTP_DEBUG_LEVEL', 0))
        self.sensitive = auth

    def message_id(self):
        address = parseaddr(self.default_from_email or '')[1]
        domain = address.rsplit('@', 1)[-1] if '@' in address else None
        return make_msgid(domain=domain)

    def send_email(self, subject, to_email, template_name, context=None, *, timeout=None,
                   standalone=False):
        """Compatibility wrapper: True means accepted by configured SMTP."""
        return self.submit_email(
            subject, to_email, template_name, context,
            timeout=timeout, standalone=standalone,
        ).accepted

    def submit_email(self, subject, to_email, template_name, context=None, *, timeout=None,
                     standalone=False, message_id=None):
        """Return safe metadata, without raw SMTP replies or message contents."""
        message_id = message_id or self.message_id()

        def failure(error, smtp_code=None, retryable=True):
            logger.warning('Email submission failed category=%s smtp_code=%s message_id=%s',
                           error, smtp_code, message_id)
            return MailSubmission(False, message_id, error, smtp_code, retryable)

        if (not self.email_host or not self.default_from_email
                or (self.use_tls and self.use_ssl)
                or bool(self.email_user) != bool(self.email_password)):
            return failure('configuration')
        if self.dedicated_auth and not (self.use_tls or self.use_ssl):
            return failure('tls_required')
        context = context or {}
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.default_from_email
        msg['To'] = to_email
        msg['Date'] = formatdate(localtime=False, usegmt=True)
        msg['Message-ID'] = message_id

        try:
            if standalone:
                html_body = current_app.jinja_env.get_template(f'emails/{template_name}.html').render(**context)
                text_body = current_app.jinja_env.get_template(f'emails/{template_name}.txt').render(**context)
            else:
                html_body = render_template(f'emails/{template_name}.html', **context)
                text_body = render_template(f'emails/{template_name}.txt', **context)
            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        except Exception:
            return failure('template', retryable=False)

        try:
            smtp_options = {'timeout': timeout if timeout is not None else 10}
            transport = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
            if self.use_ssl:
                smtp_options['context'] = ssl.create_default_context()
            with transport(self.email_host, self.email_port, **smtp_options) as server:
                sensitive = self.sensitive or template_name == 'mobile_auth_code'
                server.set_debuglevel(0 if sensitive else self.smtp_debug_level)
                if self.use_tls:
                    server.starttls(context=ssl.create_default_context())
                if self.email_user and self.email_password:
                    server.login(self.email_user, self.email_password)
                refused = server.send_message(msg)
                if isinstance(refused, dict) and refused:
                    code = next(iter(refused.values()))[0]
                    return failure('recipient', smtp_code=code, retryable=400 <= code < 500)
            return MailSubmission(True, message_id)
        except smtplib.SMTPRecipientsRefused as error:
            code = next(iter(error.recipients.values()))[0] if error.recipients else None
            return failure('recipient', smtp_code=code, retryable=code is None or 400 <= code < 500)
        except smtplib.SMTPAuthenticationError as error:
            return failure('authentication', smtp_code=error.smtp_code)
        except smtplib.SMTPResponseException as error:
            return failure('smtp', smtp_code=error.smtp_code, retryable=400 <= error.smtp_code < 500)
        except ssl.SSLError:
            return failure('tls')
        except OSError:
            return failure('network')
        except Exception:
            return failure('transport')


email_sender = EmailSender()
auth_email_sender = EmailSender(auth=True)
