"""Real PostgreSQL JSON/JSONB rollout regressions on guarded test fixtures only.

The database-name guard runs before resolving app/db_session, whose shared app
fixture creates/truncates test tables. SQLite skips this file. No credentials or
URLs are loaded here; the existing test environment supplies its isolated DB.
"""

from copy import deepcopy
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.auth.models import User
from app.cli.grammar_prompts import load_manifest, patch_prompts
from app.cli.grammar_recaps import load_manifests, patch_recaps
from app.cli.grammar_supplements import import_supplements, load_pack
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.grammar_lab.recap_manifest import _field
from app.utils.db import db

ROOT = Path(__file__).parents[2]


@pytest.fixture
def postgres_session(request):
    # Resolve existing fixture dependencies only after checking the DATABASE
    # NAME, not a substring that might occur in a username or query parameter.
    configured = make_url(os.environ.get("DATABASE_URL", "sqlite://"))
    if configured.get_backend_name() == "sqlite":
        pytest.skip("PostgreSQL-specific JSON/JSONB and row-lock regression")
    if configured.get_backend_name() != "postgresql" or "_test" not in (configured.database or ""):
        pytest.fail("Refusing rollout test outside an explicitly named PostgreSQL _test database")
    request.getfixturevalue("app")
    session = request.getfixturevalue("db_session")
    assert db.engine.dialect.name == "postgresql"
    assert "_test" in (db.engine.url.database or "")
    assert "_test" in session.execute(text("SELECT current_database()")).scalar_one()
    # This is the important deployed distinction: generic JSON cannot be
    # compared with = on PostgreSQL, while Grammar Lab uses actual JSONB.
    columns = {
        table: {column["name"]: column["type"] for column in inspect(db.engine).get_columns(table)}
        for table in ("lessons", "grammar_topics", "grammar_exercises")
    }
    assert str(columns["lessons"]["content"]).upper() == "JSON"
    assert str(columns["grammar_topics"]["content"]).upper() == "JSONB"
    assert str(columns["grammar_exercises"]["content"]).upper() == "JSONB"
    return session


def _user(session):
    name = "pg_rollout_" + uuid4().hex[:20]
    user = User(username=name, email=name + "@example.invalid", active=True)
    user.set_password("only-disposable-rollout-test-password")
    session.add(user)
    session.flush()
    return user


def _clear_exact_topics(session, slugs):
    # The fixture has already verified current_database() and _test. Clean only
    # these conventional test targets if another test left a committed fixture.
    GrammarTopic.query.filter(GrammarTopic.slug.in_(slugs)).delete(synchronize_session=False)
    session.commit()


def _set_before(content, path, value):
    """Construct the reviewed source fields without importing ignored JSON."""
    parent = content
    for index, key in enumerate(path[:-1]):
        child = [] if type(path[index + 1]) is int else {}
        if isinstance(parent, list):
            while len(parent) <= key:
                parent.append(None)
            if parent[key] is None:
                parent[key] = child
        elif key not in parent:
            parent[key] = child
        parent = parent[key]
    key = path[-1]
    if isinstance(parent, list):
        while len(parent) <= key:
            parent.append(None)
    parent[key] = deepcopy(value)


