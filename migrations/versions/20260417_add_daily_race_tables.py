"""Add daily race tables for the mission friendly-race feature.

Creates two tables:

- ``daily_races``: one row per daily race cohort (up to 5 users per calendar
  date).
- ``daily_race_participants``: membership row per user per race_date. A user
  can only belong to one race per calendar date (enforced by a unique
  constraint on ``(user_id, race_date)``).

Revision ID: 20260417_daily_race
Revises: 20260417_add_ua_seen_at
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = '20260417_daily_race'
down_revision = '20260417_add_ua_seen_at'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_races',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('race_date', sa.Date(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index('idx_daily_races_date', 'daily_races', ['race_date'])

    op.create_table(
        'daily_race_participants',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'race_id',
            sa.Integer(),
            sa.ForeignKey('daily_races.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('race_date', sa.Date(), nullable=False),
        sa.Column(
            'points',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column(
            'joined_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.UniqueConstraint(
            'user_id', 'race_date', name='uq_daily_race_participants_user_date'
        ),
    )
    op.create_index(
        'idx_daily_race_participants_user_date',
        'daily_race_participants',
        ['user_id', 'race_date'],
    )
    op.create_index(
        'idx_daily_race_participants_race_id',
        'daily_race_participants',
        ['race_id'],
    )


def downgrade():
    op.drop_index(
        'idx_daily_race_participants_race_id', table_name='daily_race_participants'
    )
    op.drop_index(
        'idx_daily_race_participants_user_date', table_name='daily_race_participants'
    )
    op.drop_table('daily_race_participants')
    op.drop_index('idx_daily_races_date', table_name='daily_races')
    op.drop_table('daily_races')
