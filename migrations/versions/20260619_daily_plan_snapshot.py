"""Add daily_plan_log.plan_json — снапшот состава required-секции на день.

Revision ID: 20260619_daily_plan_snapshot
Revises: 20260618_module_test_outs
Create Date: 2026-06-12

План дня пересобирается на каждый запрос, из-за чего состав required мог
«плыть» в течение дня (смена deck-quiz/srs, исчезновение слотов, тающая
цель SRS). Снапшот фиксирует состав и порядок слотов при первой сборке
за локальный день; completion и счётчики остаются живыми.
"""

import sqlalchemy as sa
from alembic import op

revision = '20260619_daily_plan_snapshot'
down_revision = '20260618_module_test_outs'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('daily_plan_log', sa.Column('plan_json', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('daily_plan_log', 'plan_json')
