"""Feedback v2: screenshots, page-info meta, reply thread.

Adds to ``feedback``:
  - ``screenshot_path`` — relative path under uploads dir for the attached image
  - ``viewport_width`` / ``viewport_height`` — client viewport at submit time
  - ``screen_width`` / ``screen_height`` — full device screen
  - ``device_pixel_ratio`` — DPR (HiDPI flag)
  - ``locale`` — navigator.language
  - ``timezone`` — Intl.DateTimeFormat().resolvedOptions().timeZone
  - ``platform`` — navigator.platform (best-effort)
  - ``updated_at`` — touched on reply / status change

Creates ``feedback_replies`` — append-only chat thread between admin and the
submitting user. ``is_admin`` recorded at write time so we don't depend on
``User.is_admin`` later (admin status may change).

Revision ID: 20260603_feedback_chat
Revises: 20260602_book_is_published
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = '20260603_feedback_chat'
down_revision = '20260602_book_is_published'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedback', sa.Column('screenshot_path', sa.String(length=512), nullable=True))
    op.add_column('feedback', sa.Column('viewport_width', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('viewport_height', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('screen_width', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('screen_height', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('device_pixel_ratio', sa.Float(), nullable=True))
    op.add_column('feedback', sa.Column('locale', sa.String(length=32), nullable=True))
    op.add_column('feedback', sa.Column('timezone', sa.String(length=64), nullable=True))
    op.add_column('feedback', sa.Column('platform', sa.String(length=64), nullable=True))
    op.add_column(
        'feedback',
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        'feedback_replies',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('feedback_id', sa.Integer(), nullable=False),
        sa.Column('author_user_id', sa.Integer(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['feedback_id'], ['feedback.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_feedback_replies_feedback_created',
        'feedback_replies',
        ['feedback_id', 'created_at'],
    )


def downgrade():
    op.drop_index('idx_feedback_replies_feedback_created', table_name='feedback_replies')
    op.drop_table('feedback_replies')

    op.drop_column('feedback', 'updated_at')
    op.drop_column('feedback', 'platform')
    op.drop_column('feedback', 'timezone')
    op.drop_column('feedback', 'locale')
    op.drop_column('feedback', 'device_pixel_ratio')
    op.drop_column('feedback', 'screen_height')
    op.drop_column('feedback', 'screen_width')
    op.drop_column('feedback', 'viewport_height')
    op.drop_column('feedback', 'viewport_width')
    op.drop_column('feedback', 'screenshot_path')
