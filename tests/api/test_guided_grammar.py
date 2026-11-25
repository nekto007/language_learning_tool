"""Pilot, immediate feedback and final-test separation on disposable data."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.grammar_lab.content_pilot import plurals_content
from app.grammar_lab.guided_learning import learning_steps, check_answer
from tests.api.test_native_lessons import native_context as _native_context, fetch, submit
from tests.api.test_native_grammar_mobile import native_app as _native_app


@pytest.fixture
def native_context(monkeypatch):
    return _native_context.__wrapped__(monkeypatch)


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def test_pilot_all_answers_work_in_course_and_lab_graders():
    from app.api.native_content import _question

    content = plurals_content()
    rows = content["exercises"]
    steps = learning_steps(content, len(rows))
    assert len(steps) == 8 and len(rows) == 24
    proxy = SimpleNamespace(id=42, type="grammar", content=content,
                            module=SimpleNamespace(level=SimpleNamespace(code="A1")))
    for i, row in enumerate(rows):
        q = _question(proxy, row, i)
        answer = next((o["value"] for o in q["options"] if o["label"] == row["correct_answer"]), row["correct_answer"])
        exercise = SimpleNamespace(id=i + 1, exercise_type=row["type"], content=deepcopy(row))
        for source in (None, exercise):
            result = check_answer(row, q, answer, exercise=source)
            assert result["correct"], (i, source, result)
        assert row["instruction"] in q["instruction"]
        if row["type"] == "fill_blank":
            assert "Можно также написать фразу с заполненным пропуском целиком." in q["instruction"]  # noqa: RUF001 -- Russian learner copy
        else:
            assert q["instruction"] == row["instruction"]
        assert q["theory_help"] == next(s["theory"] for s in steps if str(i) in s["question_ids"])


def test_guided_sequence_rejects_missing_or_reordered_questions():
    from app.api.native_lessons import NativeLessonError

    content = plurals_content()
    content["learning_steps"][0]["question_ids"] = ["1", "0", "2"]
    with pytest.raises(NativeLessonError):
        learning_steps(content, 24)


def test_pilot_does_not_penalize_case_spaces_or_final_full_stop():
    from app.api.native_content import _question, grade

    content = plurals_content()
    rows = content["exercises"]
    proxy = SimpleNamespace(id=42, type="grammar", content=content,
                            module=SimpleNamespace(level=SimpleNamespace(code="A1")))
    questions = [_question(proxy, row, i) for i, row in enumerate(rows)]
    answers = {}
    for q, row in zip(questions, rows, strict=True):
        expected = row["correct_answer"]
        answers[q["id"]] = next((o["value"] for o in q["options"] if o["label"] == expected), expected.upper().rstrip(".") + "  ")
        assert check_answer(row, q, answers[q["id"]])["correct"]
    result, feedback, _, _ = grade(proxy, questions, answers, 70)
    assert result["score"] == 100 and all(f["correct"] for f in feedback)


def test_wrong_answer_has_immediate_explanation_without_progress_writes(native_context):
    c = native_context
    lesson = fetch(c)
    assert lesson["immediate_feedback"]
    response = c.client.post("/api/native/lessons/42/check", headers=c.headers, json={
        "session_token": lesson["session_token"], "question_id": "0", "answer": "are"})
    assert response.status_code == 200, response.json
    assert response.json["feedback"]["correct"] is False
    assert response.json["feedback"]["expected"] == "am"
    assert response.json["feedback"]["explanation"] == "I + am"
    assert not c.writes
    assert not c.db.commit.called


def test_retry_checks_same_question_and_new_lesson_attempt_has_new_result(native_context):
    c = native_context
    lesson = fetch(c)
    for answer, correct in [("are", False), ("am", True)]:
        response = c.client.post("/api/native/lessons/42/check", headers=c.headers, json={
            "session_token": lesson["session_token"], "question_id": "0", "answer": answer})
        assert response.json["feedback"]["correct"] is correct
    assert submit(c, lesson["session_token"], {"0": "are", "1": "0"}).json["score"] == 0
    second = fetch(c)
    assert second["session_token"] != lesson["session_token"]
    assert submit(c, second["session_token"]).json["score"] == 100
    assert len(c.writes) == 2


def test_final_test_has_no_question_help_or_preview_even_with_authored_help(native_context):
    c = native_context
    c.lesson.type = "final_test"
    c.lesson.content = {"questions": [{"type": "multiple_choice", "question": "I ___ here.",
        "options": ["am", "is"], "correct": 0,
        "theory_help": [{"title": "Hidden rule", "body": "I + am"}]}]}
    lesson = fetch(c)
    assert not lesson["immediate_feedback"]
    assert "theory_help" not in lesson["questions"][0]
    response = c.client.post("/api/native/lessons/42/check", headers=c.headers, json={
        "session_token": lesson["session_token"], "question_id": "0", "answer": "0"})
    assert response.status_code == 404
    assert not c.writes


def test_stale_or_foreign_check_cannot_reveal_feedback(native_context):
    c = native_context
    lesson = fetch(c)
    c.lesson.content["exercises"][0]["answer"] = "was"
    body = {"session_token": lesson["session_token"], "question_id": "0", "answer": "am"}
    assert c.client.post("/api/native/lessons/42/check", headers=c.headers, json=body).status_code == 409
    assert c.client.post("/api/native/lessons/42/check", json=body).status_code == 401
    assert not c.writes


def test_pilot_import_is_idempotent_and_preserves_old_exercises(native_app):
    from app.grammar_lab.content_pilot import install_plurals_pilot
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, GrammarAttempt
    from app.utils.db import db
    from tests.api.test_native_full_integration import learner

    user, headers = learner(native_app)
    topic = GrammarTopic(slug="a1-4", title="Plural nouns", title_ru="Множественное число и указательные местоимения",
                         level="A1", content={"rule": "Old rule"})
    db.session.add(topic)
    db.session.flush()
    old = GrammarExercise(topic_id=topic.id, exercise_type="fill_blank",
                          content={"question": "one cat → two ___", "correct_answer": "cats"})
    db.session.add(old)
    db.session.commit()
    old_id = old.id
    install_plurals_pilot(apply=True)
    ids = list(topic.content["guided_exercise_ids"])
    install_plurals_pilot(apply=True)
    assert topic.content["guided_exercise_ids"] == ids
    assert db.session.get(GrammarExercise, old_id).content["correct_answer"] == "cats"
    assert GrammarExercise.query.filter_by(topic_id=topic.id).count() == 25
    client = native_app.test_client()
    material = client.get(f"/api/native/grammar/topics/{topic.id}", headers=headers).json["topic"]
    assert material["guided_learning"]
    response = client.post("/api/native/activities/grammar_topic/start", headers=headers,
        json={"item_id": f"grammar_topic:{topic.id}", "request_id": str(uuid4())})
    assert response.status_code == 200, response.json
    lesson = response.json["lesson"]
    assert len(lesson["learning_steps"]) == 8 and len(lesson["questions"]) == 24
    assert lesson["questions"][0]["theory_help"]
    checked = client.post("/api/native/activities/grammar_topic/check", headers=headers,
        json={"session_token": lesson["session_token"], "question_id": "0", "answer": "cat"})
    assert checked.status_code == 200, checked.json
    assert not checked.json["feedback"]["correct"]
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 0
    authored = plurals_content()["exercises"]
    answers = {}
    for q, row in zip(lesson["questions"], authored, strict=True):
        answers[q["id"]] = next((o["value"] for o in q["options"] if o["label"] == row["correct_answer"]), row["correct_answer"])
    submission = {"session_token": lesson["session_token"], "answers": answers}
    result = client.post("/api/native/activities/grammar_topic/submit", headers=headers, json=submission)
    assert result.status_code == 200 and result.json["correct_count"] == 24, result.json
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 24
    assert client.get(f"/api/native/grammar/topics/{topic.id}", headers=headers).json["topic"]["progress"]["theory_completed"]
    replay = client.post("/api/native/activities/grammar_topic/submit", headers=headers, json=submission)
    assert replay.json == result.json
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 24


def test_regular_quiz_checks_now_but_final_test_checks_only_after_submission(native_context):
    c = native_context
    c.lesson.type = "quiz"
    c.lesson.content = {"questions": [{"type": "multiple_choice", "question": "She ___ here.",
        "options": ["are", "is"], "correct": 1, "explanation": "She + is.",
        "theory_help": [{"title": "Форма is", "body": "После she используем is."}]}]}
    quiz = fetch(c)
    assert quiz["immediate_feedback"] and quiz["questions"][0]["theory_help"]
    response = c.client.post("/api/native/lessons/42/check", headers=c.headers, json={
        "session_token": quiz["session_token"], "question_id": "0", "answer": "0"})
    assert response.status_code == 200 and not response.json["feedback"]["correct"]
    assert response.json["feedback"]["expected"] == "is"
    assert response.json["feedback"]["explanation"] == "She + is."
    assert not c.writes
