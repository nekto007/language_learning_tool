"""Add site_settings key-value table.

Revision ID: 20260525_add_site_settings
Revises: 20260524_use_unified_plan
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = '20260525_add_site_settings'
down_revision = '20260524_use_unified_plan'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'site_settings' not in inspector.get_table_names():
        op.create_table(
            'site_settings',
            sa.Column('key', sa.Text(), primary_key=True, nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.Column(
                'updated_at',
                sa.DateTime(),
                nullable=False,
                server_default=sa.text('NOW()'),
            ),
        )


def downgrade():
    op.drop_table('site_settings')