def test_postgres_recap_updates_json_lesson_and_jsonb_mirror_in_place(postgres_session):
    session = postgres_session
    simple = load_manifests([ROOT / "MOBILE_GRAMMAR_RECAPS_20261120.json"])
    advanced = load_manifests([ROOT / "MOBILE_GRAMMAR_RECAP_EXAMPLES_20261120.json"])
    entries = [
        next(entry for entry in simple if len(entry["changes"]) == 1),
        next(entry for entry in advanced if any(change["path"] == ["description"] for change in entry["changes"])),
    ]
    _clear_exact_topics(session, [f"{entry['level'].lower()}-{entry['module_order']}" for entry in entries])
    rows = []
    for entry in entries:
        level = CEFRLevel.query.filter_by(code=entry["level"]).first()
        if level is None:
            level = CEFRLevel(code=entry["level"], name="PostgreSQL rollout fixture")
            session.add(level)
            session.flush()
        module = Module.query.filter_by(level_id=level.id, number=entry["module_order"]).first()
        if module is None:
            module = Module(level_id=level.id, number=entry["module_order"], title="PostgreSQL rollout fixture")
            session.add(module)
            session.flush()
        # Keep the actual reviewed module+external_key; never rename a source
        # identity just to make a database fixture easier to import.
        for old in Lessons.query.filter_by(module_id=module.id, type="grammar").all():
            if (old.content or {}).get("external_key") == entry["lesson_external_key"]:
                session.delete(old)
        session.flush()
        content = {
            "external_key": entry["lesson_external_key"],
            "exercises": [{"id": "must-survive", "correct_answer": "unchanged"}],
        }
        for change in entry["changes"]:
            _set_before(content, change["path"], change["before"])
        number = max([lesson.number for lesson in Lessons.query.filter_by(module_id=module.id).all()] + [0]) + 1
        lesson = Lessons(
            module_id=module.id,
            number=number,
            order=number,
            title="PostgreSQL reviewed source fixture",
            type="grammar",
            content=deepcopy(content),
        )
        mirror_content = deepcopy(content)
        if "description" in mirror_content:
            # This is the actual legacy importer alias, not a relaxed lookup.
            mirror_content["introduction"] = mirror_content.pop("description")
        mirror = GrammarTopic(
            slug=f"{entry['level'].lower()}-{entry['module_order']}",
            level=entry["level"],
            title="PostgreSQL mirror",
            title_ru="Тест",
            content=mirror_content,
        )
        session.add_all([lesson, mirror])
        session.flush()
        rows.append((entry, lesson, mirror))
    user = _user(session)
    progress = LessonProgress(
        user_id=user.id,
        lesson_id=rows[0][1].id,
        status="completed",
        score=87,
        best_score=91,
        last_score=87,
        data={"retain": ["answers", 3]},
    )
    exercise = GrammarExercise(
        topic_id=rows[0][2].id,
        exercise_type="fill_blank",
        order=11,
        content={"question": "I ___ here.", "correct_answer": "am"},
    )
    session.add_all([progress, exercise])
    session.flush()
    srs = UserGrammarExercise(user_id=user.id, exercise_id=exercise.id)
    srs.state, srs.interval, srs.repetitions = "review", 19, 5
    session.add(srs)
    session.commit()
    identities = [(lesson.id, mirror.id, lesson.content_version) for _, lesson, mirror in rows]
    before = [deepcopy(lesson.content) for _, lesson, _ in rows]
    dry = patch_recaps(session, entries)
    assert len(dry.updates) == 4 and not dry.conflicts and not dry.unavailable
    assert [lesson.content for _, lesson, _ in rows] == before
    assert patch_recaps(session, entries, apply=True).applied
    replay = patch_recaps(session, entries, apply=True)
    assert len(replay.unchanged) == 4 and not replay.updates
    assert identities == [(lesson.id, mirror.id, lesson.content_version) for _, lesson, mirror in rows]
    for entry, lesson, mirror in rows:
        for change in entry["changes"]:
            parent, key = _field(lesson.content, change["path"])
            assert parent[key] == change["after"]
            path = ["introduction"] if change["path"] == ["description"] else change["path"]
            parent, key = _field(mirror.content, path)
            assert parent[key] == change["after"]
        assert lesson.content["exercises"] == [{"id": "must-survive", "correct_answer": "unchanged"}]
    session.refresh(progress)
    session.refresh(srs)
    assert (progress.status, progress.score, progress.best_score, progress.last_score, progress.data) == (
        "completed",
        87,
        91,
        87,
        {"retain": ["answers", 3]},
    )
    assert (srs.exercise_id, srs.state, srs.interval, srs.repetitions) == (exercise.id, "review", 19, 5)
    assert exercise.content["correct_answer"] == "am"


