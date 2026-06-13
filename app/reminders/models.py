from datetime import datetime, timezone

from app.utils.db import db


class ReminderLog(db.Model):
    __tablename__ = 'reminder_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    template = db.Column(db.String(64), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # User-local-day dedup key. Unique (user_id, sent_on) prevents concurrent
    # /admin/reminders/send requests from double-emailing a user (audit E-079).
    sent_on = db.Column(db.Date, nullable=True)
    sent_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Tracking.
    token = db.Column(db.String(32), unique=True, nullable=False)
    opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, nullable=False, default=0)
    clicked_at = db.Column(db.DateTime, nullable=True)
    click_count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.Index('ix_reminder_logs_template_sent_at', 'template', 'sent_at'),
    )

    # Отношения
    user = db.relationship('User', foreign_keys=[user_id], backref='received_reminders')
    admin = db.relationship('User', foreign_keys=[sent_by], backref='sent_reminders')
