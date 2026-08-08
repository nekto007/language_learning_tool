"""Regression tests for CNT-005 (cross-zone audit 2026-08-08).

``check_module_access`` makes the first module of every CEFR level
auto-accessible on purpose, and its own comment names the safeguard that makes
that safe: "higher-level ENTRY modules must carry Module.prerequisites". In the
data that safeguard did not exist, so a learner 56% through A1 M2 was offered
A2 M1 and could walk the whole A2 spine without touching A1 M3-M16.

The migration ``20260808_level_entry_prerequisites`` writes those prerequisites
at the same 80% bar the intra-level rule uses. ``min_progress`` is what makes
that bar expressible — without it a prerequisite always demands 100%.
"""
from __future__ import annotations

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code


def _make_level(db_session, order: int) -> CEFRLevel:
    level = CEFRLevel(
        code=unique_level_code(), name=f'L{order}', description='d', order=order,
    )
    db_session.add(level)
    db_session.flush()
    return level


def _make_module(db_session, level, number, *, prerequisites=None) -> Module:
    module = Module(
        level_id=level.id, number=number, title=f'M{number}', description='d',
        raw_content={'module': {'id': number}}, prerequisites=prerequisites,
    )
    db_session.add(module)
    db_session.flush()
    return module


def _add_lessons(db_session, module, count: int) -> list[Lessons]:
    lessons = []
    for n in range(1, count + 1):
        lesson = Lessons(
            module_id=module.id, number=n, title=f'L{n}', type='vocabulary', content={},
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.flush()
    return lessons


def _complete(db_session, user_id, lessons, score=90.0):
    for lesson in lessons:
        db_session.add(LessonProgress(
            user_id=user_id, lesson_id=lesson.id, status='completed', score=score,
        ))
    db_session.flush()


@pytest.fixture
def two_levels(db_session, test_user):
    lower = _make_level(db_session, 1)
    upper = _make_level(db_session, 2)

    lower_last = _make_module(db_session, lower, 1)
    lessons = _add_lessons(db_session, lower_last, 10)

    entry = _make_module(db_session, upper, 1, prerequisites=[{
        'type': 'module', 'id': lower_last.id, 'min_score': 70, 'min_progress': 80,
        'source': 'level_entry_gate',
    }])
    return lower_last, lessons, entry


class TestMinProgressBar:
    def test_blocked_below_the_bar(self, db_session, test_user, two_levels):
        _lower, lessons, entry = two_levels
        _complete(db_session, test_user.id, lessons[:5])  # 50%

        accessible, reasons = entry.check_prerequisites(test_user.id)

        assert accessible is False
        assert reasons

    def test_open_at_the_bar(self, db_session, test_user, two_levels):
        _lower, lessons, entry = two_levels
        _complete(db_session, test_user.id, lessons[:8])  # 80%

        accessible, reasons = entry.check_prerequisites(test_user.id)

        assert accessible is True, reasons

    def test_low_scores_still_block(self, db_session, test_user, two_levels):
        _lower, lessons, entry = two_levels
        _complete(db_session, test_user.id, lessons[:9], score=40.0)

        accessible, _reasons = entry.check_prerequisites(test_user.id)

        assert accessible is False

    def test_default_is_still_full_completion(self, db_session, test_user):
        """Prerequisites authored before this change must not loosen."""
        level = _make_level(db_session, 1)
        prereq = _make_module(db_session, level, 1)
        lessons = _add_lessons(db_session, prereq, 10)
        gated = _make_module(db_session, level, 2, prerequisites=[
            {'type': 'module', 'id': prereq.id, 'min_score': 70},
        ])
        _complete(db_session, test_user.id, lessons[:9])  # 90% — short of 100

        accessible, _reasons = gated.check_prerequisites(test_user.id)

        assert accessible is False


class TestPlacementIsUnaffected:
    def test_prereq_below_the_placement_floor_is_skipped(
        self, db_session, test_user, two_levels,
    ):
        _lower, _lessons, entry = two_levels

        accessible, _reasons = entry.check_prerequisites(
            test_user.id, min_level_order=2,
        )

        assert accessible is True


class TestMigrationShape:
    def test_migration_declares_the_expected_bars(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / 'migrations' / 'versions' / '20260808_level_entry_prerequisites.py'
        ).read_text(encoding='utf-8')

        assert 'MIN_PROGRESS = 80' in source
        assert 'MIN_SCORE = 70' in source
        assert "_MARKER = 'level_entry_gate'" in source
        # Authored prerequisites must survive both directions.
        assert 'if existing:' in source
        assert 'LIKE :marker' in source


class TestMigrationSqlRuns:
    """The migration is plain SQL against the live schema — execute it for real."""

    def _module(self):
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / 'migrations' / 'versions' / '20260808_level_entry_prerequisites.py'
        )
        spec = importlib.util.spec_from_file_location('level_entry_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_level_entry_pairs_query_executes(self, db_session):
        migration = self._module()

        pairs = list(migration._level_entry_pairs(db_session.connection()))

        assert isinstance(pairs, list)

    def test_pairs_link_each_level_to_the_previous_one(self, db_session):
        migration = self._module()

        lower = _make_level(db_session, 901)
        upper = _make_level(db_session, 902)
        _first_lower = _make_module(db_session, lower, 1)
        last_lower = _make_module(db_session, lower, 2)
        entry_upper = _make_module(db_session, upper, 1)

        pairs = dict(migration._level_entry_pairs(db_session.connection()))

        assert pairs[entry_upper.id] == last_lower.id

    def test_downgrade_statement_executes(self, db_session):
        import sqlalchemy as sa

        db_session.connection().execute(sa.text(
            "UPDATE modules SET prerequisites = NULL "
            "WHERE prerequisites::text LIKE :marker"
        ), {'marker': '%level_entry_gate%'})
