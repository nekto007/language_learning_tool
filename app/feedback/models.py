"""Feedback model + reply thread: in-app product feedback channel.

The widget posts to ``/api/feedback`` (multipart now — optional PNG/JPEG
screenshot, plus client-collected page-info meta). Admin and user can
trade replies via ``FeedbackReply`` rows; notifications fan-out keeps
both sides aware of new activity.
"""

from datetime import datetime, timezone

from app.utils.db import db

FEEDBACK_CATEGORIES = ('bug', 'idea', 'question')
FEEDBACK_STATUSES = ('new', 'seen', 'in_progress', 'resolved', 'reopened')
FEEDBACK_PRIORITIES = ('low', 'normal', 'high', 'critical')

MESSAGE_MAX_LENGTH = 4000
URL_MAX_LENGTH = 2048
USER_AGENT_MAX_LENGTH = 512
LOCALE_MAX_LENGTH = 32
TIMEZONE_MAX_LENGTH = 64
PLATFORM_MAX_LENGTH = 64
SCREENSHOT_PATH_MAX_LENGTH = 512
REPLY_BODY_MAX_LENGTH = 4000


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
    priority = db.Column(
        db.String(16),
        nullable=False,
        default='normal',
        server_default='normal',
    )
    assignee_admin_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    reopened_at = db.Column(db.DateTime, nullable=True)

    # Optional screenshot uploaded with the report (relative path under
    # uploads/feedback). Never trust the client extension — file_security
    # validates magic bytes + Pillow.format on the way in.
    screenshot_path = db.Column(
        db.String(SCREENSHOT_PATH_MAX_LENGTH),
        nullable=True,
    )

    # Client environment snapshot — useful when triaging bug reports.
    viewport_width = db.Column(db.Integer, nullable=True)
    viewport_height = db.Column(db.Integer, nullable=True)
    screen_width = db.Column(db.Integer, nullable=True)
    screen_height = db.Column(db.Integer, nullable=True)
    device_pixel_ratio = db.Column(db.Float, nullable=True)
    locale = db.Column(db.String(LOCALE_MAX_LENGTH), nullable=True)
    timezone = db.Column(db.String(TIMEZONE_MAX_LENGTH), nullable=True)
    platform = db.Column(db.String(PLATFORM_MAX_LENGTH), nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=db.func.now(),
    )

    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        lazy='joined',
        viewonly=True,
    )
    assignee = db.relationship(
        'User',
        foreign_keys=[assignee_admin_id],
        lazy='joined',
        viewonly=True,
    )
    replies = db.relationship(
        'FeedbackReply',
        backref='feedback',
        cascade='all, delete-orphan',
        order_by='FeedbackReply.created_at.asc()',
        lazy='select',
    )

    def __repr__(self) -> str:
        return f'<Feedback id={self.id} category={self.category} status={self.status}>'


class FeedbackReply(db.Model):
    """One message in the feedback thread (user ⇄ admin)."""

    __tablename__ = 'feedback_replies'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(
        db.Integer,
        db.ForeignKey('feedback.id', ondelete='CASCADE'),
        nullable=False,
    )
    author_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Snapshot of author role at write time — User.is_admin may flip later
    # but the thread history must read stable.
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=db.func.now(),
    )

    author = db.relationship('User', lazy='joined', viewonly=True)

    __table_args__ = (
        db.Index('idx_feedback_replies_feedback_created', 'feedback_id', 'created_at'),
    )

    def __repr__(self) -> str:
        return f'<FeedbackReply id={self.id} feedback={self.feedback_id} admin={self.is_admin}>'


def create_feedback(
    user_id: int | None,
    category: str,
    message: str,
    url: str | None,
    user_agent: str | None,
    *,
    priority: str = 'normal',
    screenshot_path: str | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    screen_width: int | None = None,
    screen_height: int | None = None,
    device_pixel_ratio: float | None = None,
    locale: str | None = None,
    timezone: str | None = None,
    platform: str | None = None,
) -> Feedback:
    """Insert + flush a Feedback row. Caller commits."""

    def _trim(value: str | None, limit: int) -> str | None:
        if not value:
            return None
        return value[:limit]

    row = Feedback(
        user_id=user_id,
        category=category,
        message=message,
        url=_trim(url, URL_MAX_LENGTH),
        user_agent=_trim(user_agent, USER_AGENT_MAX_LENGTH),
        status='new',
        priority=priority if priority in FEEDBACK_PRIORITIES else 'normal',
        screenshot_path=_trim(screenshot_path, SCREENSHOT_PATH_MAX_LENGTH),
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        screen_width=screen_width,
        screen_height=screen_height,
        device_pixel_ratio=device_pixel_ratio,
        locale=_trim(locale, LOCALE_MAX_LENGTH),
        timezone=_trim(timezone, TIMEZONE_MAX_LENGTH),
        platform=_trim(platform, PLATFORM_MAX_LENGTH),
    )
    db.session.add(row)
    db.session.flush()
    return row


def create_reply(
    feedback_id: int,
    author_user_id: int | None,
    body: str,
    *,
    is_admin: bool,
) -> FeedbackReply:
    """Append a reply to a feedback thread. Caller commits.

    Touches ``Feedback.updated_at`` so the inbox sort order reflects activity.
    """
    body = (body or '').strip()
    if not body:
        raise ValueError('reply body must not be empty')
    if len(body) > REPLY_BODY_MAX_LENGTH:
        body = body[:REPLY_BODY_MAX_LENGTH]

    reply = FeedbackReply(
        feedback_id=feedback_id,
        author_user_id=author_user_id,
        is_admin=bool(is_admin),
        body=body,
    )
    db.session.add(reply)

    parent = Feedback.query.get(feedback_id)
    if parent is not None:
        parent.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if is_admin and parent.status in ('new', 'seen', 'reopened'):
            # Admin response means the ticket is actively being handled.
            parent.status = 'in_progress'
        elif not is_admin and parent.status == 'resolved':
            # A user follow-up after closure is a real signal: reopen it.
            parent.status = 'reopened'
            parent.reopened_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.session.flush()
    return reply
