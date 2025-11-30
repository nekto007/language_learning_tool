"""Make task.block_id nullable and update constraint

Revision ID: a1b2c3d4e5f6
Revises: d35366cf95ab
Create Date: 2025-11-30 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd35366cf95ab'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old unique constraint
    op.drop_constraint('uix_block_task_type', 'task', type_='unique')

    # Make block_id nullable
    op.alter_column('task', 'block_id',
                    existing_type=sa.Integer(),
                    nullable=True)

    # Create new unique constraint that allows NULL block_id
    # (block_id, task_type) should be unique only when block_id is not NULL
    op.create_index(
        'uix_block_task_type_partial',
        'task',
        ['block_id', 'task_type'],
        unique=True,
        postgresql_where=sa.text('block_id IS NOT NULL')
    )


def downgrade():
    # Drop the partial unique index
    op.drop_index('uix_block_task_type_partial', table_name='task')

    # Make block_id non-nullable again (will fail if there are NULL values)
    op.alter_column('task', 'block_id',
                    existing_type=sa.Integer(),
                    nullable=False)

    # Recreate the original unique constraint
    op.create_unique_constraint('uix_block_task_type', 'task', ['block_id', 'task_type'])
