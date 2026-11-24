"""Standalone grammar submit receipts preserve results and exactly one set of effects."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import re
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy import create_engine, delete, event, text
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.test import TestResponse

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.grammar_lab.answer_review import lab_revision
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic, UserGrammarExercise, UserGrammarTopicStatus
from app.utils.db import db
from tests.api.test_grammar_lab_disputes import browser, endpoint, exercise


def submission(item: GrammarExercise, answer: object) -> dict[str, Any]:
    return {"answer": answer, "session_id": "grammar_test", "source": "topic_practice",
            "submission_id": str(uuid4()), "exercise_revision": lab_revision(item)}


def post(client: FlaskClient, headers: dict[str, str], item: GrammarExercise, payload: dict) -> TestResponse:
    g.pop("_login_user", None)
    try:
        return client.post(endpoint(item) + "/submit", headers=headers, json=payload)
    finally:
        g.pop("_login_user", None)


def effects(user_id: int, exercise_id: int, topic_id: int) -> tuple:
    progress = UserGrammarExercise.query.filter_by(user_id=user_id, exercise_id=exercise_id).one_or_none()
    topic = UserGrammarTopicStatus.query.filter_by(user_id=user_id, topic_id=topic_id).one_or_none()
    stats = UserStatistics.query.filter_by(user_id=user_id).one_or_none()
    return (
        GrammarAttempt.query.filter_by(user_id=user_id, exercise_id=exercise_id).count(),
        None if progress is None else {**progress.to_dict(), "session_attempts": progress.session_attempts},
        None if topic is None else topic.xp_earned,
        0 if stats is None else stats.total_xp,
        StreakEvent.query.filter_by(user_id=user_id).count(),
    )


def committed_user() -> User:
    slug = uuid4().hex
    user = User(username=slug, email=slug + "@example.invalid", active=True, onboarding_completed=True, timezone="UTC")
    user.set_password(slug)
    db.session.add(user)
    db.session.commit()
    return user


def remove_committed_attempt_fixture(user_id: int, topic_id: int) -> None:
    db.session.rollback()
    db.session.execute(delete(User).where(User.id == user_id))
    db.session.execute(delete(GrammarTopic).where(GrammarTopic.id == topic_id))
    db.session.commit()


@pytest.mark.parametrize("answer", ["am", "is"])
def test_identical_submit_replays_grade_and_keeps_srs_xp_once(
    app: Flask, db_session: Session, test_user: User, answer: str,
) -> None:
    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    client, headers = browser(app, test_user)
    payload = submission(item, answer)
    first = post(client, headers, item, payload)
    assert first.status_code == 200, first.json
    assert first.headers["Cache-Control"] == "private, no-store"
    assert first.json["is_correct"] is (answer == "am")
    baseline = effects(test_user.id, item.id, item.topic_id)
    assert baseline[0] == baseline[1]["session_attempts"] == 1
    assert baseline[2] == (10 if answer == "am" else 0)
    assert baseline[3] == 10
    retry = post(client, headers, item, payload)
    assert retry.status_code == 200, retry.json
    # Rejection tokens may be freshly signed on each valid replay.
    assert {k: v for k, v in first.json.items() if k != "dispute_token"} == {
        k: v for k, v in retry.json.items() if k != "dispute_token"
    }
    assert ("dispute_token" in retry.json) == (answer == "is")
    assert effects(test_user.id, item.id, item.topic_id) == baseline
    attempt = GrammarAttempt.query.filter_by(submission_id=payload["submission_id"]).one()
    assert attempt.user_answer == answer
    assert "user_answer" not in attempt.submission_receipt["response"]
    assert "dispute_token" not in attempt.submission_receipt["response"]


def test_request_identity_revision_and_original_replay(
    app: Flask, db_session: Session, test_user: User,
) -> None:
    row = {"question": "I ___ ready.", "correct_answer": "am"}
    item = exercise("fill_blank", row)
    other_item = exercise("fill_blank", row)
    client, headers = browser(app, test_user)
    payload = submission(item, "is")
    assert post(client, headers, item, {**payload, "submission_id": True}).json["code"] == "invalid_input"
    assert post(client, headers, item, {**payload, "exercise_revision": None}).json["code"] == "invalid_input"
    assert post(client, headers, item, payload).json["dispute_token"]
    original = effects(test_user.id, item.id, item.topic_id)
    for target, changed in [(item, {**payload, "answer": "IS!"}), (other_item, payload)]:
        conflict = post(client, headers, target, changed)
        assert conflict.status_code == 409
        assert conflict.json["code"] == "submission_mismatch"

    item.content = {**row, "correct_answer": "is"}
    db_session.commit()
    replay = post(client, headers, item, payload)
    assert replay.status_code == 200
    assert replay.json["is_correct"] is False and replay.json["correct_answer"] == "am"
    assert "dispute_token" not in replay.json
    assert effects(test_user.id, item.id, item.topic_id) == original
    stale = post(client, headers, item, {**payload, "submission_id": str(uuid4())})
    assert stale.status_code == 409 and stale.json["code"] == "lesson_changed"
    fresh = post(client, headers, item, submission(item, "is"))
    assert fresh.status_code == 200 and fresh.json["is_correct"] is True


def test_claim_and_all_side_effects_roll_back_when_finishing_fails(
    app: Flask, db_session: Session, test_user: User, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.grammar_lab.routes import grammar_service

    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    client, headers = browser(app, test_user)
    payload = submission(item, "am")
    original = effects(test_user.id, item.id, item.topic_id)
    finish = grammar_service.check_and_update_mastery

    def fail(*_args: object) -> None:
        assert effects(test_user.id, item.id, item.topic_id)[0] == 1
        raise RuntimeError("forced failure immediately before receipt")

    monkeypatch.setattr(grammar_service, "check_and_update_mastery", fail)
    failed = post(client, headers, item, payload)
    assert failed.status_code == 503 and failed.json["code"] == "grading_failed"
    assert effects(test_user.id, item.id, item.topic_id) == original
    assert GrammarAttempt.query.filter_by(submission_id=payload["submission_id"]).count() == 0
    monkeypatch.setattr(grammar_service, "check_and_update_mastery", finish)
    assert post(client, headers, item, payload).status_code == 200
    assert effects(test_user.id, item.id, item.topic_id)[0] == 1


def test_legacy_submissions_remain_independent(
    app: Flask, db_session: Session, test_user: User,
) -> None:
    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    client, headers = browser(app, test_user)
    for _ in range(2):
        reply = post(client, headers, item, {"answer": "am", "session_id": "legacy"})
        assert reply.status_code == 200 and reply.json["is_correct"]
    attempts = GrammarAttempt.query.filter_by(user_id=test_user.id, exercise_id=item.id).all()
    assert len(attempts) == 2
    assert all(row.submission_id is None and row.submission_receipt is None for row in attempts)


def test_typed_answer_replays_with_original_json_shape(
    app: Flask, db_session: Session, test_user: User,
) -> None:
    item = exercise("matching", {"pairs": [{"left": "I", "right": "am"}, {"left": "She", "right": "is"}]})
    client, headers = browser(app, test_user)
    payload = submission(item, {"0": "0", "1": "1"})
    first = post(client, headers, item, payload)
    second = post(client, headers, item, {**payload, "answer": {"1": "1", "0": "0"}})
    assert first.status_code == second.status_code == 200, (first.json, second.json)
    assert first.json == second.json
    assert first.json["user_answer"] == payload["answer"]
    assert effects(test_user.id, item.id, item.topic_id)[0] == 1


def test_web_topic_reload_and_tabs_keep_the_attempt_counter_for_their_own_session(
    app: Flask, db_session: Session, test_user: User,
) -> None:
    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    client, headers = browser(app, test_user)

    def open_topic() -> str:
        g.pop("_login_user", None)
        page = client.get(f"/grammar-lab/practice/topic/{item.topic_id}")
        g.pop("_login_user", None)
        assert page.status_code == 200, page.location
        return re.search(r'let sessionId = "([^"]+)";', page.text).group(1)

    first_tab = open_topic()
    first = {**submission(item, "is"), "session_id": first_tab}
    graded = post(client, headers, item, first)
    assert graded.status_code == 200 and graded.json["srs_update"]["session_attempts"] == 1
    snapshot = effects(test_user.id, item.id, item.topic_id)
    other_tab = open_topic()
    assert other_tab != first_tab
    assert effects(test_user.id, item.id, item.topic_id) == snapshot
    replay = post(client, headers, item, first)
    assert replay.json["srs_update"] == graded.json["srs_update"]
    assert effects(test_user.id, item.id, item.topic_id) == snapshot

    def grade_again(session: str, source: str = "topic_practice") -> int:
        response = post(client, headers, item, {**submission(item, "is"), "session_id": session, "source": source})
        assert response.status_code == 200, response.json
        return response.json["srs_update"]["session_attempts"]

    assert grade_again(first_tab) == 2
    assert grade_again(other_tab) == 1
    assert grade_again(first_tab) == 3
    assert grade_again("grammar_practice_mixed", source="srs_review") == 4
    assert effects(test_user.id, item.id, item.topic_id)[0] == 5


@pytest.mark.parametrize("case", ["same_key", "same_exercise", "same_topic"])
def test_two_postgresql_requests_serialize_without_losing_srs_or_topic_xp(app: Flask, case: str) -> None:
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Independent transactions require PostgreSQL")
    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    other = item
    if case == "same_topic":
        other = GrammarExercise(topic_id=item.topic_id, exercise_type="fill_blank",
                                content={"question": "I ___ here.", "correct_answer": "am"})
        db.session.add(other)
    user = committed_user()
    user_id, item_id, other_id, topic_id = user.id, item.id, other.id, item.topic_id
    payload = submission(item, "am")
    other_payload = payload if case == "same_key" else submission(other, "am")
    targets = [(endpoint(item) + "/submit", payload), (endpoint(other) + "/submit", other_payload)]
    engine = db.engine
    barrier = Barrier(2)

    def wait_for_claim(
        conn: Connection, cursor: object, statement: str, parameters: object,
        context: ExecutionContext, executemany: bool,
    ) -> None:
        if statement.startswith("INSERT INTO grammar_attempts") and "ON CONFLICT" in statement:
            barrier.wait(timeout=10)

    def send(url: str, body: dict) -> tuple[int, dict]:
        with app.app_context():
            active = db.session.get(User, user_id)
            client, headers = browser(app, active)
            reply = client.post(url, headers=headers, json=body)
            return reply.status_code, reply.json

    event.listen(engine, "before_cursor_execute", wait_for_claim)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(send, url, body) for url, body in targets]
            first, second = [result.result(timeout=20) for result in results]
        assert first[0] == second[0] == 200, (first, second)
        snapshot = effects(user_id, item_id, topic_id)
        if case == "same_key":
            assert first == second
            assert (snapshot[0], snapshot[1]["session_attempts"], snapshot[2], snapshot[3]) == (1, 1, 10, 10)
        elif case == "same_exercise":
            assert sorted(reply["srs_update"]["session_attempts"] for _, reply in (first, second)) == [1, 2]
            assert (snapshot[0], snapshot[1]["session_attempts"], snapshot[2], snapshot[3]) == (2, 2, 20, 10)
        else:
            assert (snapshot[0], snapshot[1]["session_attempts"], snapshot[2], snapshot[3]) == (1, 1, 20, 10)
            other_snapshot = effects(user_id, other_id, topic_id)
            assert (other_snapshot[0], other_snapshot[1]["session_attempts"]) == (1, 1)
    finally:
        event.remove(engine, "before_cursor_execute", wait_for_claim)
        remove_committed_attempt_fixture(user_id, topic_id)


def test_optional_global_xp_lock_failure_preserves_receipt_and_mandatory_effects(
    app: Flask, caplog: pytest.LogCaptureFixture,
) -> None:
    if db.engine.dialect.name != "postgresql":
        pytest.skip("The global XP timeout is PostgreSQL-specific")
    item = exercise("fill_blank", {"question": "I ___ ready.", "correct_answer": "am"})
    user = committed_user()
    user_id, item_id, topic_id = user.id, item.id, item.topic_id
    db.session.add(UserStatistics(user_id=user_id, total_xp=0))
    db.session.commit()
    client, headers = browser(app, user)
    payload = submission(item, "am")
    try:
        # A real competing PostgreSQL connection holds the same row as the
        # daily-plan poller. The timeout must roll back only the optional XP.
        with db.engine.begin() as locked:
            locked.execute(text("SELECT id FROM user_statistics WHERE user_id = :user_id FOR UPDATE"),
                           {"user_id": user_id}).scalar_one()
            first = post(client, headers, item, payload)
            assert first.status_code == 200 and first.json["is_correct"]
        assert "grammar_review slot XP skipped" in caplog.text
        retry = post(client, headers, item, payload)
        assert retry.status_code == 200 and retry.json == first.json
        snapshot = effects(user_id, item_id, topic_id)
        assert (snapshot[0], snapshot[1]["session_attempts"], snapshot[2], snapshot[3], snapshot[4]) == (1, 1, 10, 0, 0)
    finally:
        remove_committed_attempt_fixture(user_id, topic_id)


def test_postgresql_migration_accepts_legacy_rows_and_recovers_invalid_concurrent_index(app: Flask) -> None:
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent index DDL requires PostgreSQL")
    migration = import_module("migrations.versions.20261124_grammar_submit_receipts")
    schema = "grammar_submit_" + uuid4().hex[:12]
    engine = create_engine(db.engine.url, future=True)

    def migrate(connection: Connection, upgrade: bool) -> None:
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            (migration.upgrade if upgrade else migration.downgrade)()

    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE grammar_attempts (id serial PRIMARY KEY, user_id int NOT NULL)"))
            connection.execute(text("INSERT INTO grammar_attempts (user_id) VALUES (1), (1)"))
            connection.execute(text("ALTER TABLE grammar_attempts ADD COLUMN submission_id uuid"))
            key = str(uuid4())
            connection.execute(text("INSERT INTO grammar_attempts (user_id, submission_id) VALUES (1, :key), (1, :key)"),
                               {"key": key})
            connection.commit()
            with pytest.raises(IntegrityError):
                migrate(connection, True)
            connection.rollback()
            connection.execute(text("DELETE FROM grammar_attempts WHERE id = 4"))
            connection.commit()
            migrate(connection, True)
            connection.execute(text("INSERT INTO grammar_attempts (user_id) VALUES (1)"))
            connection.execute(text("INSERT INTO grammar_attempts (user_id, submission_id) VALUES (2, :key)"), {"key": key})
            connection.commit()
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO grammar_attempts (user_id, submission_id) VALUES (1, :key)"), {"key": key})
            connection.rollback()
            migrate(connection, False)
            assert connection.execute(text("SELECT count(*) FROM grammar_attempts")).scalar_one() == 5
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
