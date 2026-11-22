"""Retired grammar stays in history, never in a new queue or due hint."""

from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def material(native_app):
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.utils.db import db

    user, _ = learner(native_app)
    user.onboarding_completed = True
    topic = GrammarTopic(slug="retired-queues-" + uuid4().hex, title="Grammar", title_ru="Grammar",
                         level="A1", content={})
    db.session.add(topic)
    db.session.flush()
    rows = []
    for index, flag in enumerate((None, False, True)):
        content = {"question": f"I ___ here. ({index})", "correct_answer": "am"}
        if flag is not None:
            content["guided_retired"] = flag
        exercise = GrammarExercise(topic_id=topic.id, exercise_type="fill_blank", content=content,
                                   difficulty=1, order=index)
        db.session.add(exercise)
        rows.append(exercise)
    db.session.commit()
    return SimpleNamespace(user=user, topic=topic, legacy=rows[0], active=rows[1], retired=rows[2])


def cookie_client(app, user):
    from flask import g

    # The disposable fixture keeps one app context for the whole module;
    # requests must not reuse Flask-Login's cached user from another test.
    g.pop("_login_user", None)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
        session["_fresh"] = True
    return client


def test_web_exercise_list_keeps_legacy_and_explicit_active_but_hides_retired(native_app, material):
    client = cookie_client(native_app, material.user)
    response = client.get(f"/grammar-lab/api/topic/{material.topic.id}/exercises")
    assert response.status_code == 200
    assert [row["id"] for row in response.json] == [material.legacy.id, material.active.id]


def test_single_sibling_does_not_resurrect_retired_exercises(native_app, material):
    from app.daily_plan.linear.errors import get_sibling_exercise
    from app.utils.db import db

    error = SimpleNamespace(lesson=SimpleNamespace(grammar_topic_id=material.topic.id), question_payload={
        "exercise_id": material.legacy.id, "difficulty": 1, "question_type": "fill_blank"})
    selected = get_sibling_exercise(error, db)
    assert selected.id == material.active.id
    assert get_sibling_exercise(error, db, exclude_exercise_ids={material.active.id}) is None


def test_grouped_siblings_filter_retired_before_taking_limit(native_app, material):
    from app.daily_plan.linear.errors import get_topic_sibling_exercises
    from app.utils.db import db

    selected = get_topic_sibling_exercises(material.topic.id, set(), db, count=10)
    assert {row.id for row in selected} == {material.legacy.id, material.active.id}
    assert get_topic_sibling_exercises(material.topic.id, {material.legacy.id, material.active.id}, db) == []


def test_due_hint_ignores_retired_only_history_and_counts_only_active_due(native_app, material):
    from app.daily_plan.next_step import _check_grammar_weak
    from app.grammar_lab.models import UserGrammarExercise, UserGrammarTopicStatus
    from app.utils.db import db

    status = UserGrammarTopicStatus(user_id=material.user.id, topic_id=material.topic.id, status="practicing")
    old = UserGrammarExercise(material.user.id, material.retired.id)
    old.state = "review"
    old.next_review = datetime.now(UTC) - timedelta(days=1)
    db.session.add_all([status, old])
    db.session.commit()
    assert _check_grammar_weak(material.user.id, db) is None
    active = UserGrammarExercise(material.user.id, material.active.id)
    active.state = "review"
    active.next_review = datetime.now(UTC) - timedelta(days=1)
    db.session.add(active)
    db.session.commit()
    suggestion = _check_grammar_weak(material.user.id, db)
    assert suggestion.data["topic_id"] == material.topic.id
    assert suggestion.data["due_exercises"] == 1


def test_retired_srs_history_and_attempt_remain_readable(native_app, material):
    from app.grammar_lab.models import GrammarAttempt, UserGrammarExercise
    from app.utils.db import db

    old = UserGrammarExercise(material.user.id, material.retired.id)
    old.state = "review"
    old.interval = 24
    old.correct_count = 3
    attempt = GrammarAttempt(user_id=material.user.id, exercise_id=material.retired.id,
                             is_correct=True, user_answer="am", source="topic_practice")
    db.session.add_all([old, attempt])
    db.session.commit()
    client = cookie_client(native_app, material.user)
    response = client.get(f"/grammar-lab/api/exercise/{material.retired.id}/srs-info")
    assert response.status_code == 200 and response.json["interval"] == 24
    assert response.json["correct_count"] == 3
    assert GrammarAttempt.query.filter_by(user_id=material.user.id, exercise_id=material.retired.id).count() == 1


def test_retired_submit_is_rejected_before_grading_srs_or_attempt_writes(native_app, material, monkeypatch):
    from unittest.mock import Mock
    from app.grammar_lab.models import GrammarAttempt, UserGrammarExercise
    from app.grammar_lab.services.grammar_lab_service import GrammarLabService

    service = GrammarLabService()
    grade = Mock()
    monkeypatch.setattr(service.grader, "grade", grade)
    before = (GrammarAttempt.query.count(), UserGrammarExercise.query.count())
    result = service.submit_answer(material.retired.id, material.user.id, "am")
    assert result["status"] == 409 and result["code"] == "lesson_changed"
    grade.assert_not_called()
    monkeypatch.setitem(native_app.config, "WTF_CSRF_ENABLED", False)
    response = cookie_client(native_app, material.user).post(
        f"/grammar-lab/api/exercise/{material.retired.id}/submit", json={"answer": "am"})
    assert response.status_code == 409
    assert before == (GrammarAttempt.query.count(), UserGrammarExercise.query.count())


