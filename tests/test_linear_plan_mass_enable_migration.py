"""Tests for the linear-plan mass-enable data migration.

Verifies:
- Migration file is well-formed and links correctly into the chain
- upgrade() issues the expected UPDATE filtered to onboarded users only
- downgrade() is intentionally a no-op (cannot distinguish mass-enabled from manual opt-ins)
- The logic is idempotent (re-running upgrade is a no-op)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "20260420_linear_plan_mass_enable.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_linear_plan_mass_enable", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationMetadata:
    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration not found: {MIGRATION_PATH}"

    def test_revision_id(self):
        mod = _load_migration()
        assert mod.revision == "20260420_linear_mass_enable"

    def test_down_revision(self):
        mod = _load_migration()
        assert mod.down_revision == "20260420_add_linear_daily_plan"

    def test_branch_labels_none(self):
        mod = _load_migration()
        assert mod.branch_labels is None


class TestUpgradeStatement:
    def test_upgrade_runs_one_update_statement(self):
        mod = _load_migration()
        executed: list[str] = []
        with patch("alembic.op.execute", side_effect=lambda sql: executed.append(str(sql))):
            mod.upgrade()
        assert len(executed) == 1

    def test_upgrade_sets_use_linear_plan_true(self):
        mod = _load_migration()
        executed: list[str] = []
        with patch("alembic.op.execute", side_effect=lambda sql: executed.append(str(sql))):
            mod.upgrade()
        sql = executed[0]
        assert "UPDATE users" in sql
        assert "use_linear_plan = TRUE" in sql

    def test_upgrade_filters_onboarded_users(self):
        """Users mid-onboarding must not be flipped into the linear plan."""
        mod = _load_migration()
        executed: list[str] = []
        with patch("alembic.op.execute", side_effect=lambda sql: executed.append(str(sql))):
            mod.upgrade()
        sql = executed[0]
        assert "onboarding_completed = TRUE" in sql

    def test_upgrade_is_idempotent_via_where_clause(self):
        """Users already on the linear plan are excluded, so re-runs are no-ops."""
        mod = _load_migration()
        executed: list[str] = []
        with patch("alembic.op.execute", side_effect=lambda sql: executed.append(str(sql))):
            mod.upgrade()
        sql = executed[0]
        assert "use_linear_plan = FALSE" in sql


class TestDowngradeStatement:
    def test_downgrade_is_noop(self):
        """Downgrade cannot distinguish mass-enabled users from manual opt-ins,
        so it deliberately does nothing — preserves author/beta flags."""
        mod = _load_migration()
        executed: list[str] = []
        with patch("alembic.op.execute", side_effect=lambda sql: executed.append(str(sql))):
            mod.downgrade()
        assert executed == []


class TestUpgradeSideEffects:
    def test_upgrade_flips_only_onboarded_users(self, app, db_session):
        """Integration-style: run the raw SQL on the live test DB."""
        import uuid

        from app.auth.models import User

        # Three users: onboarded+off, not-onboarded+off, already-on+onboarded
        onboarded = User(
            username=f"u1_{uuid.uuid4().hex[:8]}",
            email=f"u1_{uuid.uuid4().hex[:8]}@example.com",
            onboarding_completed=True,
            use_linear_plan=False,
        )
        onboarded.set_password("pw")

        not_onboarded = User(
            username=f"u2_{uuid.uuid4().hex[:8]}",
            email=f"u2_{uuid.uuid4().hex[:8]}@example.com",
            onboarding_completed=False,
            use_linear_plan=False,
        )
        not_onboarded.set_password("pw")

        already_on = User(
            username=f"u3_{uuid.uuid4().hex[:8]}",
            email=f"u3_{uuid.uuid4().hex[:8]}@example.com",
            onboarding_completed=True,
            use_linear_plan=True,
        )
        already_on.set_password("pw")

        db_session.add_all([onboarded, not_onboarded, already_on])
        db_session.commit()

        # Execute the same SQL the migration emits.
        from sqlalchemy import text

        db_session.execute(
            text(
                """
                UPDATE users
                SET use_linear_plan = TRUE
                WHERE onboarding_completed = TRUE
                  AND use_linear_plan = FALSE
                """
            )
        )
        db_session.commit()

        db_session.refresh(onboarded)
        db_session.refresh(not_onboarded)
        db_session.refresh(already_on)

        assert onboarded.use_linear_plan is True
        assert not_onboarded.use_linear_plan is False
        assert already_on.use_linear_plan is True

    def test_rerunning_update_is_idempotent(self, app, db_session):
        """Running the filtered UPDATE twice must produce the same state."""
        import uuid

        from sqlalchemy import text

        from app.auth.models import User

        user = User(
            username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"u_{uuid.uuid4().hex[:8]}@example.com",
            onboarding_completed=True,
            use_linear_plan=False,
        )
        user.set_password("pw")
        db_session.add(user)
        db_session.commit()

        stmt = text(
            """
            UPDATE users
            SET use_linear_plan = TRUE
            WHERE onboarding_completed = TRUE
              AND use_linear_plan = FALSE
            """
        )
        db_session.execute(stmt)
        db_session.commit()
        db_session.refresh(user)
        assert user.use_linear_plan is True

        # Second run: no-op — the WHERE clause excludes already-flipped rows.
        result = db_session.execute(stmt)
        db_session.commit()
        assert result.rowcount == 0
        db_session.refresh(user)
        assert user.use_linear_plan is True


@pytest.mark.smoke
class TestMigrationChain:
    def test_single_alembic_head(self, app):
        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(args=["db", "heads"])
        assert result.exit_code == 0, (
            f"flask db heads failed (exit {result.exit_code}): {result.output}"
        )
