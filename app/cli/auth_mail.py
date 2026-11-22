"""Private operational commands for the durable authentication-mail queue."""

import json
import signal
import threading

import click
from sqlalchemy import func

from app.auth.mobile_models import MobileAuthMail, utcnow
from app.auth.mobile_mail import process_auth_mail
from app.utils.db import db


def queue_status():
    """Aggregate metadata only: no addresses, codes, payloads or credentials."""
    now = utcnow()
    counts = dict(db.session.query(MobileAuthMail.status, func.count()).group_by(MobileAuthMail.status).all())
    oldest = db.session.query(func.min(MobileAuthMail.available_at)).filter(
        MobileAuthMail.status == 'pending', MobileAuthMail.available_at <= now,
    ).scalar()
    errors = dict(db.session.query(MobileAuthMail.last_error, func.count()).filter(
        MobileAuthMail.status.in_(['pending', 'failed']), MobileAuthMail.last_error.isnot(None),
    ).group_by(MobileAuthMail.last_error).all())
    return {
        'counts': counts,
        'oldest_due_seconds': max(0, int((now - oldest).total_seconds())) if oldest else 0,
        'errors': errors,
        'accepted_means': 'Configured SMTP accepted submission; recipient delivery is not confirmed.',
    }


def register_auth_mail_commands(app):
    @app.cli.command('auth-mail-status')
    def status_command():
        """Print queue counts and retry lag as JSON, without personal data."""
        click.echo(json.dumps(queue_status(), sort_keys=True))

    @app.cli.command('auth-mail-worker')
    @click.option('--once', is_flag=True, help='Process one bounded batch and exit.')
    @click.option('--interval', type=click.IntRange(1, 60), default=5, show_default=True)
    @click.option('--batch-size', type=click.IntRange(1, 100), default=20, show_default=True)
    def worker_command(once, interval, batch_size):
        """Dedicated OTP worker. PostgreSQL SKIP LOCKED supports multiple workers."""
        stop = threading.Event()
        previous = {}
        if not once:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        try:
            while not stop.is_set():
                try:
                    accepted = process_auth_mail(batch_size, maintenance=False)
                    if once:
                        click.echo(json.dumps({'accepted': accepted}))
                except Exception:
                    db.session.rollback()
                    # Never include an exception which might hold a decrypted code.
                    app.logger.warning('Authentication mail worker batch failed')
                    if once:
                        raise click.ClickException('Authentication mail batch failed') from None
                finally:
                    db.session.remove()
                if once:
                    break
                stop.wait(interval)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
