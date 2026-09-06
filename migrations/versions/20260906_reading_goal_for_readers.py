"""Turn the daily reading goal on for learners who already picked a book.

Lesson audit item 16: picking a book is the reading goal. Existing accounts
with a UserReadingPreference get the default 5-minute goal so reading stays
in their required section (item 14 had made it opt-in); anyone can switch it
back to «по желанию» on the study settings page.

Revision ID: 20260906_reading_goal_for_readers
Revises: 20260906_reading_goal_and_pace
Create Date: 2026-09-06
"""
from alembic import op


revision = '20260906_reading_goal_for_readers'
down_revision = '20260906_reading_goal_and_pace'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO study_settings (user_id, new_words_per_day, reviews_per_day,
                                    include_translations, include_examples, include_audio,
                                    show_hint_time, reading_minutes_per_day)
        SELECT p.user_id, 5, 20, true, true, true, 10, 5
        FROM user_reading_preference p
        WHERE NOT EXISTS (SELECT 1 FROM study_settings s WHERE s.user_id = p.user_id)
        """
    )
    op.execute(
        """
        UPDATE study_settings s SET reading_minutes_per_day = 5
        WHERE s.reading_minutes_per_day = 0
          AND EXISTS (SELECT 1 FROM user_reading_preference p WHERE p.user_id = s.user_id)
        """
    )


def downgrade():
    # Data-only: the goal is a preference the learner can change; nothing to undo safely.
    pass
