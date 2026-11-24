"""Guest diagnostic ownership and personal follow-up preferences."""
from alembic import op
import sqlalchemy as sa

revision = '20261124_placement_personal'
down_revision = '20261124_placement_tests'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('placement_guests',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False))
    op.create_index('ix_placement_guests_expires_at', 'placement_guests', ['expires_at'])
    with op.batch_alter_table('placement_attempts') as batch:
        batch.alter_column('user_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('guest_key', sa.String(64), nullable=True))
        batch.create_foreign_key('fk_placement_attempt_guest', 'placement_guests', ['guest_key'], ['key'], ondelete='CASCADE')
        batch.create_check_constraint('ck_placement_attempt_owner', '(user_id IS NOT NULL) <> (guest_key IS NOT NULL)')
        batch.create_index('ix_placement_attempts_guest_key', ['guest_key'])
        batch.create_index('uq_placement_attempt_active_guest', ['guest_key'], unique=True,
                           postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))
    op.create_table('placement_preferences',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('dismissed_key', sa.String(100), nullable=True),
        sa.Column('dismissed_keys', sa.JSON(), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.Column('level_checkpoints', sa.JSON(), nullable=False))
    op.create_table('placement_reviews',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('placement_attempts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('topic_slug', sa.String(100), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('due_on', sa.Date(), nullable=False),
        sa.Column('completed_on', sa.Date(), nullable=True),
        sa.Column('practice', sa.JSON(), nullable=False),
        sa.UniqueConstraint('attempt_id', 'topic_slug', name='uq_placement_review_attempt_topic'))
    op.create_index('ix_placement_reviews_user_id', 'placement_reviews', ['user_id'])


def downgrade() -> None:
    op.drop_table('placement_reviews')
    op.drop_table('placement_preferences')
    # Anonymous attempts cannot be represented by the previous schema.
    op.execute("DELETE FROM placement_attempts WHERE user_id IS NULL")
    with op.batch_alter_table('placement_attempts') as batch:
        batch.drop_index('uq_placement_attempt_active_guest')
        batch.drop_index('ix_placement_attempts_guest_key')
        batch.drop_constraint('ck_placement_attempt_owner', type_='check')
        batch.drop_constraint('fk_placement_attempt_guest', type_='foreignkey')
        batch.drop_column('guest_key')
        batch.alter_column('user_id', existing_type=sa.Integer(), nullable=False)
    op.drop_table('placement_guests')
