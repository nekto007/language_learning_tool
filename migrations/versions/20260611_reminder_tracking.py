"""Add open/click tracking columns to reminder_logs.

Revision ID: 20260611_reminder_tracking
Revises: 20260610_book_rights_metadata
Create Date: 2026-06-11

- ``token`` opaque per-email ID baked into tracking URLs.
- ``opened_at`` / ``open_count`` updated on tracking-pixel hit.
- ``clicked_at`` / ``click_count`` updated on tracked-link redirect.

Existing rows get a generated token via UPDATE so the UNIQUE constraint holds.
"""

import secrets

from alembic import op
import sqlalchemy as sa


revision = '20260611_reminder_tracking'
down_revision = '20260610_book_rights_metadata'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reminder_logs', sa.Column('token', sa.String(32), nullable=True))
    op.add_column('reminder_logs', sa.Column('opened_at', sa.DateTime(), nullable=True))
    op.add_column('reminder_logs', sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('reminder_logs', sa.Column('clicked_at', sa.DateTime(), nullable=True))
    op.add_column('reminder_logs', sa.Column('click_count', sa.Integer(), nullable=False, server_default='0'))

    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id FROM reminder_logs WHERE token IS NULL')).fetchall()
    for row in rows:
        conn.execute(
            sa.text('UPDATE reminder_logs SET token = :token WHERE id = :id'),
            {'token': secrets.token_hex(16), 'id': row[0]},
        )

    op.alter_column('reminder_logs', 'token', nullable=False)
    op.create_unique_constraint('uq_reminder_logs_token', 'reminder_logs', ['token'])
    op.create_index('ix_reminder_logs_template_sent_at', 'reminder_logs', ['template', 'sent_at'])


def downgrade():
    op.drop_index('ix_reminder_logs_template_sent_at', table_name='reminder_logs')
    op.drop_constraint('uq_reminder_logs_token', 'reminder_logs', type_='unique')
    op.drop_column('reminder_logs', 'click_count')
    op.drop_column('reminder_logs', 'clicked_at')
    op.drop_column('reminder_logs', 'open_count')
    op.drop_column('reminder_logs', 'opened_at')
    op.drop_column('reminder_logs', 'token')
