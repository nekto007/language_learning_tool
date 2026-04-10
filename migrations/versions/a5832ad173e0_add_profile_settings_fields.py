"""add_profile_settings_fields

Revision ID: a5832ad173e0
Revises: 05212962d037
Create Date: 2026-04-10 12:46:03.048234

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a5832ad173e0'
down_revision = '05212962d037'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('timezone', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('daily_goal_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('notify_email_reminders', sa.Boolean(), server_default='true', nullable=False))
        batch_op.add_column(sa.Column('notify_in_app_achievements', sa.Boolean(), server_default='true', nullable=False))
        batch_op.add_column(sa.Column('notify_in_app_streaks', sa.Boolean(), server_default='true', nullable=False))
        batch_op.add_column(sa.Column('notify_in_app_weekly', sa.Boolean(), server_default='true', nullable=False))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notify_in_app_weekly')
        batch_op.drop_column('notify_in_app_streaks')
        batch_op.drop_column('notify_in_app_achievements')
        batch_op.drop_column('notify_email_reminders')
        batch_op.drop_column('daily_goal_minutes')
        batch_op.drop_column('timezone')
