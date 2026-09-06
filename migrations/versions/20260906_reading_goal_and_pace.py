"""Personal daily reading goal; explicit lesson pace for existing users.

Lesson audit item 14: reading becomes optional unless the learner sets a
daily goal (study_settings.reading_minutes_per_day, 0 = optional), and the
number of curriculum lessons per day is the learner's explicit choice
(users.plan_difficulty: light=1, normal=2, intensive=3). Existing accounts
keep their effective pace: the automatic ladder kept them on one lesson a
day, so 'normal' (the never-used column default) is rewritten to 'light';
new sign-ups keep the model default of two lessons.

Revision ID: 20260906_reading_goal_and_pace
Revises: 20260906_card_grade_events
Create Date: 2026-09-06
"""
import sqlalchemy as sa
from alembic import op


revision = '20260906_reading_goal_and_pace'
down_revision = '20260906_card_grade_events'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'study_settings',
        sa.Column('reading_minutes_per_day', sa.SmallInteger(), nullable=False, server_default='0'),
    )
    op.execute("UPDATE users SET plan_difficulty = 'light' WHERE plan_difficulty = 'normal'")


def downgrade():
    op.drop_column('study_settings', 'reading_minutes_per_day')
