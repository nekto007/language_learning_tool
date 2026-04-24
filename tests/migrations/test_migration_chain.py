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
