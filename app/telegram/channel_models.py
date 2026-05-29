"""
Models for the Telegram channel auto-publisher.

A ``ChannelPost`` row is created by the publisher whenever it picks a piece of
content (a word, a grammar topic, or a manual entry) and assigns it a future
publication slot. The same row is later updated when the scheduler actually
delivers the message to the channel.

Decoupling content selection from delivery has two benefits: it surfaces an
auditable queue for the admin UI, and it makes the publisher idempotent —
a re-run never duplicates a post because the queue row already exists.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Index, Integer, String, Text
)

from app.utils.db import db


# Kinds of channel posts. Constants live alongside the model to keep the
# allowed values self-documenting; the publisher tests against the same set.
KIND_WORD = 'word_of_day'
KIND_GRAMMAR = 'grammar_tip'
KIND_MISTAKE = 'mistake_of_day'
KIND_MANUAL = 'manual'
ALLOWED_KINDS = {KIND_WORD, KIND_GRAMMAR, KIND_MISTAKE, KIND_MANUAL}

# Lifecycle states. ``queued`` rows are eligible for publishing once their
# ``scheduled_for`` arrives; ``published`` is terminal-success; ``failed``
# is terminal-error; ``skipped`` means an operator cancelled before send.
STATUS_QUEUED = 'queued'
STATUS_PUBLISHED = 'published'
STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'
ALLOWED_STATUSES = {STATUS_QUEUED, STATUS_PUBLISHED, STATUS_FAILED, STATUS_SKIPPED}


class ChannelPost(db.Model):
    """Single scheduled or published post in the Telegram channel queue."""

    __tablename__ = 'telegram_channel_posts'

    id = Column(Integer, primary_key=True)

    # Kind: word_of_day / grammar_tip / manual. Drives picker reuse and
    # admin grouping. Not enforced via DB enum to keep migrations simple;
    # the model layer validates on write.
    kind = Column(String(32), nullable=False)

    # Reference to source content. Nullable for kind='manual' (the post is
    # free-form, no DB content backs it). We deliberately store the content
    # type as a string instead of joining FKs, so deleting a word or grammar
    # topic doesn't cascade-delete the historical channel post — the snapshot
    # in ``text_snapshot`` keeps the historical record intact.
    content_ref_type = Column(String(32), nullable=True)
    content_ref_id = Column(Integer, nullable=True)

    # When the scheduler is allowed to publish this post (UTC, naive).
    scheduled_for = Column(DateTime, nullable=False)

    # When the publisher actually delivered the message (UTC, naive). Null
    # until published.
    published_at = Column(DateTime, nullable=True)

    # Telegram message_id returned by sendMessage on success. Useful for
    # later edits, deletions, or building a permalink via t.me/c/<chat>/<id>.
    message_id = Column(BigInteger, nullable=True)

    # Lifecycle state. See ALLOWED_STATUSES.
    status = Column(String(16), nullable=False, default=STATUS_QUEUED)

    # The exact text that was scheduled/sent. Captured at queue time so the
    # admin UI shows what will go out (or what went out historically), even
    # if the underlying DB row is later edited.
    text_snapshot = Column(Text, nullable=False, default='')

    # Last error message when status='failed'. Truncated to keep rows small.
    error = Column(String(500), nullable=True)

    # Whether this post was inserted by an admin (vs by the auto-picker).
    is_manual = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    __table_args__ = (
        # publish_due() looks up queued posts whose scheduled_for has passed.
        Index('idx_channel_posts_status_due', 'status', 'scheduled_for'),
        # Dedup picker checks recent posts of the same content kind+ref.
        Index('idx_channel_posts_kind_ref', 'kind', 'content_ref_type', 'content_ref_id'),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelPost id={self.id} kind={self.kind} "
            f"status={self.status} scheduled_for={self.scheduled_for}>"
        )
