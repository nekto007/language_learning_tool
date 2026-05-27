"""Feedback model: lightweight in-app product feedback channel."""

from datetime import datetime

from app.utils.db import db


FEEDBACK_CATEGORIES = ('bug', 'idea', 'question')
FEEDBACK_STATUSES = ('new', 'seen', 'resolved')

MESSAGE_MAX_LENGTH = 4000
URL_MAX_LENGTH = 2048
USER_AGENT_MAX_LENGTH = 512


class Feedback(db.Model):
    __tablename__ = 'feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    category = db.Column(db.String(16), nullable=False)
    message = db.Column(db.Text, nullable=False)
    url = db.Column(db.String(URL_MAX_LENGTH), nullable=True)
    user_agent = db.Column(db.String(USER_AGENT_MAX_LENGTH), nullable=True)
    status = db.Column(
        db.String(16),
        nullable=False,
        default='new',
        server_default='new',
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.func.now(),
    )

    user = db.relationship('User', lazy='joined', viewonly=True)

    def __repr__(self) -> str:
        return f'<Feedback id={self.id} category={self.category} status={self.status}>'


def create_feedback(
    user_id: int | None,
    category: str,
    message: str,
    url: str | None,
    user_agent: str | None,
) -> Feedback:
    """Insert + flush a Feedback row. Caller commits."""
    row = Feedback(
        user_id=user_id,
        category=category,
        message=message,
        url=(url or None) and url[:URL_MAX_LENGTH],
        user_agent=(user_agent or None) and user_agent[:USER_AGENT_MAX_LENGTH],
        status='new',
    )
    db.session.add(row)
    db.session.flush()
    return row
