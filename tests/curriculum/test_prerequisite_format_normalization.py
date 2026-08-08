"""Regression tests for CNT-014 and CNT-019 (cross-zone audit 2026-08-08).

CNT-014 — two modules declared their prerequisites as level-relative slug
strings (``["module_10", "module_11"]``). ``Module.check_prerequisites`` keeps
only ``dict`` entries with ``type == 'module'``, so both lists reduced to empty
and returned "accessible": the catalogue's only two authored checkpoints were
silent no-ops. Migration ``20260808_normalize_module_prerequisites`` resolves
each slug to a ``modules.id`` inside the same level and rewrites it in the shape
the parser reads.

CNT-019 — 1728 ``antonyms`` rows and 180 ``synonyms`` rows held the literal
``["null"]``. The lesson UI hid it behind ``_clean_word_list``; every other
consumer saw a populated list, and the metadata-coverage figure was inflated.
Migration ``20260808_clear_null_literal_word_lists`` blanks them.

The migrations are plain SQL against the live schema, so the tests execute them
for real on the test database rather than asserting on their source text.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from tests.conftest import unique_level_code

VERSIONS = Path(__file__).resolve().parents[2] / 'migrations' / 'versions'


def _load(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prereq_migration():
    return _load('20260808_normalize_module_prerequisites.py', 'prereq_migration')


@pytest.fixture
def null_literal_migration():
    return _load('20260808_clear_null_literal_word_lists.py', 'null_literal_migration')


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


class TestSlugRegex:
    @pytest.mark.parametrize('slug,number', [
        ('module_1', 1), ('module_10', 10), ('Module_7', 7), ('module-3', 3),
    ])
    def test_recognised_forms(self, prereq_migration, slug, number):
        match = prereq_migration._SLUG_RE.match(slug)
        assert match and int(match.group(1)) == number

    @pytest.mark.parametrize('value', ['module', 'lesson_3', 'module_abc', ''])
    def test_rejected_forms(self, prereq_migration, value):
        assert prereq_migration._SLUG_RE.match(value) is None


class TestNormalizationOnLiveSchema:
    def test_slug_resolves_to_the_module_in_the_same_level(
        self, db_session, prereq_migration,
    ):
        level = _make_level(db_session, 911)
        target = _make_module(db_session, level, 10)
        gated = _make_module(db_session, level, 12, prerequisites=['module_10'])
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)

        entry = gated.prerequisites[0]
        assert entry['type'] == 'module'
        assert entry['id'] == target.id
        assert entry['legacy_slug'] == 'module_10'

    def test_a_normalized_prerequisite_actually_gates(
        self, db_session, test_user, prereq_migration,
    ):
        """The point of the migration: check_prerequisites must now say no."""
        level = _make_level(db_session, 912)
        target = _make_module(db_session, level, 10)
        for n in range(1, 11):
            db_session.add(Lessons(
                module_id=target.id, number=n, title=f'L{n}', type='vocabulary', content={},
            ))
        gated = _make_module(db_session, level, 12, prerequisites=['module_10'])
        db_session.flush()

        assert gated.check_prerequisites(test_user.id)[0] is True, 'slug form is a no-op'

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)

        accessible, reasons = gated.check_prerequisites(test_user.id)
        assert accessible is False and reasons

        lessons = Lessons.query.filter_by(module_id=target.id).all()
        for lesson in lessons[:9]:
            db_session.add(LessonProgress(
                user_id=test_user.id, lesson_id=lesson.id, status='completed', score=90.0,
            ))
        db_session.flush()
        assert gated.check_prerequisites(test_user.id)[0] is True

    def test_unresolvable_slug_is_kept_not_dropped(self, db_session, prereq_migration):
        level = _make_level(db_session, 913)
        gated = _make_module(db_session, level, 2, prerequisites=['module_99'])
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)

        assert gated.prerequisites == ['module_99']

    def test_slug_does_not_leak_across_levels(self, db_session, prereq_migration):
        other = _make_level(db_session, 914)
        _make_module(db_session, other, 10)
        level = _make_level(db_session, 915)
        gated = _make_module(db_session, level, 12, prerequisites=['module_10'])
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)

        assert gated.prerequisites == ['module_10'], 'must not match a sibling level'

    def test_dict_prerequisites_are_left_untouched(self, db_session, prereq_migration):
        level = _make_level(db_session, 916)
        target = _make_module(db_session, level, 1)
        authored = [{'type': 'module', 'id': target.id, 'min_score': 65}]
        gated = _make_module(db_session, level, 2, prerequisites=authored)
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)

        assert gated.prerequisites == authored

    def test_round_trip_restores_the_original_slugs(self, db_session, prereq_migration):
        level = _make_level(db_session, 917)
        _make_module(db_session, level, 1)
        _make_module(db_session, level, 2)
        gated = _make_module(db_session, level, 4, prerequisites=['module_1', 'module_2'])
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        prereq_migration.restore_slugs(db_session.connection())
        db_session.expire(gated)

        assert gated.prerequisites == ['module_1', 'module_2']

    def test_running_twice_changes_nothing(self, db_session, prereq_migration):
        level = _make_level(db_session, 918)
        _make_module(db_session, level, 1)
        gated = _make_module(db_session, level, 2, prerequisites=['module_1'])
        db_session.flush()

        prereq_migration.normalize_prerequisites(db_session.connection())
        db_session.expire(gated)
        first = list(gated.prerequisites)

        assert prereq_migration.normalize_prerequisites(db_session.connection()) == 0
        db_session.expire(gated)
        assert gated.prerequisites == first


class TestNullLiteralSweep:
    def _insert_word(self, db_session, english, synonyms, antonyms):
        row = db_session.connection().execute(sa.text(
            'INSERT INTO collection_words (english_word, russian_word, synonyms, antonyms) '
            'VALUES (:e, :r, :s, :a) RETURNING id'
        ), {'e': english, 'r': 'слово', 's': synonyms, 'a': antonyms}).scalar()
        return row

    def _read(self, db_session, word_id):
        return db_session.connection().execute(sa.text(
            'SELECT synonyms::text, antonyms::text FROM collection_words WHERE id = :id'
        ), {'id': word_id}).fetchone()

    def test_literal_null_is_blanked(self, db_session, null_literal_migration):
        word_id = self._insert_word(db_session, 'cnt019-a', '["null"]', '["null"]')

        null_literal_migration.clear_null_literals(db_session.connection())

        assert self._read(db_session, word_id) == (None, None)

    def test_real_values_survive(self, db_session, null_literal_migration):
        word_id = self._insert_word(db_session, 'cnt019-b', '["quiet"]', '["loud"]')

        null_literal_migration.clear_null_literals(db_session.connection())

        synonyms, antonyms = self._read(db_session, word_id)
        assert 'quiet' in synonyms and 'loud' in antonyms

    def test_a_list_that_merely_contains_null_survives(
        self, db_session, null_literal_migration,
    ):
        """Only the exact one-element literal is generator junk."""
        word_id = self._insert_word(db_session, 'cnt019-c', '["null", "void"]', None)

        null_literal_migration.clear_null_literals(db_session.connection())

        synonyms, _ = self._read(db_session, word_id)
        assert 'void' in synonyms

    def test_running_twice_touches_nothing_the_second_time(
        self, db_session, null_literal_migration,
    ):
        self._insert_word(db_session, 'cnt019-d', '["null"]', '["null"]')

        assert null_literal_migration.clear_null_literals(db_session.connection()) >= 2
        assert null_literal_migration.clear_null_literals(db_session.connection()) == 0
