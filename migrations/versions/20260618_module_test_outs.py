"""Add module_test_outs — попытки сдачи модуля экстерном.

Revision ID: 20260618_module_test_outs
Revises: 20260617_writing_grammar_check
Create Date: 2026-06-18

Имя таблицы намеренно module_test_outs (не module_skip_tests): в части
старых БД существует осиротевшая таблица module_skip_tests от прежней
схемы — коллизии имён избегаем.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260618_module_test_outs'
down_revision = '20260617_writing_grammar_check'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'module_test_outs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id', sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'module_id', sa.Integer(),
            sa.ForeignKey('modules.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'idx_module_test_outs_user_module',
        'module_test_outs',
        ['user_id', 'module_id', 'created_at'],
    )


def downgrade():
    op.drop_index('idx_module_test_outs_user_module', table_name='module_test_outs')
    op.drop_table('module_test_outs')
