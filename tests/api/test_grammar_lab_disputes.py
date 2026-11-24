"""Standalone Grammar Lab receipts authorize disputes without redoing practice."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from itsdangerous import URLSafeTimedSerializer
from werkzeug.test import TestResponse

from app.achievements.models import UserStatistics
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic, UserGrammarExercise
from app.utils.db import db
from tests.api.test_native_full_integration import learner
from tests.api.test_quiz_corrections import native_app


def browser(app: Flask, user: User) -> tuple[FlaskClient, dict[str, str]]:
    client = app.test_client()
    token = uuid4().hex
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
        session["_fresh"] = True
        session["csrf_token"] = token
    g.pop("_login_user", None)
    headers = {"X-CSRFToken": URLSafeTimedSerializer(app.secret_key, salt="wtf-csrf-token").dumps(token)}
    return client, headers


def exercise(kind: str, content: dict[str, Any]) -> GrammarExercise:
    topic = GrammarTopic(slug="lab-dispute-" + uuid4().hex, title="Dispute test",
                         title_ru="Тест спора", level="A1", content={})
    db.session.add(topic)
    db.session.flush()
    item = GrammarExercise(topic_id=topic.id, exercise_type=kind, content=content)
    db.session.add(item)
    db.session.commit()
    return item


def endpoint(item: GrammarExercise) -> str:
    return f"/grammar-lab/api/exercise/{item.id}"


def submit(
    client: FlaskClient, headers: dict[str, str], item: GrammarExercise, answer: object,
) -> dict[str, Any]:
    response = client.post(endpoint(item) + "/submit", headers=headers, json={"answer": answer})
    assert response.status_code == 200, response.json
    return response.json


def dispute(
    client: FlaskClient, headers: dict[str, str], item: GrammarExercise, token: str, answer: object,
) -> TestResponse:
    return client.post(endpoint(item) + "/dispute", headers=headers,
                       json={"dispute_token": token, "answer": answer})


def state(user: User, item: GrammarExercise) -> tuple[int, dict[str, Any], int | None]:
    srs = UserGrammarExercise.query.filter_by(user_id=user.id, exercise_id=item.id).one()
    stats = UserStatistics.query.filter_by(user_id=user.id).one_or_none()
    return (GrammarAttempt.query.filter_by(user_id=user.id, exercise_id=item.id).count(),
            deepcopy(srs.to_dict()), stats.total_xp if stats else None)


def test_rejection_receipt_is_bound_to_exact_answer_exercise_and_owner(native_app: Flask) -> None:  # noqa: F811
    from app.grammar_lab.dispute_receipts import read_rejection_receipt

    user, _ = learner(native_app)
    client, headers = browser(native_app, user)
    row = {"question": "I ___ here.", "instruction": "Fill the gap.", "correct_answer": "am"}
    item = exercise("fill_blank", row)
    other_item = exercise("fill_blank", row)
    assert "dispute_token" not in submit(client, headers, item, "am")
    assert "dispute_token" not in submit(client, headers, item, "   ")
    token = submit(client, headers, item, "is")["dispute_token"]
    original_state = state(user, item)
    claims = read_rejection_receipt(token, user.id, item.id)
    assert set(claims) == {"user", "exercise", "revision", "grader", "answer_digest"}
    assert dispute(client, {}, item, token, "is").status_code == 400
    assert dispute(client, headers, item, token + "tampered", "is").status_code == 409
    assert dispute(client, headers, item, token, "IS!").status_code == 400
    assert dispute(client, headers, other_item, token, "is").status_code == 403
    g.pop("_login_user", None)
    anonymous = native_app.test_client()
    with anonymous.session_transaction() as session:
        session["csrf_token"] = URLSafeTimedSerializer(native_app.secret_key, salt="wtf-csrf-token").loads(
            headers["X-CSRFToken"],
        )
    assert dispute(anonymous, headers, item, token, "is").status_code in (302, 401)
    assert AnswerDispute.query.filter_by(grammar_exercise_id=item.id).count() == 0
    g.pop("_login_user", None)
    response = dispute(client, headers, item, token, "is")
    assert response.json == {"success": True}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert dispute(client, headers, item, token, "is").json == response.json
    assert state(user, item) == original_state

    saved = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    assert saved.lesson_id is None
    assert saved.evidence == {"row": row, "answer": "is", "question": {
        "prompt": "I ___ here.", "instruction": "Fill the gap.",
    }}
    assert saved.status == "pending" and saved.review is None

    another, _ = learner(native_app)
    second, second_headers = browser(native_app, another)
    assert dispute(second, second_headers, item, token, "is").status_code == 403
    second_token = submit(second, second_headers, item, "IS!")["dispute_token"]
    assert dispute(second, second_headers, item, second_token, "IS!").json == {"success": True}
    assert AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one().evidence["answer"] == "is"


def test_typed_matching_rejection_keeps_original_json(native_app: Flask) -> None:  # noqa: F811
    user, _ = learner(native_app)
    client, headers = browser(native_app, user)
    item = exercise("matching", {"question": "Match the pairs.", "pairs": [
        {"left": "I", "right": "am"}, {"left": "You", "right": "are"},
    ]})
    wrong = {"0": "1", "1": "0"}
    token = submit(client, headers, item, wrong)["dispute_token"]
    assert dispute(client, headers, item, token, {"0": 1, "1": 0}).status_code == 400
    assert dispute(client, headers, item, token, wrong).json == {"success": True}
    same_wrong = [[1, 0], [0, 1]]
    second = submit(client, headers, item, same_wrong)["dispute_token"]
    assert dispute(client, headers, item, second, same_wrong).json == {"success": True}
    assert AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one().evidence["answer"] == wrong


def test_stale_expired_and_retired_receipts_cannot_be_queued(
    native_app: Flask, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    from app.grammar_lab import dispute_receipts

    user, _ = learner(native_app)
    client, headers = browser(native_app, user)
    row = {"question": "I ___ here.", "correct_answer": "am"}
    item = exercise("fill_blank", row)
    token = submit(client, headers, item, "is")["dispute_token"]
    with monkeypatch.context() as patched:
        patched.setattr(dispute_receipts, "_RECEIPT_SECONDS", -1)
        assert dispute(client, headers, item, token, "is").json["error"] == "dispute_receipt_invalid"
    item.content = {**row, "question": "I ___ a student."}
    db.session.commit()
    assert dispute(client, headers, item, token, "is").json["error"] == "lesson_changed"
    current_token = submit(client, headers, item, "is")["dispute_token"]
    item.content = {**row, "guided_retired": True}
    db.session.commit()
    assert dispute(client, headers, item, current_token, "is").status_code == 409
    assert AnswerDispute.query.filter_by(grammar_exercise_id=item.id).count() == 0


def test_content_override_changes_receipt_revision_and_evidence(native_app: Flask) -> None:  # noqa: F811
    from app.grammar_lab.answer_review import apply_lab_patch

    user, _ = learner(native_app)
    client, headers = browser(native_app, user)
    original = {"question": "I ___ here.", "correct_answer": "is"}
    item = exercise("fill_blank", original)
    old_token = submit(client, headers, item, "am")["dispute_token"]
    apply_lab_patch(item, {"correct_answer": "am"})
    db.session.commit()
    assert item.content == original
    assert dispute(client, headers, item, old_token, "am").json["error"] == "lesson_changed"
    assert "dispute_token" not in submit(client, headers, item, "am")
    token = submit(client, headers, item, "is")["dispute_token"]
    assert dispute(client, headers, item, token, "is").json == {"success": True}
    saved = AnswerDispute.query.filter_by(grammar_exercise_id=item.id).one()
    assert saved.evidence["row"]["correct_answer"] == "am"
    assert saved.evidence["answer"] == "is"
