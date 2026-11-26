"""Store resumable, opt-in web practice rounds."""
from alembic import op
import sqlalchemy as sa


revision = '20261127_web_practice_rounds'
down_revision = '20261125_content_moderator'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'web_practice_rounds',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('lessons.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.String(64), nullable=False),
        sa.Column('progress_version', sa.String(64), nullable=False),
        sa.Column('web_course', sa.Boolean(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
    )
    op.create_index('ix_web_practice_round_resume', 'web_practice_rounds',
                    ['user_id', 'lesson_id', 'web_course', 'completed'])


def downgrade() -> None:
    op.drop_table('web_practice_rounds')
