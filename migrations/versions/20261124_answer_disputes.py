"""Persist shared disputes for rejected course answers."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_answer_disputes"
down_revision = "20261124_placement_personal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_disputes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("question_revision", sa.String(64), nullable=False),
        sa.Column("grader_version", sa.Integer(), nullable=False),
        sa.Column("normalized_answer_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("review", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "lesson_id", "question_id", "question_revision", "grader_version", "normalized_answer_hash",
            name="uq_answer_dispute_identity",
        ),
    )
    op.create_index("ix_answer_disputes_status", "answer_disputes", ["status"])


def downgrade() -> None:
    op.drop_table("answer_disputes")
