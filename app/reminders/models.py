from datetime import datetime, timezone

from app.utils.db import db


class ReminderLog(db.Model):
    __tablename__ = 'reminder_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    template = db.Column(db.String(64), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sent_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Отношения
    user = db.relationship('User', foreign_keys=[user_id], backref='received_reminders')
    admin = db.relationship('User', foreign_keys=[sent_by], backref='sent_reminders')
