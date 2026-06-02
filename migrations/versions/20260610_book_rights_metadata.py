"""Add rights/licensing metadata to book table.

Revision ID: 20260610_book_rights_metadata
Revises: 20260609_feedback_context
Create Date: 2026-06-10

Adds rights tracking so the catalog can decide which books are accessible
to a user without the optional ``books`` module:

- ``public_domain`` books → accessible to every registered user
- ``licensed`` / ``companion_only`` → require the admin-granted ``books`` module

The default of ``companion_only`` is intentionally conservative: existing rows
keep the same behavior they had before this change (admin must grant the
``books`` module to expose them).
"""

from alembic import op
import sqlalchemy as sa


revision = '20260610_book_rights_metadata'
down_revision = '20260609_feedback_context'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'book',
        sa.Column(
            'rights_status', sa.String(length=20),
            nullable=False, server_default='companion_only',
        ),
    )
    op.add_column('book', sa.Column('source_url', sa.Text(), nullable=True))
    op.add_column('book', sa.Column('license_type', sa.String(length=100), nullable=True))
    op.add_column('book', sa.Column('permission_document', sa.Text(), nullable=True))
    op.add_column(
        'book',
        sa.Column(
            'allowed_text_percent', sa.Integer(),
            nullable=False, server_default='100',
        ),
    )
    op.add_column(
        'book',
        sa.Column(
            'audio_rights_status', sa.String(length=20),
            nullable=False, server_default='companion_only',
        ),
    )
    op.add_column(
        'book',
        sa.Column(
            'commercial_use_allowed', sa.Boolean(),
            nullable=False, server_default='false',
        ),
    )
    op.add_column(
        'book',
        sa.Column(
            'territory', sa.String(length=100),
            nullable=False, server_default='worldwide',
        ),
    )
    op.add_column('book', sa.Column('expiration_date', sa.Date(), nullable=True))

    op.create_check_constraint(
        'ck_book_rights_status',
        'book',
        "rights_status IN ('public_domain', 'licensed', 'companion_only')",
    )
    op.create_check_constraint(
        'ck_book_audio_rights_status',
        'book',
        "audio_rights_status IN ('public_domain', 'licensed', 'companion_only', 'none')",
    )
    op.create_check_constraint(
        'ck_book_allowed_text_percent',
        'book',
        'allowed_text_percent >= 0 AND allowed_text_percent <= 100',
    )

    op.create_index(
        'idx_book_rights_status',
        'book',
        ['rights_status'],
    )


def downgrade():
    op.drop_index('idx_book_rights_status', table_name='book')
    op.drop_constraint('ck_book_allowed_text_percent', 'book', type_='check')
    op.drop_constraint('ck_book_audio_rights_status', 'book', type_='check')
    op.drop_constraint('ck_book_rights_status', 'book', type_='check')
    op.drop_column('book', 'expiration_date')
    op.drop_column('book', 'territory')
    op.drop_column('book', 'commercial_use_allowed')
    op.drop_column('book', 'audio_rights_status')
    op.drop_column('book', 'allowed_text_percent')
    op.drop_column('book', 'permission_document')
    op.drop_column('book', 'license_type')
    op.drop_column('book', 'source_url')
    op.drop_column('book', 'rights_status')
