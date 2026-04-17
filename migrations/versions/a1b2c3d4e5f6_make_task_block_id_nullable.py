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


def _table_exists(table_name):
    insp = sa.inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _constraint_exists(table_name, constraint_name):
    insp = sa.inspect(op.get_bind())
    return any(c.get('name') == constraint_name for c in insp.get_unique_constraints(table_name))


def _index_exists(table_name, index_name):
    insp = sa.inspect(op.get_bind())
    return any(index.get('name') == index_name for index in insp.get_indexes(table_name))


def _column_is_nullable(table_name, column_name):
    insp = sa.inspect(op.get_bind())
    for column in insp.get_columns(table_name):
        if column['name'] == column_name:
            return column.get('nullable', True)
    return True


def upgrade():
    if not _table_exists('task'):
        return

    # Drop the old unique constraint
    if _constraint_exists('task', 'uix_block_task_type'):
        op.drop_constraint('uix_block_task_type', 'task', type_='unique')

    # Make block_id nullable
    if not _column_is_nullable('task', 'block_id'):
        op.alter_column('task', 'block_id',
                        existing_type=sa.Integer(),
                        nullable=True)

    # Create new unique constraint that allows NULL block_id
    # (block_id, task_type) should be unique only when block_id is not NULL
    if not _index_exists('task', 'uix_block_task_type_partial'):
        op.create_index(
            'uix_block_task_type_partial',
            'task',
            ['block_id', 'task_type'],
            unique=True,
            postgresql_where=sa.text('block_id IS NOT NULL')
        )


def downgrade():
    if not _table_exists('task'):
        return

    # Drop the partial unique index
    if _index_exists('task', 'uix_block_task_type_partial'):
        op.drop_index('uix_block_task_type_partial', table_name='task')

    # Make block_id non-nullable again (will fail if there are NULL values)
    if _column_is_nullable('task', 'block_id'):
        op.alter_column('task', 'block_id',
                        existing_type=sa.Integer(),
                        nullable=False)

    # Recreate the original unique constraint
    if not _constraint_exists('task', 'uix_block_task_type'):
        op.create_unique_constraint('uix_block_task_type', 'task', ['block_id', 'task_type'])
