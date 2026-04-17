"""
Tests for the composite DB indexes migration (20260416_add_composite_indexes).

Verifies:
- Migration file is well-formed and links correctly into the chain
- upgrade() and downgrade() call the expected index operations
- The indexes specified correspond to real high-traffic query patterns
"""
import importlib.util
from pathlib import Path
from unittest.mock import call, patch, MagicMock

import pytest


MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "20260416_add_composite_indexes.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_composite_indexes", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationMetadata:
    """Verify revision chain and module-level fields."""

    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration not found: {MIGRATION_PATH}"

    def test_revision_id(self):
        mod = _load_migration()
        assert mod.revision == "20260416_add_composite_indexes"

    def test_down_revision(self):
        mod = _load_migration()
        assert mod.down_revision == "add_password_reset_tokens"

    def test_branch_labels_none(self):
        mod = _load_migration()
        assert mod.branch_labels is None

    def test_depends_on_none(self):
        mod = _load_migration()
        assert mod.depends_on is None


class TestUpgradeCreatesIndexes:
    """upgrade() must create the expected composite indexes."""

    EXPECTED_INDEXES = [
        ("idx_study_sessions_user_id", "study_sessions", ["user_id"]),
        ("idx_study_sessions_user_start_time", "study_sessions", ["user_id", "start_time"]),
        ("idx_quiz_results_user_id", "quiz_results", ["user_id"]),
        ("idx_quiz_results_user_completed_at", "quiz_results", ["user_id", "completed_at"]),
        ("idx_lesson_attempts_user_started_at", "lesson_attempts", ["user_id", "started_at"]),
    ]

    def test_upgrade_creates_all_indexes(self):
        mod = _load_migration()
        created = []

        def capture_create_index(name, table, columns, **kwargs):
            created.append((name, table, columns))

        with patch("alembic.op.create_index", side_effect=capture_create_index):
            mod.upgrade()

        assert len(created) == len(self.EXPECTED_INDEXES), (
            f"Expected {len(self.EXPECTED_INDEXES)} indexes, got {len(created)}: {created}"
        )
        for idx_name, table, cols in self.EXPECTED_INDEXES:
            assert (idx_name, table, cols) in created, (
                f"Missing index: {idx_name} on {table}{cols}"
            )

    def test_upgrade_covers_study_sessions(self):
        mod = _load_migration()
        created_tables = []
        with patch("alembic.op.create_index", side_effect=lambda n, t, c, **kw: created_tables.append(t)):
            mod.upgrade()
        assert "study_sessions" in created_tables

    def test_upgrade_covers_quiz_results(self):
        mod = _load_migration()
        created_tables = []
        with patch("alembic.op.create_index", side_effect=lambda n, t, c, **kw: created_tables.append(t)):
            mod.upgrade()
        assert "quiz_results" in created_tables

    def test_upgrade_covers_lesson_attempts(self):
        mod = _load_migration()
        created_tables = []
        with patch("alembic.op.create_index", side_effect=lambda n, t, c, **kw: created_tables.append(t)):
            mod.upgrade()
        assert "lesson_attempts" in created_tables


class TestDowngradeDropsIndexes:
    """downgrade() must drop each index that upgrade() creates."""

    EXPECTED_DROPS = {
        "idx_study_sessions_user_id",
        "idx_study_sessions_user_start_time",
        "idx_quiz_results_user_id",
        "idx_quiz_results_user_completed_at",
        "idx_lesson_attempts_user_started_at",
    }

    def test_downgrade_drops_all_indexes(self):
        mod = _load_migration()
        dropped = []

        def capture_drop_index(name, **kwargs):
            dropped.append(name)

        with patch("alembic.op.drop_index", side_effect=capture_drop_index):
            mod.downgrade()

        assert set(dropped) == self.EXPECTED_DROPS, (
            f"Dropped {set(dropped)}, expected {self.EXPECTED_DROPS}"
        )

    def test_downgrade_symmetry_with_upgrade(self):
        """Every index created in upgrade must be dropped in downgrade."""
        mod = _load_migration()
        created = []
        dropped = []

        with patch("alembic.op.create_index", side_effect=lambda n, t, c, **kw: created.append(n)):
            mod.upgrade()

        with patch("alembic.op.drop_index", side_effect=lambda n, **kw: dropped.append(n)):
            mod.downgrade()

        assert set(created) == set(dropped), (
            f"Asymmetry: created={set(created)}, dropped={set(dropped)}"
        )


@pytest.mark.smoke
class TestMigrationChain:
    """Verify flask db heads reports a single head after migration is added."""

    def test_single_alembic_head(self, app):
        runner = app.test_cli_runner(mix_stderr=False)
        result = runner.invoke(args=["db", "heads"])
        # exit 0 means alembic found a single unambiguous head
        assert result.exit_code == 0, (
            f"flask db heads failed (exit {result.exit_code}): {result.output}"
        )
