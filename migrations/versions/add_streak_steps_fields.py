"""add steps_done and steps_total to streak_events

Revision ID: add_streak_steps_fields
Revises: None
Create Date: 2026-03-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_streak_steps_fields'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return table in inspector.get_table_names()


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c['name'] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _table_exists('streak_events'):
        return
    if not _column_exists('streak_events', 'steps_done'):
        op.add_column('streak_events', sa.Column('steps_done', sa.Integer(), nullable=True))
    if not _column_exists('streak_events', 'steps_total'):
        op.add_column('streak_events', sa.Column('steps_total', sa.Integer(), nullable=True))


def downgrade():
    if not _table_exists('streak_events'):
        return
    if _column_exists('streak_events', 'steps_total'):
        op.drop_column('streak_events', 'steps_total')
    if _column_exists('streak_events', 'steps_done'):
        op.drop_column('streak_events', 'steps_done')
