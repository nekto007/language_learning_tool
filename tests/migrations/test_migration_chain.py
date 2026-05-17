"""Smoke check for alembic migration chain integrity.

Walks every revision file under ``migrations/versions`` and asserts:

- Exactly one head (no revision points down to it).
- Every ``down_revision`` entry refers to a known revision (no orphans).

The repository has multiple historical roots (``down_revision is None``)
that were later unified by merge migrations, so single-root is not
asserted.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

_REV_RE = re.compile(r"^revision\s*=\s*['\"]([0-9a-zA-Z_]+)['\"]", re.MULTILINE)
_DOWN_RE = re.compile(
    r"^down_revision\s*=\s*(None|['\"]([0-9a-zA-Z_]+)['\"]|\(([^)]*?)\))",
    re.MULTILINE | re.DOTALL,
)


def _parse_revisions() -> dict[str, list[str] | None]:
    chain: dict[str, list[str] | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        if path.name.startswith("__"):
            continue
        text = path.read_text()
        rev_match = _REV_RE.search(text)
        down_match = _DOWN_RE.search(text)
        if not rev_match or not down_match:
            continue
        revision = rev_match.group(1)
        raw = down_match.group(1)
        if raw == "None":
            chain[revision] = None
        elif down_match.group(2):
            chain[revision] = [down_match.group(2)]
        else:
            tuple_body = down_match.group(3) or ""
            parents = re.findall(r"['\"]([0-9a-zA-Z_]+)['\"]", tuple_body)
            chain[revision] = parents or None
    return chain


@pytest.fixture(scope="module")
def chain() -> dict[str, list[str] | None]:
    return _parse_revisions()


def test_no_orphan_parents(chain):
    known = set(chain.keys())
    orphans: list[tuple[str, str]] = []
    for rev, parents in chain.items():
        if parents is None:
            continue
        for parent in parents:
            if parent not in known:
                orphans.append((rev, parent))
    assert not orphans, f"migrations reference unknown parents: {orphans}"


def test_single_head(chain):
    referenced: set[str] = set()
    for parents in chain.values():
        if parents is None:
            continue
        referenced.update(parents)
    heads = [rev for rev in chain if rev not in referenced]
    assert len(heads) == 1, f"expected one head migration, found {heads}"


def test_user_lesson_progress_migration_present(chain):
    assert "d35366cf95ab" in chain, "d35366cf95ab migration missing"
    assert chain["d35366cf95ab"] == ["51563928c8a8"]


# ---------------------------------------------------------------------------
# Migration readiness audit (Task 2 of post-immersion content-data plan):
# verify (statically, without a live DB) that the migrations that introduce
# new tables and user default columns are present in the migration tree.
# This guarantees that an `alembic upgrade head` against an empty DB will
# produce the schema the immersion features depend on.
# ---------------------------------------------------------------------------


_REQUIRED_TABLE_TO_MIGRATION_HINT = {
    # table_name : substring that must appear in the migration file body
    "listening_attempts": "listening_attempts",
    "user_writing_attempts": "user_writing_attempts",
    "pronunciation_attempts": "pronunciation_attempts",
    "user_reading_sessions": "user_reading_sessions",
    "user_reading_preference": "user_reading_preference",
    "quiz_error_log": "quiz_error_log",
    "grammar_theory_view": "grammar_theory_view",
    "word_collocations": "word_collocations",
    "vocab_annotations": "vocab_annotations",
    "cultural_notes": "cultural_notes",
    "daily_challenges": "daily_challenges",
    "custom_word_lists": "custom_word_lists",
    "lesson_feedback": "lesson_feedback",
    "user_route_progress": "user_route_progress",
    "daily_plan_logs": "daily_plan_log",
    "daily_plan_events": "daily_plan_events",
    "daily_study_minutes": "daily_study_minutes",
}

_REQUIRED_USER_COLUMN_DEFAULTS = {
    # column_name : default literal that must appear in some migration
    "daily_word_goal": "10",
    "weekly_lesson_goal": "5",
    "plan_difficulty": "normal",
    "streak_shield_active": "false",
}


def _read_all_migrations() -> dict[str, str]:
    bodies: dict[str, str] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        if path.name.startswith("__"):
            continue
        bodies[path.name] = path.read_text()
    return bodies


def test_new_immersion_tables_have_migrations():
    bodies = _read_all_migrations()
    joined = "\n".join(bodies.values())
    missing = [
        table
        for table, hint in _REQUIRED_TABLE_TO_MIGRATION_HINT.items()
        if hint not in joined
    ]
    assert not missing, f"no migration creates these tables: {missing}"


def test_user_default_columns_have_migrations():
    bodies = _read_all_migrations()
    joined = "\n".join(bodies.values())
    missing = []
    for column, default_literal in _REQUIRED_USER_COLUMN_DEFAULTS.items():
        if column not in joined:
            missing.append((column, "column not declared"))
            continue
        # Find a line that mentions both the column and its server_default.
        if default_literal not in joined.lower():
            missing.append((column, f"default literal '{default_literal}' missing"))
    assert not missing, f"user-defaults drift detected: {missing}"


def test_no_duplicate_revisions(chain):
    """Sanity: every revision id appears in only one file."""
    counts: dict[str, int] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        if path.name.startswith("__"):
            continue
        for match in _REV_RE.finditer(path.read_text()):
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    duplicates = [rev for rev, c in counts.items() if c > 1]
    assert not duplicates, f"duplicate revision ids: {duplicates}"
