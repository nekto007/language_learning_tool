"""Notification model for in-app notification center."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.utils.db import db


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    type = Column(String(50), nullable=False)  # achievement, level_up, streak_milestone, referral, weekly_challenge
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    link = Column(String(500), nullable=True)
    icon = Column(String(10), default='🔔')
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship('User', backref=db.backref('notifications', cascade='all, delete-orphan', passive_deletes=True))

    __table_args__ = (
        Index('idx_notifications_user_read', 'user_id', 'read'),
        Index('idx_notifications_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'link': self.link,
            'icon': self.icon,
            'read': self.read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Notification {self.id} type={self.type} user={self.user_id}>'
