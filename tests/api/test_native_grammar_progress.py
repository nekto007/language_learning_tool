"""Per-account grammar coverage and explicit slide completion on disposable DB."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.native_grammar_progress import theory_revision
from app.auth.account_deletion import AccountDeletionRequest
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.grammar_lab.models import (
    GrammarAttempt,
    GrammarExercise,
    GrammarTopic,
    UserGrammarExercise,
    UserGrammarTopicStatus,
)
from app.study.models import NativeLearningRun, StudySession
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def topic(*, count=3, level="A1", theory=True):
    value = GrammarTopic(
        slug="slide-" + uuid4().hex,
        title="To be",
        title_ru="Глагол to be",
        level=level,
        content={"rule": "I am. You are."} if theory else {},
    )
    db.session.add(value)
    db.session.flush()
    rows = []
    for index in range(count):
        row = GrammarExercise(
            topic_id=value.id,
            exercise_type="fill_blank",
            order=index,
            content={"question": "I ___ here.", "correct_answer": "am"},
        )
        db.session.add(row)
        rows.append(row)
    db.session.commit()
    return value, rows


def material(app, headers, identifier):
    response = app.test_client().get(f"/api/native/grammar/topics/{identifier}", headers=headers)
    assert response.status_code == 200, response.json
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "Set-Cookie" not in response.headers
    return response.json["topic"]


def complete(app, headers, identifier, revision, **extra):
    return app.test_client().post(
        f"/api/native/grammar/topics/{identifier}/theory/complete",
        headers=headers,
        json={"theory_revision": revision, "completed": True, **extra},
    )


def study_rows(user):
    return [
        model.query.filter_by(user_id=user.id).count()
        for model in (UserGrammarTopicStatus, UserGrammarExercise, GrammarAttempt, NativeLearningRun, StudySession)
    ]


def test_gets_are_read_only_and_count_unique_actual_answers_per_account(native_app):
    user, headers = learner(native_app)
    other, other_headers = learner(native_app)
    value, exercises = topic()
    # Starting practice preallocates NEW rows: merely having one isn't progress.
    for exercise in exercises:
        db.session.add(UserGrammarExercise(user_id=user.id, exercise_id=exercise.id))
    db.session.commit()
    first = UserGrammarExercise.query.filter_by(user_id=user.id, exercise_id=exercises[0].id).one()
    first.correct_count, first.incorrect_count = 4, 2
    first.first_reviewed, first.last_reviewed = datetime.now(UTC), datetime.now(UTC)
    first.state, first.interval, first.session_attempts = "review", 15, 3
    second = UserGrammarExercise.query.filter_by(user_id=user.id, exercise_id=exercises[1].id).one()
    second.incorrect_count = 1
    third = UserGrammarExercise(user_id=other.id, exercise_id=exercises[2].id)
    third.correct_count = 10
    db.session.add(third)
    db.session.commit()
    before = study_rows(user)
    snapshot = (first.state, first.interval, first.session_attempts, first.next_review, first.correct_count)
    expected = {"theory_completed": False, "practiced_exercises": 2, "correct_exercises": 1, "total_exercises": 3}
    assert material(native_app, headers, value.id)["progress"] == expected
    response = native_app.test_client().get("/api/native/grammar/topics", headers=headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    assert next(item for item in response.json["topics"] if item["id"] == value.id)["progress"] == expected
    assert material(native_app, other_headers, value.id)["progress"] == {
        "theory_completed": False,
        "practiced_exercises": 1,
        "correct_exercises": 1,
        "total_exercises": 3,
    }
    assert study_rows(user) == before
    db.session.refresh(first)
    assert (first.state, first.interval, first.session_attempts, first.next_review, first.correct_count) == snapshot


def link_completed_course(user, value, *, complete=True):
    level = CEFRLevel(code="S" + uuid4().hex[:1].upper(), name="Slide test")
    # Reuse a unique ordinary test-only level code without changing topic identity.
    while CEFRLevel.query.filter_by(code=level.code).first():
        level.code = "S" + uuid4().hex[:1].upper()
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title="Slide test")
    db.session.add(module)
    db.session.flush()
    linked = Lessons(
        module_id=module.id,
        number=1,
        type="grammar",
        title="Linked rule",
        grammar_topic_id=value.id,
        content={"rule": "Preserve course rule"},
    )
    db.session.add(linked)
    db.session.flush()
    progress = LessonProgress(
        user_id=user.id, lesson_id=linked.id, status="completed" if complete else "in_progress", score=90
    )
    db.session.add(progress)
    db.session.commit()
    return progress


def test_existing_course_completion_is_visible_without_lazy_status_creation(native_app):
    user, headers = learner(native_app)
    value, _ = topic()
    course_progress = link_completed_course(user, value)
    before = study_rows(user)
    assert material(native_app, headers, value.id)["progress"]["theory_completed"] is True
    assert study_rows(user) == before and before[0] == 0
    assert UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=value.id).first() is None
    response = complete(native_app, headers, value.id, material(native_app, headers, value.id)["theory_revision"])
    assert response.status_code == 200 and response.json["xp_earned"] == 0
    status = UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=value.id).one()
    assert status.theory_completed and status.xp_earned == 0
    db.session.refresh(course_progress)
    assert course_progress.status == "completed" and course_progress.score == 90


def test_only_explicit_completion_marks_theory_and_awards_once_without_starting_practice(native_app):
    user, headers = learner(native_app)
    value, _ = topic()
    document = material(native_app, headers, value.id)
    assert document["progress"]["theory_completed"] is False
    before = study_rows(user)
    response = complete(native_app, headers, value.id, document["theory_revision"])
    assert response.status_code == 200, response.json
    assert response.json == {
        "success": True,
        "progress": {**document["progress"], "theory_completed": True},
        "xp_earned": 20,
    }
    assert response.headers["Cache-Control"] == "private, no-store" and "Set-Cookie" not in response.headers
    after = study_rows(user)
    assert after == [before[0] + 1, *before[1:]]
    status = UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=value.id).one()
    original_stamp = status.theory_completed_at
    assert status.status == "theory_completed" and status.xp_earned == 20 and original_stamp
    again = complete(native_app, headers, value.id, document["theory_revision"])
    assert again.status_code == 200 and again.json["xp_earned"] == 0
    db.session.refresh(status)
    assert status.xp_earned == 20 and status.theory_completed_at == original_stamp
    assert material(native_app, headers, value.id)["progress"]["theory_completed"] is True
    assert study_rows(user) == after


@pytest.mark.parametrize("status_name", ["practicing", "mastered"])
def test_completion_preserves_existing_practice_status_and_srs(native_app, status_name):
    user, headers = learner(native_app)
    value, exercises = topic()
    status = UserGrammarTopicStatus(
        user_id=user.id, topic_id=value.id, status=status_name, theory_completed=False, xp_earned=45
    )
    progress = UserGrammarExercise(user_id=user.id, exercise_id=exercises[0].id)
    progress.state, progress.interval, progress.session_attempts, progress.correct_count = "review", 34, 2, 4
    db.session.add_all([status, progress])
    db.session.commit()
    before = (
        progress.state,
        progress.interval,
        progress.session_attempts,
        progress.next_review,
        progress.correct_count,
    )
    document = material(native_app, headers, value.id)
    response = complete(native_app, headers, value.id, document["theory_revision"])
    assert response.status_code == 200 and response.json["xp_earned"] == 20
    db.session.refresh(status)
    db.session.refresh(progress)
    assert status.status == status_name and status.theory_completed and status.xp_earned == 65
    assert (
        progress.state,
        progress.interval,
        progress.session_attempts,
        progress.next_review,
        progress.correct_count,
    ) == before
    assert complete(native_app, headers, value.id, document["theory_revision"]).json["xp_earned"] == 0


def test_revisions_are_stable_and_stale_completion_does_not_write(native_app):
    user, headers = learner(native_app)
    value, _ = topic()
    document = material(native_app, headers, value.id)
    revision = document["theory_revision"]
    assert len(revision) == 64 and revision == material(native_app, headers, value.id)["theory_revision"]
    assert theory_revision([{"body": "Same", "title": "Rule"}]) == theory_revision([{"title": "Rule", "body": "Same"}])
    before = study_rows(user)
    value.content = {"rule": "A changed rule."}
    db.session.commit()
    response = complete(native_app, headers, value.id, revision)
    assert response.status_code == 409 and response.json["error"] == "lesson_changed"
    assert study_rows(user) == before
    assert material(native_app, headers, value.id)["theory_revision"] != revision


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"theory_revision": "a" * 64},
        {"theory_revision": "a" * 64, "completed": False},
        {"theory_revision": "a" * 64, "completed": 1},
        {"theory_revision": [], "completed": True},
        {"theory_revision": "bad", "completed": True},
        {"theory_revision": "g" * 64, "completed": True},
        {"theory_revision": "a" * 64, "completed": True, "user_id": 1},
    ],
)
def test_completion_rejects_nonexact_or_invalid_bodies_without_any_progress_write(native_app, body):
    user, headers = learner(native_app)
    value, _ = topic()
    before = study_rows(user)
    response = native_app.test_client().post(
        f"/api/native/grammar/topics/{value.id}/theory/complete", headers=headers, json=body
    )
    assert response.status_code == 400 and response.json["error"] == "invalid_input"
    assert study_rows(user) == before


def test_authentication_public_topic_gate_and_zero_exercise_rules(native_app):
    user, headers = learner(native_app)
    value, _ = topic(count=0)
    document = material(native_app, headers, value.id)
    assert document["progress"] == {
        "theory_completed": False,
        "practiced_exercises": 0,
        "correct_exercises": 0,
        "total_exercises": 0,
    }
    client = native_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"], session["_fresh"] = user.get_id(), True
    response = client.post(
        f"/api/native/grammar/topics/{value.id}/theory/complete",
        json={"completed": True, "theory_revision": document["theory_revision"]},
    )
    assert response.status_code == 401
    assert complete(native_app, headers, value.id, document["theory_revision"]).status_code == 200
    hidden, _ = topic(level="C2")
    assert complete(native_app, headers, hidden.id, document["theory_revision"]).status_code == 404
    assert complete(native_app, headers, 2147483647, document["theory_revision"]).status_code == 404
    no_rules, _ = topic(theory=False)
    no_material = material(native_app, headers, no_rules.id)
    assert no_material["theory"] == []
    assert complete(native_app, headers, no_rules.id, no_material["theory_revision"]).status_code == 422
    assert UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=no_rules.id).first() is None


def test_pending_deletion_blocks_theory_completion_and_catalogue(native_app):
    user, headers = learner(native_app)
    value, _ = topic()
    document = material(native_app, headers, value.id)
    now = datetime.now(UTC)
    db.session.add(
        AccountDeletionRequest(
            user_id=user.id,
            status="pending",
            requested_at=now,
            earliest_deletion_at=now + timedelta(days=7),
            latest_deletion_at=now + timedelta(days=14),
        )
    )
    db.session.commit()
    response = complete(native_app, headers, value.id, document["theory_revision"])
    assert response.status_code == 403 and response.json["error"] == "account_deletion_pending"
    assert native_app.test_client().get("/api/native/grammar/topics", headers=headers).status_code == 403
    assert UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=value.id).first() is None


def test_pending_deletion_is_rechecked_after_user_lock(native_app, monkeypatch):
    from app.auth import deletion_access

    user, headers = learner(native_app)
    value, _ = topic()
    document = material(native_app, headers, value.id)
    calls = []

    def concurrent_deletion(_user_id):
        calls.append(_user_id)
        return len(calls) > 1

    monkeypatch.setattr(deletion_access, "learning_suspended", concurrent_deletion)
    response = complete(native_app, headers, value.id, document["theory_revision"])
    assert response.status_code == 403 and response.json["error"] == "account_deletion_pending"
    assert len(calls) >= 2
    assert UserGrammarTopicStatus.query.filter_by(user_id=user.id, topic_id=value.id).first() is None


def test_progress_query_budget_does_not_grow_with_topic_count(native_app):
    _user, headers = learner(native_app)
    values = [topic(count=index)[0] for index in range(5)]
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if any(
            name in statement.lower() for name in ("grammar_topics", "grammar_exercises", "user_grammar_topic_status")
        ):
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        response = native_app.test_client().get("/api/native/grammar/topics", headers=headers)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(statements) == 3, statements
    assert all(
        "select" in statement.lower()
        and not any(word in statement.lower() for word in ("insert into", "update ", "delete from"))
        for statement in statements
    )
    selected = {item["id"]: item for item in response.json["topics"]}
    assert [selected[value.id]["progress"]["total_exercises"] for value in values] == list(range(5))


def test_other_account_completion_and_incomplete_course_do_not_complete_my_theory(native_app):
    owner, owner_headers = learner(native_app)
    other, other_headers = learner(native_app)
    value, exercises = topic(count=1)
    link_completed_course(owner, value, complete=False)
    link_completed_course(other, value)
    status = UserGrammarTopicStatus(
        user_id=other.id, topic_id=value.id, theory_completed=True, status="theory_completed", xp_earned=20
    )
    progress = UserGrammarExercise(user_id=owner.id, exercise_id=exercises[0].id)
    progress.last_reviewed = datetime.now(UTC)  # Legacy record with no attempt counters.
    db.session.add_all([status, progress])
    db.session.commit()
    assert material(native_app, owner_headers, value.id)["progress"] == {
        "theory_completed": False,
        "practiced_exercises": 1,
        "correct_exercises": 0,
        "total_exercises": 1,
    }
    assert material(native_app, other_headers, value.id)["progress"]["theory_completed"] is True
    assert UserGrammarTopicStatus.query.filter_by(user_id=owner.id, topic_id=value.id).first() is None


def test_revision_tracks_visible_material_and_projection_not_private_answers(native_app, monkeypatch):
    from app.api import native_grammar_progress

    _user, headers = learner(native_app)
    value, _ = topic()
    before = material(native_app, headers, value.id)["theory_revision"]
    value.content = {**value.content, "exercises": [{"correct_answer": "private-key"}], "audio": "metadata.mp3"}
    db.session.commit()
    assert material(native_app, headers, value.id)["theory_revision"] == before
    monkeypatch.setattr(
        native_grammar_progress, "NATIVE_PROJECTION_VERSION", native_grammar_progress.NATIVE_PROJECTION_VERSION + 1
    )
    assert material(native_app, headers, value.id)["theory_revision"] != before


def test_commit_failure_restores_existing_theory_status_and_reward(native_app, monkeypatch):
    from app.api.native_grammar_progress import complete_theory

    user, headers = learner(native_app)
    value, _ = topic()
    status = UserGrammarTopicStatus(
        user_id=user.id, topic_id=value.id, theory_completed=False, status="practicing", xp_earned=45
    )
    db.session.add(status)
    db.session.commit()
    revision = material(native_app, headers, value.id)["theory_revision"]

    def failed_commit():
        db.session.flush()
        raise RuntimeError("Injected completion commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(db.session, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="Injected"):
            complete_theory(user.id, value.id, revision)
    db.session.refresh(status)
    assert not status.theory_completed and status.theory_completed_at is None
    assert status.status == "practicing" and status.xp_earned == 45
