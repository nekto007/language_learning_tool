"""
CI test: verify the Alembic migration chain has exactly one head.

This test is intended to catch divergent heads early — before they reach
production.  It does not require a running database; it inspects the
migration script directory directly via the Alembic script environment.
"""
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


@pytest.mark.smoke
def test_single_alembic_head(app):
    """Migration script directory must have exactly one head revision."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected 1 Alembic head, found {len(heads)}: {heads}. "
        "Run `flask db merge heads -m merge_heads` to fix."
    )


def test_merge_migration_file_exists():
    """The merge-heads migration file must exist in migrations/versions/."""
    versions_dir = REPO_ROOT / "migrations" / "versions"
    merge_files = list(versions_dir.glob("*merge_heads*"))
    assert len(merge_files) >= 1, (
        "No merge_heads migration found in migrations/versions/. "
        "Run `flask db merge heads -m merge_heads` to create one."
    )


def test_merge_migration_has_two_parents():
    """The merge migration must reference both diverged heads as down_revision."""
    import importlib.util

    versions_dir = REPO_ROOT / "migrations" / "versions"
    merge_files = list(versions_dir.glob("*merge_heads*"))
    assert merge_files, "No merge_heads migration found."

    path = merge_files[0]
    spec = importlib.util.spec_from_file_location("merge_heads_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert isinstance(mod.down_revision, tuple), (
        f"Expected down_revision to be a tuple of parents, got: {mod.down_revision!r}"
    )
    assert len(mod.down_revision) == 2, (
        f"Expected 2 parents in merge migration, got {len(mod.down_revision)}"
    )
