"""SQL budgets for first-time topic and mixed Grammar Lab sessions."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from flask import Flask
from sqlalchemy import delete, event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.orm import Session

from app.auth.models import User
from app.grammar_lab.models import (
    GrammarExercise, GrammarTopic, UserGrammarExercise, compute_initial_ease_for_difficulty,
)
from app.grammar_lab.services.grammar_lab_service import GrammarLabService
from app.srs.constants import DEFAULT_EASE_FACTOR, CardState
from app.srs.service import unified_srs_service
from app.utils.db import db


def create_topics(session: Session, size: int, topic_count: int) -> tuple[list[int], list[tuple[int, int]]]:
    topics = [
        GrammarTopic(slug=f"practice-sql-{uuid4().hex}", title=f"Topic {index}",
                     title_ru=f"Тема {index}", level="A1")
        for index in range(topic_count)
    ]
    session.add_all(topics)
    session.flush()
    exercises = [
        GrammarExercise(
            topic_id=topics[index % topic_count].id,
            exercise_type="fill_blank",
            content={"question": "I ___ ready.", "correct_answer": "am"},
            difficulty=1 + index % 3,
            order=index,
        )
        for index in range(size)
    ]
    session.add_all(exercises)
    session.flush()
    return [topic.id for topic in topics], [(exercise.id, exercise.difficulty) for exercise in exercises]


@pytest.mark.parametrize("kind", ["topic", "mixed"])
@pytest.mark.parametrize("size", [12, 48])
def test_first_practice_sql_budget(db_session: Session, test_user: User, kind: str, size: int) -> None:
    topic_ids, exercises = create_topics(db_session, size, 1 if kind == "topic" else 4)
    user_id = test_user.id
    connection = db_session.connection()
    counts: Counter[str] = Counter()

    def record_sql(
        conn: Connection, cursor: object, statement: str, parameters: object,
        context: ExecutionContext, executemany: bool,
    ) -> None:
        counts[statement.split(maxsplit=1)[0].upper()] += 1

    event.listen(connection.engine, "before_cursor_execute", record_sql)
    try:
        lab = GrammarLabService()
        if kind == "topic":
            result = lab.start_topic_practice(topic_ids[0], user_id, max_exercises=12)
        else:
            result = lab.get_practice_session(user_id, topic_ids=topic_ids, count=12)
    finally:
        event.remove(connection.engine, "before_cursor_execute", record_sql)

    print(f"{kind} {size}: {sum(counts.values())} {dict(counts)}")
    assert sum(counts.values()) <= (16 if kind == "topic" else 6)
    assert result["total_exercises"] == 12
    assert len({row["id"] for row in result["exercises"]}) == 12
    assert all(row["srs_state"] == CardState.NEW.value for row in result["exercises"])
    rows = UserGrammarExercise.query.filter_by(user_id=user_id).all()
    assert {row.exercise_id for row in rows} == {exercise_id for exercise_id, _ in exercises}
    assert {row.exercise_id: row.ease_factor for row in rows} == {
        exercise_id: compute_initial_ease_for_difficulty(difficulty) for exercise_id, difficulty in exercises
    }


def test_mixed_excludes_future_and_new_but_preserves_due_priority_and_srs_values(
    db_session: Session, test_user: User,
) -> None:
    topic_ids, exercises = create_topics(db_session, 5, 2)
    ids = [exercise_id for exercise_id, _ in exercises]
    user_id = test_user.id
    now = datetime.now(UTC)
    seeded = unified_srs_service.get_or_create_grammar_exercise_progress(user_id, ids)
    for index, state in enumerate([CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING, CardState.REVIEW]):
        seeded[index].state = state.value
        seeded[index].interval = 5 + index
        seeded[index].lapses = 1 + index
        seeded[index].next_review = now + timedelta(days=1 if index == 3 else -1)
    db_session.flush()

    result = GrammarLabService().get_practice_session(user_id, topic_ids, include_new=False)
    assert result["stats"] == {"relearning_count": 1, "learning_count": 1, "review_count": 1, "new_count": 0}
    assert [row["id"] for row in result["exercises"]] == [ids[2], ids[1], ids[0]]
    assert [(row["srs_interval"], row["srs_lapses"]) for row in result["exercises"]] == [(7, 3), (6, 2), (5, 1)]
    assert all(row["topic_title"] for row in result["exercises"])


def test_topic_retains_review_state_and_resets_attempts_with_legacy_difficulty(
    db_session: Session, test_user: User,
) -> None:
    topic_ids, exercises = create_topics(db_session, 2, 1)
    ids = [exercise_id for exercise_id, _ in exercises]
    user_id = test_user.id
    exercise = db_session.get(GrammarExercise, ids[1])
    exercise.difficulty = None
    existing, = unified_srs_service.get_or_create_grammar_exercise_progress(user_id, ids[:1])
    existing.state = CardState.REVIEW.value
    existing.interval = 11
    existing.lapses = 3
    existing.session_attempts = 2
    existing.next_review = datetime.now(UTC) - timedelta(days=1)
    db_session.flush()

    result = GrammarLabService().start_topic_practice(topic_ids[0], user_id)
    assert [row["id"] for row in result["exercises"]] == ids
    first, second = result["exercises"]
    assert (first["srs_state"], first["srs_interval"], first["srs_lapses"]) == ("review", 11, 3)
    assert (second["srs_state"], second["srs_interval"], second["srs_lapses"]) == ("new", 0, 0)
    assert existing.session_attempts == 0
    new = UserGrammarExercise.query.filter_by(user_id=user_id, exercise_id=ids[1]).one()
    assert new.ease_factor == DEFAULT_EASE_FACTOR
    assert new.next_review and new.step_index == new.repetitions == 0


def test_postgresql_concurrent_batches_share_rows_in_requested_order(app: Flask) -> None:
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent batches require PostgreSQL")
    key = uuid4().hex
    user = User(username=f"grammar-srs-{key}", email=f"{key}@example.invalid", active=True)
    user.set_password(key)
    db.session.add(user)
    topic_ids, exercises = create_topics(db.session, 2, 1)
    user_id = user.id
    first, second = (exercise_id for exercise_id, _ in exercises)
    db.session.commit()
    engine = db.engine
    barrier = Barrier(2)

    def wait_for_competing_insert(
        conn: Connection, cursor: object, statement: str, parameters: object,
        context: ExecutionContext, executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO USER_GRAMMAR_EXERCISES "):
            barrier.wait(timeout=10)

    def create_progress(ids: list[int]) -> list[tuple[int, int]]:
        with app.app_context():
            rows = unified_srs_service.get_or_create_grammar_exercise_progress(user_id, ids)
            result = [(row.exercise_id, row.id) for row in rows]
            db.session.commit()
            return result

    event.listen(engine, "before_cursor_execute", wait_for_competing_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(create_progress, [first, second, first])
            right = pool.submit(create_progress, [second, first])
            left_result, right_result = left.result(timeout=20), right.result(timeout=20)
        assert [row[0] for row in left_result] == [first, second, first]
        assert right_result == [left_result[1], left_result[0]]
        assert left_result[0] == left_result[2]
        assert UserGrammarExercise.query.filter_by(user_id=user_id).count() == 2
    finally:
        event.remove(engine, "before_cursor_execute", wait_for_competing_insert)
        db.session.rollback()
        db.session.execute(delete(User).where(User.id == user_id))
        db.session.execute(delete(GrammarTopic).where(GrammarTopic.id == topic_ids[0]))
        db.session.commit()
