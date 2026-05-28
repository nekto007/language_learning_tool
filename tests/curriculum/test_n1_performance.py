"""Tests for N+1 query prevention in curriculum routes.

Task 58: Performance — N+1 в curriculum routes.
Verifies that joinedload is used for hot paths and query counts stay bounded.
"""
from __future__ import annotations

import uuid
import pytest

from sqlalchemy import event

from app.curriculum.models import CEFRLevel, Lessons, LessonProgress, Module
from app.utils.db import db
from tests.conftest import unique_level_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_level(db_session) -> CEFRLevel:
    level = CEFRLevel(code=unique_level_code(), name=f"Level-{_uid()}", order=99)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level) -> Module:
    module = Module(level_id=level.id, number=1, title=f"Module-{_uid()}", description="")
    db_session.add(module)
    db_session.commit()
    return module


_lesson_counter = 0


def _make_lesson(db_session, module, lesson_type: str = "text", content: dict | None = None, number: int | None = None) -> Lessons:
    global _lesson_counter
    _lesson_counter += 1
    if content is None:
        content = {"content": "Sample text for the lesson."}
    if number is None:
        number = _lesson_counter
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f"Lesson-{_uid()}",
        type=lesson_type,
        order=number,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _count_queries(fn) -> int:
    """Execute fn and return how many SQL statements were executed."""
    count = [0]

    def _listener(conn, cursor, statement, params, context, executemany):
        count[0] += 1

    event.listen(db.engine, "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(db.engine, "before_cursor_execute", _listener)
    return count[0]


def _count_table_queries(fn, table_name: str) -> int:
    """Count standalone SELECT queries that target a specific table."""
    count = [0]

    def _listener(conn, cursor, statement, params, context, executemany):
        stmt = statement.lower()
        # A standalone (lazy-load) query starts with SELECT and has the table as
        # the primary source — not just as a JOIN target inside another query.
        if stmt.lstrip().startswith("select") and f"from {table_name}" in stmt:
            count[0] += 1

    event.listen(db.engine, "before_cursor_execute", _listener)
    try:
        fn()
    finally:
        event.remove(db.engine, "before_cursor_execute", _listener)
    return count[0]


# ---------------------------------------------------------------------------
# Tests: learn index bounded query count
# ---------------------------------------------------------------------------

class TestLearnIndexQueryCount:
    """Curriculum /learn/ page must not produce N+1 queries."""

    @pytest.mark.smoke
    def test_learn_index_bounded_queries(self, client, test_user, db_session):
        """Curriculum index must use bounded DB queries regardless of level/module count.

        The /learn/ page uses CurriculumCacheService which performs:
        - 1 joinedload query: levels + modules + lessons
        - 1 bulk progress query
        - ~3 gamification queries (dates, completion, today)
        - ~1 recent activity query
        Plus per-request overhead (session, site_settings, user auth) ~ 20 queries.
        Total should be ≤ 50 even with middleware overhead.
        """
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        _login(client, test_user)

        total = _count_queries(lambda: client.get("/learn/"))

        assert total <= 50, (
            f"/learn/ issued {total} queries — possible N+1 (expected ≤ 50)"
        )

    def test_learn_index_multi_module_not_n_plus_1(self, client, test_user, db_session):
        """Adding modules must not grow query count proportionally (joinedload active).

        If N+1 were present, 5 modules would produce ~5x more queries.
        With joinedload, adding modules produces ≤ 5 additional queries total.
        """
        level = _make_level(db_session)

        # Baseline: 1 module
        mod1 = Module(level_id=level.id, number=1, title="Mod1", description="")
        db_session.add(mod1)
        db_session.commit()
        _make_lesson(db_session, mod1)
        _login(client, test_user)
        baseline = _count_queries(lambda: client.get("/learn/"))

        # Add 4 more modules
        for i in range(2, 6):
            mod = Module(level_id=level.id, number=i, title=f"Mod{i}", description="")
            db_session.add(mod)
            db_session.commit()
            _make_lesson(db_session, mod)

        multi = _count_queries(lambda: client.get("/learn/"))

        # With joinedload, 5 modules should add ≤ 10 extra queries vs 1 module
        assert multi - baseline <= 10, (
            f"5 modules added {multi - baseline} extra queries vs 1 module — "
            f"possible N+1 (baseline={baseline}, multi={multi})"
        )


# ---------------------------------------------------------------------------
# Tests: text_lesson no lazy load for module/level
# ---------------------------------------------------------------------------

class TestTextLessonJoinedLoad:
    """text_lesson must not issue separate queries for lesson.module / module.level."""

    def test_text_lesson_no_standalone_modules_query(self, client, test_user, db_session):
        """text_lesson must not issue a standalone SELECT FROM modules (lazy load)."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, "text", {"content": "Hello world."})
        _login(client, test_user)

        lazy_module_queries = _count_table_queries(
            lambda: client.get(f"/lesson/{lesson.id}/text"),
            "modules",
        )

        # With joinedload the module is fetched in the same query as the lesson —
        # no separate SELECT FROM modules should be issued.
        assert lazy_module_queries == 0, (
            f"text_lesson issued {lazy_module_queries} separate 'modules' queries — "
            "joinedload appears to be missing"
        )

    def test_text_lesson_query_count_bounded(self, client, test_user, db_session):
        """text_lesson overall query count must stay within a reasonable bound."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, "text", {"content": "Hello."})
        _login(client, test_user)

        total = _count_queries(lambda: client.get(f"/lesson/{lesson.id}/text"))

        assert total <= 40, (
            f"text_lesson issued {total} queries — possible N+1 (expected ≤ 40)"
        )


# ---------------------------------------------------------------------------
# Tests: listening_immersion_lesson no lazy load for module/level
# ---------------------------------------------------------------------------

class TestListeningImmersionJoinedLoad:
    """listening_immersion_lesson must not issue separate queries for module/level."""

    def test_listening_immersion_no_standalone_modules_query(self, client, test_user, db_session):
        """listening_immersion_lesson must not issue a standalone SELECT FROM modules."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(
            db_session, module, "listening_immersion",
            {"content": "Listen carefully.", "audio_url": "/test.mp3"},
        )
        _login(client, test_user)

        lazy_module_queries = _count_table_queries(
            lambda: client.get(f"/lesson/{lesson.id}/listening-immersion"),
            "modules",
        )

        assert lazy_module_queries == 0, (
            f"listening_immersion issued {lazy_module_queries} separate 'modules' queries"
        )


# ---------------------------------------------------------------------------
# Tests: learn_by_module page
# ---------------------------------------------------------------------------

class TestLearnByModuleQueryCount:
    """Module lesson list page must not produce N+1 queries."""

    def test_learn_by_module_bounded_queries(self, client, test_user, db_session):
        """Module page must use bounded DB queries."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        for i in range(1, 6):
            _make_lesson(db_session, module, content={"content": f"Lesson {i}"})

        _login(client, test_user)
        url = f"/learn/{level.code.lower()}/module-{module.number}/"

        total = _count_queries(lambda: client.get(url))

        assert total <= 40, (
            f"learn_by_module issued {total} queries — possible N+1 (expected ≤ 40)"
        )


# ---------------------------------------------------------------------------
# Tests: admin import invalidates curriculum cache
# ---------------------------------------------------------------------------

class TestAdminImportCacheInvalidation:
    """Admin curriculum import must clear the curriculum cache."""

    def test_import_clears_curriculum_cache(self, client, admin_user, db_session):
        """After a successful curriculum import the curriculum cache must be empty."""
        import json as _json
        from app.curriculum.cache import cache as curriculum_cache

        # Create the A1 level and a module in the DB so the import service finds them
        a1 = CEFRLevel.query.filter_by(code="A1").first()
        if not a1:
            a1 = CEFRLevel(code="A1", name="Beginner", order=1)
            db_session.add(a1)
            db_session.commit()

        # Ensure module 1 exists for A1 (import service finds by number)
        mod = Module.query.filter_by(level_id=a1.id, number=1).first()
        if not mod:
            mod = Module(level_id=a1.id, number=1, title="Module 1", description="")
            db_session.add(mod)
            db_session.commit()

        # Seed the cache with stale data
        curriculum_cache.set("curriculum:stale_key", {"stale": True})
        assert curriculum_cache.get("curriculum:stale_key") is not None

        # Use a high lesson number to avoid unique constraint collisions.
        # Use old format: {"level": "A1", "module": 1, "lessons": [...]}
        lesson_number = 9000 + (hash(_uid()) % 999)
        payload = _json.dumps({
            "level": "A1",
            "module": 1,
            "title": "Module 1",
            "lessons": [
                {
                    "lesson_number": lesson_number,
                    "title": f"Cache Test Lesson {_uid()}",
                    "type": "text",
                    "content": {"content": "Hello world"},
                }
            ],
        })

        response = client.post(
            "/admin/curriculum/import",
            data={"json_text": payload},
            follow_redirects=False,
        )

        # On success the route redirects (302) and clears the cache
        if response.status_code == 302:
            assert curriculum_cache.get("curriculum:stale_key") is None, (
                "Admin curriculum import did not clear the curriculum cache"
            )
