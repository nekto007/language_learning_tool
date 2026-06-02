"""Feedback auto-context: lesson/book/course IDs, app version, client errors bag.

Adds a small set of structured pointers plus a JSON catch-all so bug reports
arrive with enough context that the operator doesn't have to ping the user
back asking "which lesson were you on?".

  - ``lesson_id`` — extracted from ``/learn/<id>/`` on submit
  - ``book_id``   — extracted from ``/read/<id>`` / ``/books/<id>``
  - ``app_version`` — git SHA or release tag stamped by deploy
  - ``context_json`` — bag for anything we can't normalize today
    (recent client JS errors, course_id, chapter_id, route endpoint,
    SPA state…)

Revision ID: 20260609_feedback_context
Revises: 20260608_feedback_triage
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa


revision = '20260609_feedback_context'
down_revision = '20260608_feedback_triage'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedback', sa.Column('lesson_id', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('book_id', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('app_version', sa.String(length=64), nullable=True))
    op.add_column('feedback', sa.Column('context_json', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('feedback', 'context_json')
    op.drop_column('feedback', 'app_version')
    op.drop_column('feedback', 'book_id')
    op.drop_column('feedback', 'lesson_id')
