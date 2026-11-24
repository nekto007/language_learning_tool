"""Web transport and durable deduplication for answer disputes."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import os
import re
from threading import Barrier
from uuid import uuid4
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask, g
from flask.testing import FlaskClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute, current_dispute_row, record_rejected_answer
from app.curriculum.models import LessonAttempt, LessonProgress, Lessons
from app.utils.db import db
from tests.api.test_native_full_integration import learner
from tests.api.test_quiz_corrections import course, native_app


def browser(app: Flask, user: User, lesson: Lessons) -> tuple[FlaskClient, str, dict[str, str], str]:
    user.onboarding_completed = True
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
        session["_fresh"] = True
    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    page = client.get(f"/learn/{lesson.id}/")
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    endpoint = f"/curriculum/api/lesson/{lesson.id}/practice"
    doc = client.get(endpoint).json["lesson"]
    return client, endpoint, {"X-CSRFToken": csrf}, doc["session_token"]


def test_only_rejected_server_grade_can_create_a_dispute(course: tuple) -> None:  # noqa: F811
    user, _, lesson, _, awards = course
    client, endpoint, headers, token = browser(course[3].application, user, lesson)
    body = {"session_token": token, "question_id": "0", "answer": "She go to school."}
    assert client.post(endpoint + "/dispute", json=body).status_code == 400

    for invalid, code in [
        ({"answer": "She goes to school."}, "answer_not_rejected"),
        ({"answer": ""}, "invalid_input"),
        ({"question_id": "100"}, "invalid_input"),
        ({"correct": False}, "invalid_input"),
        ({"session_token": "made-up"}, "lesson_changed"),
    ]:
        response = client.post(endpoint + "/dispute", json=body | invalid, headers=headers)
        assert response.status_code == (409 if code == "lesson_changed" else 400)
        assert response.json["error"] == code
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 0

    checked = client.post(endpoint + "/check", json=body, headers=headers)
    assert checked.json["feedback"]["correct"] is False
    result = client.post(endpoint + "/dispute", json=body, headers=headers)
    assert result.status_code == 200
    assert result.json == {"success": True}
    assert result.headers["Cache-Control"] == "private, no-store"
    dispute = AnswerDispute.query.filter_by(lesson_id=lesson.id).one()
    assert dispute.status == "pending"
    assert dispute.review is None and dispute.next_attempt_at is None
    assert dispute.evidence == {
        "row": lesson.content["exercises"][0],
        "answer": body["answer"],
        "question": {"prompt": "Correct: She go to school.", "instruction": "Введи ответ"},
    }
    assert LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).count() == 0
    assert LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson.id).count() == 0
    assert awards == []


def test_identity_is_shared_and_changes_only_with_the_question_revision(course: tuple) -> None:  # noqa: F811
    user, _, lesson, client, _ = course
    app = client.application
    lesson.content = lesson.content | {"instruction": "Correct the sentence."}
    db.session.commit()
    first, endpoint, headers, token = browser(app, user, lesson)
    body = {"session_token": token, "question_id": "0", "answer": "She go to school."}
    assert first.post(endpoint + "/dispute", json=body, headers=headers).json == {"success": True}
    original = AnswerDispute.query.filter_by(lesson_id=lesson.id).one()
    original.status = "reviewed"
    original.review = {"decision": "keep"}
    db.session.commit()

    other, _ = learner(app)
    second, endpoint, other_headers, other_token = browser(app, other, lesson)
    assert second.post(endpoint + "/dispute", json=body, headers=other_headers).status_code == 403
    assert second.post(endpoint + "/dispute", json=body | {
        "session_token": other_token, "answer": " SHE   GO TO SCHOOL!",
    }, headers=other_headers).json == {"success": True}
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 1
    assert original.status == "reviewed" and original.review == {"decision": "keep"}
    assert original.evidence["answer"] == body["answer"]
    assert original.evidence["question"]["lesson_instruction"] == "Correct the sentence."
    assert current_dispute_row(original, lesson) is lesson.content["exercises"][0]

    old_row, neighbour = lesson.content["exercises"]
    lesson.content = lesson.content | {"exercises": [old_row, neighbour | {"explanation": "Other explanation."}]}
    db.session.commit()
    assert current_dispute_row(original, lesson) == old_row
    assert second.post(endpoint + "/dispute", json=body | {
        "session_token": other_token,
    }, headers=other_headers).status_code == 409
    new_token = second.get(endpoint).json["lesson"]["session_token"]
    assert second.post(endpoint + "/dispute", json=body | {
        "session_token": new_token,
    }, headers=other_headers).json == {"success": True}
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 1

    new_row = old_row | {"correct_answer": "She goes to school every day."}
    lesson.content = lesson.content | {"exercises": [new_row, neighbour]}
    db.session.commit()
    assert current_dispute_row(original, lesson) is None
    new_token = second.get(endpoint).json["lesson"]["session_token"]
    assert second.post(endpoint + "/dispute", json=body | {
        "session_token": new_token,
    }, headers=other_headers).json == {"success": True}
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 2


def test_quiz_choice_uses_real_option_id_and_plan_guard(course: tuple, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.api import native_lessons
    from app.curriculum import security

    user, _, lesson, client, _ = course
    lesson.type = "quiz"
    lesson.content = {"questions": [{"question": "They ___ ready.", "type": "multiple_choice",
                                     "options": ["is", "are"], "correct": 1}]}
    db.session.commit()
    client, endpoint, headers, token = browser(client.application, user, lesson)
    body = {"session_token": token, "question_id": "0", "answer": "0"}
    monkeypatch.setattr(security, "check_lesson_access", lambda *_: False)
    assert client.post(endpoint + "/dispute", json=body, headers=headers).status_code == 403
    monkeypatch.setattr(security, "check_lesson_access", lambda *_: True)
    with monkeypatch.context() as patch:
        def paused(_lesson_id: int) -> None:
            raise native_lessons.NativeLessonError("plan_paused", 403)
        patch.setattr(native_lessons, "_guard_plan", paused)
        assert client.post(endpoint + "/dispute", json=body, headers=headers).json["error"] == "plan_paused"
    assert client.post(endpoint + "/dispute", json=body | {"answer": "is"}, headers=headers).status_code == 400
    assert client.post(endpoint + "/dispute", json=body | {"answer": "1"}, headers=headers).json["error"] == "answer_not_rejected"
    assert client.post(endpoint + "/dispute", json=body, headers=headers).json == {"success": True}
    dispute = AnswerDispute.query.filter_by(lesson_id=lesson.id).one()
    assert dispute.evidence["answer"] == "0"
    assert dispute.evidence["row"]["options"][0] == "is"


def test_dispute_does_not_grade_final_answers(course: tuple, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.api import native_content

    user, _, lesson, client, _ = course
    lesson.type = "final_test"
    lesson.content = {"questions": [{"question": "They ___ ready.", "type": "multiple_choice",
                                     "options": ["is", "are"], "correct": 1}]}
    db.session.commit()
    client, endpoint, headers, token = browser(client.application, user, lesson)

    def unexpected_grade(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Final answers must not reach the dispute grader")

    monkeypatch.setattr(native_content, "check_course_answer", unexpected_grade)
    response = client.post(endpoint + "/dispute", headers=headers, json={
        "session_token": token, "question_id": "0", "answer": "0",
    })
    assert response.status_code == 404
    assert response.json == {"success": False, "error": "not_found"}
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 0


def test_postgresql_migration_and_concurrent_browsers() -> None:
    """Use a throwaway schema, leaving the configured test database untouched."""
    raw_url = os.getenv("LLT_DISPUTE_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set LLT_DISPUTE_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql" and "_test" in (url.database or "")
    assert url.host in (None, "localhost", "127.0.0.1")
    schema = "dispute_test_" + uuid4().hex
    admin = create_engine(url)
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    migration = import_module("migrations.versions.20261124_answer_disputes")
    try:
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE lessons (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO lessons (id) VALUES (1)"))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        lesson = SimpleNamespace(id=1, type="grammar", content={"exercises": [
            {"type": "transformation", "question": "She ___ ready.", "correct_answer": "is"},
        ]})
        question = {"id": "0", "prompt": "She ___ ready.", "input": "text"}
        barrier = Barrier(6)

        def record(answer: str) -> None:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                record_rejected_answer(session, lesson, question, answer)
                session.commit()

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(record, ["are", "ARE!"] * 3))
        with Session(engine) as session:
            dispute = session.scalars(select(AnswerDispute)).one()
            assert dispute.status == "pending" and dispute.review is None
            assert dispute.evidence["answer"] in ("are", "ARE!")
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            assert conn.execute(text("SELECT to_regclass('answer_disputes')")).scalar() is None
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()
