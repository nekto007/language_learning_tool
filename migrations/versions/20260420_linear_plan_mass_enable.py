"""Enable the linear daily plan for all onboarded users (mass rollout).

Flips ``users.use_linear_plan`` to TRUE for every user that has finished
onboarding (``onboarding_completed = TRUE``). Idempotent: users already on the
linear plan are not touched, and users still in onboarding keep the legacy
mission/v2 plan until they complete it manually.

Revision ID: 20260420_linear_mass_enable
Revises: 20260420_add_linear_daily_plan
Create Date: 2026-04-20
"""
from alembic import op


revision = '20260420_linear_mass_enable'
down_revision = '20260420_add_linear_daily_plan'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE users
        SET use_linear_plan = TRUE
        WHERE onboarding_completed = TRUE
          AND use_linear_plan = FALSE
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE users
        SET use_linear_plan = FALSE
        WHERE use_linear_plan = TRUE
        """
    )
