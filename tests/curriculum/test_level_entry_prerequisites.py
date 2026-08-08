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
        # The score bar must stay switched off: check_prerequisites averages
        # LessonProgress.score across ungraded completions too, so any non-zero
        # min_score can permanently lock a 100%-completed module.
        assert 'MIN_SCORE = 0' in source
        assert "_MARKER = 'level_entry_gate'" in source


class TestMigrationSqlRuns:
    """The migration is plain SQL against the live schema — execute it for real."""

    def _module(self, db_session=None):
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / 'migrations' / 'versions' / '20260808_level_entry_prerequisites.py'
        )
        spec = importlib.util.spec_from_file_location('level_entry_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if db_session is not None:
            # `op.get_bind()` needs an Alembic context; the savepoint connection
            # the fixture already owns is the same thing the migration wants.
            connection = db_session.connection()
            module.op = type('_Op', (), {'get_bind': staticmethod(lambda: connection)})()
        return module

    def test_pairs_link_each_level_to_the_previous_one(self, db_session):
        migration = self._module()

        lower = _make_level(db_session, 901)
        upper = _make_level(db_session, 902)
        first_lower = _make_module(db_session, lower, 1)
        last_lower = _make_module(db_session, lower, 2)
        entry_upper = _make_module(db_session, upper, 1)
        _add_lessons(db_session, first_lower, 1)
        _add_lessons(db_session, last_lower, 1)
        _add_lessons(db_session, entry_upper, 1)

        pairs = dict(migration._level_entry_pairs(db_session.connection()))

        assert pairs[entry_upper.id] == last_lower.id

    def test_a_lessonless_trailing_module_is_never_the_gate(self, db_session):
        """A module with no lessons reports 0% forever — gating on it would lock
        the level permanently, and a locked level reads as an exhausted spine."""
        migration = self._module()

        lower = _make_level(db_session, 911)
        upper = _make_level(db_session, 912)
        with_lessons = _make_module(db_session, lower, 1)
        empty_trailing = _make_module(db_session, lower, 2)
        entry_upper = _make_module(db_session, upper, 1)
        _add_lessons(db_session, with_lessons, 1)
        _add_lessons(db_session, entry_upper, 1)

        pairs = dict(migration._level_entry_pairs(db_session.connection()))

        assert pairs[entry_upper.id] == with_lessons.id
        assert empty_trailing.id not in pairs.values()

    def test_upgrade_writes_the_gate_and_leaves_authored_rows_alone(self, db_session):
        migration = self._module(db_session)

        lower = _make_level(db_session, 921)
        upper = _make_level(db_session, 922)
        third = _make_level(db_session, 923)
        last_lower = _make_module(db_session, lower, 1)
        entry_upper = _make_module(db_session, upper, 1)
        authored = [{'type': 'module', 'id': last_lower.id, 'min_score': 65}]
        entry_third = _make_module(db_session, third, 1, prerequisites=authored)
        for module in (last_lower, entry_upper, entry_third):
            _add_lessons(db_session, module, 1)

        migration.upgrade()
        db_session.expire_all()

        written = db_session.get(Module, entry_upper.id).prerequisites
        assert written == [{
            'type': 'module',
            'id': last_lower.id,
            'min_score': migration.MIN_SCORE,
            'min_progress': migration.MIN_PROGRESS,
            'source': 'level_entry_gate',
        }]
        # Authored prerequisites win — the migration must not overwrite them.
        assert db_session.get(Module, entry_third.id).prerequisites == authored

    def test_upgrade_is_idempotent(self, db_session):
        migration = self._module(db_session)

        lower = _make_level(db_session, 931)
        upper = _make_level(db_session, 932)
        last_lower = _make_module(db_session, lower, 1)
        entry_upper = _make_module(db_session, upper, 1)
        _add_lessons(db_session, last_lower, 1)
        _add_lessons(db_session, entry_upper, 1)

        migration.upgrade()
        db_session.expire_all()
        first = db_session.get(Module, entry_upper.id).prerequisites
        migration.upgrade()
        db_session.expire_all()

        assert db_session.get(Module, entry_upper.id).prerequisites == first


class TestDowngradeStripsOnlyItsOwnRows:
    """``strip_marker_entries`` is what makes downgrade non-destructive."""

    def _strip(self):
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / 'migrations' / 'versions' / '20260808_level_entry_prerequisites.py'
        )
        spec = importlib.util.spec_from_file_location('level_entry_migration_dg', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.strip_marker_entries

    def test_marker_entry_is_removed(self):
        strip = self._strip()

        assert strip([{'type': 'module', 'id': 4, 'source': 'level_entry_gate'}]) is None

    def test_authored_entry_beside_a_marker_survives(self):
        strip = self._strip()
        authored = {'type': 'module', 'id': 9, 'min_score': 70}

        kept = strip([{'source': 'level_entry_gate', 'id': 4}, authored])

        assert kept == [authored]

    @pytest.mark.parametrize('untouched', [
        [{'type': 'module', 'id': 9}],   # marker matched other text, not a row of ours
        'not json at all',
        '{"type": "module"}',            # valid JSON, but not a list
    ])
    def test_rows_we_did_not_write_are_left_alone(self, untouched):
        strip = self._strip()

        assert strip(untouched) is False
