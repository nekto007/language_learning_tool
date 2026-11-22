"""Track SMTP acceptance separately from recipient delivery.

Revision ID: 20261122_auth_mail_submission
Revises: 20261120_family_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = '20261122_auth_mail_submission'
down_revision = '20261120_family_accounts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mobile_auth_mail', sa.Column('message_id', sa.String(255), nullable=True))
    op.add_column('mobile_auth_mail', sa.Column('accepted_at', sa.DateTime(), nullable=True))
    op.add_column('mobile_auth_mail', sa.Column('last_error', sa.String(32), nullable=True))
    op.add_column('mobile_auth_mail', sa.Column('last_smtp_code', sa.Integer(), nullable=True))
    op.create_index('ix_mobile_auth_mail_due', 'mobile_auth_mail', ['status', 'available_at'])
    # Historical sent meant only SMTP handoff; no delivery timestamp is known.
    op.execute("UPDATE mobile_auth_mail SET status = 'accepted' WHERE status = 'sent'")


def downgrade():
    op.drop_index('ix_mobile_auth_mail_due', table_name='mobile_auth_mail')
    op.execute("UPDATE mobile_auth_mail SET status = 'sent' WHERE status = 'accepted'")
    op.execute("UPDATE mobile_auth_mail SET status = 'expired' WHERE status = 'failed'")
    for name in ('last_smtp_code', 'last_error', 'accepted_at', 'message_id'):
        op.drop_column('mobile_auth_mail', name)