def lesson_for(material, *, guided_revision=None, kind="grammar"):
    from app.curriculum.models import CEFRLevel, Module, Lessons
    from app.utils.db import db

    level = CEFRLevel.query.filter_by(code="A1").first()
    if level is None:
        level = CEFRLevel(code="A1", name="A1")
        db.session.add(level)
        db.session.flush()
    module = Module(level_id=level.id, number=Module.query.count() + 1, title="Practice")
    db.session.add(module)
    db.session.flush()
    content = {"rule": "I + am"}
    if guided_revision:
        content["guided_catalog_digest"] = guided_revision
    lesson = Lessons(module_id=module.id, number=1, type=kind, title="Practice", content=content,
                     grammar_topic_id=material.topic.id if kind == "grammar" else None)
    db.session.add(lesson)
    db.session.commit()
    return lesson


def test_rollout_supersedes_positional_errors_without_deleting_or_resolving_history(native_app, material):
    from app.daily_plan.linear.errors import (log_quiz_error, count_unresolved, get_review_pool,
                                              _unresolved_question_indices)
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db

    lesson = lesson_for(material)
    old = log_quiz_error(material.user.id, lesson.id, {"question_index": 0, "question_text": "Old question"}, db)
    db.session.commit()
    assert count_unresolved(material.user.id, db) == 1
    assert _unresolved_question_indices(material.user.id, lesson.id, db) == {0}
    lesson.content = {"guided_catalog_digest": "a" * 64}
    db.session.commit()
    assert count_unresolved(material.user.id, db) == 0
    assert get_review_pool(material.user.id, db) == []
    assert _unresolved_question_indices(material.user.id, lesson.id, db) == set()
    assert db.session.get(QuizErrorLog, old.id).resolved_at is None
    assert QuizErrorLog.query.filter_by(user_id=material.user.id).count() == 1


def test_new_guided_error_has_revision_dedups_and_next_revision_can_log_same_index(native_app, material):
    from app.daily_plan.linear.errors import (log_quiz_error, log_quiz_errors_from_result,
                                              count_unresolved, get_review_pool, _unresolved_question_indices)
    from app.daily_plan.linear.models import QuizErrorLog
    from app.utils.db import db

    first, second = "a" * 64, "b" * 64
    lesson = lesson_for(material, guided_revision=first)
    log_quiz_error(material.user.id, lesson.id, {"question_index": 0, "question_text": "Superseded"}, db)
    question = {"type": "fill_blank", "question": "I ___ here.", "correct_answer": "am",
                "guided_revision": first, "guided_key": "be:first"}
    result = {"feedback": {"0": {"status": "incorrect", "user_answer": "are", "correct_answer": "am"}}}
    created = log_quiz_errors_from_result(material.user.id, lesson.id, [question], result, db, source="grammar")
    assert len(created) == 1
    assert created[0].question_payload["guided_revision"] == first
    assert created[0].question_payload["guided_key"] == "be:first"
    assert log_quiz_errors_from_result(material.user.id, lesson.id, [question], result, db, source="grammar") == []
    db.session.commit()
    assert count_unresolved(material.user.id, db) == 1
    assert [e.id for e in get_review_pool(material.user.id, db)] == [created[0].id]
    lesson.content = {"guided_catalog_digest": second}
    db.session.commit()
    assert count_unresolved(material.user.id, db) == 0
    assert _unresolved_question_indices(material.user.id, lesson.id, db) == set()
    replacement = {**question, "question": "She ___ here.", "correct_answer": "is",
                   "guided_revision": second, "guided_key": "be:second"}
    newer = log_quiz_errors_from_result(material.user.id, lesson.id, [replacement], result, db, source="grammar")
    db.session.commit()
    assert len(newer) == 1 and count_unresolved(material.user.id, db) == 1
    history = QuizErrorLog.query.filter_by(user_id=material.user.id).all()
    assert len(history) == 3 and all(e.resolved_at is None for e in history)


def test_nonguided_quiz_errors_still_count_and_dedup_independently(native_app, material):
    from app.daily_plan.linear.errors import log_quiz_error, log_quiz_errors_from_result, count_unresolved, get_review_pool
    from app.utils.db import db

    guided = lesson_for(material, guided_revision="a" * 64)
    quiz = lesson_for(material, kind="quiz")
    log_quiz_error(material.user.id, guided.id, {"question_index": 0}, db)
    question = {"type": "multiple_choice", "question": "Question", "options": ["A", "B"], "correct_answer": "A"}
    result = {"feedback": {"0": {"status": "incorrect", "user_answer": "B", "correct_answer": "A"}}}
    created = log_quiz_errors_from_result(material.user.id, quiz.id, [question], result, db)
    assert len(created) == 1
    assert log_quiz_errors_from_result(material.user.id, quiz.id, [question], result, db) == []
    db.session.commit()
    assert count_unresolved(material.user.id, db) == 1
    assert [e.id for e in get_review_pool(material.user.id, db)] == [created[0].id]
