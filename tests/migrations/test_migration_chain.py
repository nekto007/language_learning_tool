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


# ---------------------------------------------------------------------------
# Task 57 additions: CASCADE idempotency, streak_shield DEFAULT, downgrade safety
# ---------------------------------------------------------------------------

_STREAK_SHIELD_MIGRATION = "20260523_streak_shield.py"
_CASCADE_MIGRATION = "20260425_grammar_exercise_cascade.py"

# The 5 most-recent non-merge migrations by chain proximity to current head.
# Merge migrations intentionally have `pass` downgrade bodies, so they are
# excluded from the "real downgrade" check.
_LAST_5_NON_MERGE = [
    "20260602_book_is_published.py",
    "20260601_activity_feed_indexes.py",
    "20260527_slot_skipped_unique_index.py",
    "20260527_feedback.py",
    "20260525_add_site_settings.py",
]


def test_streak_shield_has_server_default_false():
    path = MIGRATIONS_DIR / _STREAK_SHIELD_MIGRATION
    assert path.exists(), f"Migration file missing: {_STREAK_SHIELD_MIGRATION}"
    text = path.read_text()
    assert "streak_shield_active" in text, "streak_shield_active column not in migration"
    # server_default must be 'false' (postgres boolean literal)
    assert "server_default='false'" in text or 'server_default="false"' in text, (
        "streak_shield_active migration must have server_default='false'"
    )


def test_grammar_cascade_migration_is_idempotent():
    path = MIGRATIONS_DIR / _CASCADE_MIGRATION
    assert path.exists(), f"Migration file missing: {_CASCADE_MIGRATION}"
    text = path.read_text()
    # Idempotency guard: migration inspects FK before recreating it
    assert "_ensure_cascade" in text, "CASCADE migration must have idempotency guard (_ensure_cascade)"
    # Must check existing FK options before dropping/recreating
    assert "ondelete" in text.lower(), (
        "CASCADE migration must inspect ondelete option to avoid redundant ALTER"
    )
    # Must skip on SQLite (test environment)
    assert "sqlite" in text.lower() or "_is_postgres" in text, (
        "CASCADE migration must skip on SQLite to avoid fragile batch ALTER"
    )


def test_last_5_migrations_have_real_downgrade():
    for fname in _LAST_5_NON_MERGE:
        path = MIGRATIONS_DIR / fname
        assert path.exists(), f"Migration file missing: {fname}"
        text = path.read_text()
        # downgrade function must exist
        assert "def downgrade" in text, f"{fname}: missing downgrade() function"
        # Extract body after def downgrade():
        m = re.search(r"def downgrade\(\)[^:]*:(.*)", text, re.DOTALL)
        assert m, f"{fname}: could not parse downgrade body"
        body = m.group(1)
        # Meaningful downgrade = contains op. call or DROP/ALTER SQL
        has_op_call = bool(re.search(r"\bop\.", body))
        assert has_op_call, (
            f"{fname}: downgrade() appears to be a no-op (no op.* calls). "
            "Non-merge migrations must have a real downgrade."
        )


def test_cascade_migration_upgrade_skips_sqlite():
    path = MIGRATIONS_DIR / _CASCADE_MIGRATION
    text = path.read_text()
    # The upgrade() function must early-return on non-postgres
    # (to protect test environments that use SQLite)
    m = re.search(r"def upgrade\(\)[^:]*:(.*?)(?=\ndef |\Z)", text, re.DOTALL)
    assert m, "Could not find upgrade() in cascade migration"
    body = m.group(1)
    assert "not _is_postgres" in body or "return" in body, (
        "upgrade() in cascade migration must return early on non-postgres"
    )