def test_postgres_prompts_patch_all_80_exact_existing_identities_and_preserve_srs(postgres_session):
    session = postgres_session
    pack = load_manifest(ROOT / "MOBILE_GRAMMAR_EXERCISE_PROMPTS_20261120.json")
    slugs = [f"{source['level'].lower()}-{source['module_order']}" for source in pack["sources"]]
    _clear_exact_topics(session, slugs)
    topics = {}
    for source, slug in zip(pack["sources"], slugs, strict=True):
        topic = GrammarTopic(
            slug=slug,
            level=source["level"],
            title="Exact imported practice",
            title_ru="Тест",
            content={"rule": "Retain theory"},
        )
        session.add(topic)
        session.flush()
        topics[source["path"]] = topic
    rows = []
    for change in pack["changes"]:
        row = GrammarExercise(
            topic_id=topics[change["source"]].id,
            exercise_type=change["exercise_type"],
            order=change["exercise_order"],
            difficulty=change["difficulty"],
            content={**deepcopy(change["content_before"]), "source": "json_import"},
        )
        session.add(row)
        rows.append(row)
    session.flush()
    user = _user(session)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=rows[0].id)
    progress.state, progress.interval, progress.repetitions = "review", 23, 7
    session.add(progress)
    session.commit()
    identities = [(row.id, row.topic_id, row.order, row.difficulty, row.content["correct_answer"]) for row in rows]
    assert len(patch_prompts(session, pack).updates) == 80
    assert len(patch_prompts(session, pack, apply=True).updates) == 80
    replay = patch_prompts(session, pack, apply=True)
    assert len(replay.unchanged) == 80 and not replay.updates
    assert identities == [
        (row.id, row.topic_id, row.order, row.difficulty, row.content["correct_answer"]) for row in rows
    ]
    assert all(
        row.content == {**change["content_after"], "source": "json_import"}
        for row, change in zip(rows, pack["changes"], strict=True)
    )
    session.refresh(progress)
    assert (progress.exercise_id, progress.state, progress.interval, progress.repetitions) == (
        rows[0].id,
        "review",
        23,
        7,
    )


def test_postgres_both_optional_packs_create_3_topics_60_exercises_idempotently(postgres_session):
    session = postgres_session
    packs = [
        load_pack(ROOT / name)
        for name in ("MOBILE_GRAMMAR_SUPPLEMENTS_20261120.json", "MOBILE_GRAMMAR_FUTURE_PERFECT_20261120.json")
    ]
    slugs = [topic["slug"] for pack in packs for topic in pack["topics"]]
    _clear_exact_topics(session, slugs)
    for pack in packs:
        dry = import_supplements(session, pack)
        assert dry.topics_to_create == len(pack["topics"])
        applied = import_supplements(session, pack, apply=True)
        assert applied.topics_to_create == len(pack["topics"])
        assert applied.exercises_to_create == 20 * len(pack["topics"])
    topics = GrammarTopic.query.filter(GrammarTopic.slug.in_(slugs)).all()
    rows = (
        GrammarExercise.query.filter(GrammarExercise.topic_id.in_([topic.id for topic in topics]))
        .order_by(GrammarExercise.id)
        .all()
    )
    assert len(topics) == 3 and len(rows) == 60
    ids = [row.id for row in rows]
    user = _user(session)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=ids[0])
    progress.state, progress.interval, progress.repetitions = "review", 17, 4
    session.add(progress)
    session.commit()
    for pack in packs:
        replay = import_supplements(session, pack, apply=True)
        assert replay.topics_to_create == replay.exercises_to_create == 0
        assert replay.topics_unchanged == len(pack["topics"])
        assert replay.exercises_unchanged == 20 * len(pack["topics"])
    assert ids == [
        row.id
        for row in GrammarExercise.query.filter(GrammarExercise.topic_id.in_([topic.id for topic in topics])).order_by(
            GrammarExercise.id
        )
    ]
    session.refresh(progress)
    assert (progress.exercise_id, progress.state, progress.interval, progress.repetitions) == (ids[0], "review", 17, 4)
