"""Append-only log of SRS grades (card_grade_events).

Lesson audit item 11: the adaptive SRS tier measured «recent accuracy» from the
lifetime correct/incorrect counters of recently touched cards, so a learner
returning to an old deck stayed in collapse on years-old misses. Every grade is
now logged with the card state before the answer; retention is read from the
last N grades of REVIEW-state cards.

Revision ID: 20260906_card_grade_events
Revises: 20260829_perfect_day_unique_index
Create Date: 2026-09-06
"""
import sqlalchemy as sa
from alembic import op


revision = '20260906_card_grade_events'
down_revision = '20260829_perfect_day_unique_index'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'card_grade_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column(
            'direction_id', sa.Integer(),
            sa.ForeignKey('user_card_directions.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('word_id', sa.Integer(), nullable=True),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('state_before', sa.String(length=16), nullable=False),
        sa.Column('step_before', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('interval_before', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ease_before', sa.Float(), nullable=True),
        sa.Column('lapses_before', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('state_after', sa.String(length=16), nullable=False),
        sa.Column('interval_after', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ease_after', sa.Float(), nullable=True),
        sa.Column('is_first_review', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('context', sa.String(length=32), nullable=True),
        sa.Column(
            'session_id', sa.Integer(),
            sa.ForeignKey('study_sessions.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('graded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_card_grade_events_user_graded', 'card_grade_events', ['user_id', 'graded_at'])
    op.create_index('ix_card_grade_events_direction', 'card_grade_events', ['direction_id'])


def downgrade():
    op.drop_index('ix_card_grade_events_direction', table_name='card_grade_events')
    op.drop_index('ix_card_grade_events_user_graded', table_name='card_grade_events')
    op.drop_table('card_grade_events')
