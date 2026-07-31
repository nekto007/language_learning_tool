"""Track recovery for difficult SRS cards per direction.

Revision ID: 20260731_card_recovery_state
Revises: 20260714_lesson_retry_scores
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = '20260731_card_recovery_state'
down_revision = '20260714_lesson_retry_scores'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_card_directions',
        sa.Column('difficulty_score', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'user_card_directions',
        sa.Column('recovery_required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column(
        'user_card_directions',
        sa.Column('recovery_successes', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('user_card_directions', sa.Column('recovery_due_at', sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE user_card_directions "
        "SET difficulty_score = CASE "
        "WHEN lapses >= 5 THEN 10 "
        "ELSE lapses * 2 END, "
        "recovery_required = CASE WHEN lapses >= 3 THEN true ELSE false END"
    )
    op.create_index(
        'idx_card_direction_recovery_due',
        'user_card_directions',
        ['recovery_required', 'recovery_due_at'],
    )


def downgrade():
    op.drop_index('idx_card_direction_recovery_due', table_name='user_card_directions')
    op.drop_column('user_card_directions', 'recovery_due_at')
    op.drop_column('user_card_directions', 'recovery_successes')
    op.drop_column('user_card_directions', 'recovery_required')
    op.drop_column('user_card_directions', 'difficulty_score')
