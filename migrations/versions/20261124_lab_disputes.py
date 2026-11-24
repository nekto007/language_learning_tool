"""Add an independent Grammar Lab source to answer disputes."""

from alembic import op
import sqlalchemy as sa

revision = "20261124_lab_disputes"
down_revision = "20261124_answer_disputes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grammar_exercises", sa.Column("answer_review_override", sa.JSON(), nullable=True))
    with op.batch_alter_table("answer_disputes") as batch:
        batch.add_column(sa.Column("grammar_exercise_id", sa.Integer(), nullable=True))
        batch.alter_column("lesson_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key(
            "fk_answer_dispute_lab_exercise", "grammar_exercises", ["grammar_exercise_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_answer_dispute_lab_identity", [
            "grammar_exercise_id", "question_revision", "grader_version", "normalized_answer_hash",
        ])
        batch.create_check_constraint(
            "ck_answer_dispute_source", "(lesson_id IS NULL) <> (grammar_exercise_id IS NULL)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    lab_disputes = connection.execute(sa.text(
        "SELECT 1 FROM answer_disputes WHERE grammar_exercise_id IS NOT NULL LIMIT 1",
    ))
    overrides = connection.execute(sa.text(
        "SELECT 1 FROM grammar_exercises WHERE answer_review_override IS NOT NULL LIMIT 1",
    ))
    if lab_disputes.scalar() is not None or overrides.scalar() is not None:
        raise RuntimeError("Archive Grammar Lab disputes and answer overrides before downgrading.")
    with op.batch_alter_table("answer_disputes") as batch:
        batch.drop_constraint("ck_answer_dispute_source", type_="check")
        batch.drop_constraint("uq_answer_dispute_lab_identity", type_="unique")
        batch.drop_constraint("fk_answer_dispute_lab_exercise", type_="foreignkey")
        batch.alter_column("lesson_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("grammar_exercise_id")
    op.drop_column("grammar_exercises", "answer_review_override")
