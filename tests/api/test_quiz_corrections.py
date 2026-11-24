"""Independent scores and assisted completion on a disposable real database."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.api.quiz_corrections import correction_help
from tests.api.test_native_full_integration import learner
from tests.api.test_account_deletion import native_app as _native_app


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    from app.api import native_lessons
    from app.curriculum.models import CEFRLevel, Module, Lessons
    from app.utils.db import db
    import app.curriculum.security as security
    import app.daily_plan.linear.xp as xp

    user, headers = learner(native_app)
    level = CEFRLevel(code=uuid4().hex[:8], name="Isolated correction test")
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title="Corrections")
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(module_id=module.id, number=1, title="First round", type="grammar", content={
        "description": "She + goes. They + are.",
        "exercises": [
            {"type": "transformation", "question": "Correct: She go to school.",
             "correct_answer": "She goes to school.", "explanation": "She + goes."},
            {"type": "multiple_choice", "question": "They ___ ready.",
             "options": ["is", "are"], "correct": 1, "explanation": "They + are."},
        ]})
    db.session.add(lesson)
    db.session.commit()
    monkeypatch.setattr(native_lessons, "_guard_plan", lambda *a: "curriculum")
    monkeypatch.setattr(security, "check_lesson_access", lambda *a: True)
    awards = []
    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", lambda *a, **k: awards.append(k["score"]))
    return user, headers, lesson, native_app.test_client(), awards


def document(course, optin=True):
    _, headers, lesson, client, _ = course
    response = client.get(f"/api/native/lessons/{lesson.id}" + ("?quiz_flow=deferred_v1" if optin else ""), headers=headers)
    assert response.status_code == 200, response.json
    return response.json["lesson"]


def submit(course, lesson, answers):
    _, headers, model, client, _ = course
    return client.post(f"/api/native/lessons/{model.id}/submit", headers=headers,
                       json={"session_token": lesson["session_token"], "answers": answers})


def progress_and_attempts(course):
    from app.curriculum.models import LessonProgress, LessonAttempt
    user, _, lesson, _, _ = course
    return (LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).one(),
            LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson.id).all())


def test_passing_first_round_is_deferred_and_keeps_score(course):
    first = document(course)
    assert first["quiz_phase"] == "first" and first["passing_score"] == 50
    assert "correction_help" not in first["questions"][0]
    result = submit(course, first, {"0": "She go to school", "1": "1"})
    assert result.status_code == 200, result.json
    assert result.json["score"] == 50 and result.json["passed"]
    assert result.json["completed"] is False and result.json["correction_pending"]
    progress, attempts = progress_and_attempts(course)
    assert progress.status == "in_progress" and progress.last_score == 50
    assert len(attempts) == 1 and attempts[0].score == 50 and attempts[0].passed
    assert course[-1] == []
    # Lost first-round response remains the same receipt, not a second attempt.
    assert submit(course, first, {"0": "She goes to school", "1": "1"}).json == result.json
    correction = document(course, optin=False)
    assert correction["quiz_phase"] == "correction"
    assert [q["id"] for q in correction["questions"]] == ["0"]
    assert correction["learning_steps"] == []
    assert correction["correction"]["first_correct_count"] == 1
    assert correction["correction"]["first_total_count"] == 2
    assert not correction["correction"]["theory_required"]
    assert correction["questions"][0]["instruction"].startswith("Впиши пропущенное слово.")
    assert correction["questions"][0]["correction_help"]["segments"] == [
        {"text": "She", "editable": False}, {"text": "", "editable": True},
        {"text": "to", "editable": False}, {"text": "school.", "editable": False},
    ]


def test_assisted_completion_does_not_inflate_failed_score_or_attempts(course):
    from app.daily_plan.linear.models import QuizErrorLog

    first = document(course)
    first_result = submit(course, first, {"0": "She go to school", "1": "0"}).json
    assert first_result["score"] == 0 and not first_result["passed"]
    correction = document(course)
    assert correction["correction"]["theory_required"]
    assert [q["id"] for q in correction["questions"]] == ["0", "1"]
    user, headers, model, client, awards = course
    progress, _ = progress_and_attempts(course)
    before = deepcopy(progress.data)
    response = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
        "session_token": correction["session_token"], "question_id": "0",
        "answer": "She go to school", "help_level": 3})
    assert response.status_code == 200, response.json
    assert not response.json["feedback"]["correct"]
    assert "goes." not in response.json["feedback"]["correction_help"]["choices"]
    assert progress_and_attempts(course)[0].data == before
    failed = submit(course, correction, {"0": "She goes to school", "1": "0"})
    assert failed.status_code == 200 and not failed.json["completed"]
    assert progress_and_attempts(course)[0].data == before
    completed = submit(course, correction, {"0": "SHE GOES TO SCHOOL!", "1": "1"})
    assert completed.status_code == 200, completed.json
    assert completed.json["completed"] and not completed.json["correction_pending"]
    assert completed.json["score"] == 0 and not completed.json["passed"]
    assert completed.json["correct_count"] == completed.json["total_count"] == 2
    progress, attempts = progress_and_attempts(course)
    assert progress.status == "completed" and progress.last_score == progress.best_score == 0
    assert progress.data["quiz_correction"]["first_answers"] == {"0": "She go to school", "1": "0"}
    assert progress.data["quiz_correction"]["status"] == "completed"
    assert len(attempts) == 1 and not attempts[0].passed and attempts[0].score == 0
    assert QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=model.id, resolved_at=None).count() == 0
    assert awards == [0]
    # Account serialisation + saved nonce make both receipts exactly-once.
    assert submit(course, correction, {"0": "SHE GOES TO SCHOOL!", "1": "1"}).json == completed.json
    assert submit(course, first, {"0": "She go to school", "1": "0"}).json == first_result
    assert len(progress_and_attempts(course)[1]) == 1 and awards == [0]


def test_correction_checks_reject_first_correct_question_and_invalid_help(course):
    first = document(course)
    submit(course, first, {"0": "She go to school", "1": "1"})
    correction = document(course)
    _, headers, model, client, _ = course
    body = {"session_token": correction["session_token"], "question_id": "1", "answer": "1"}
    assert client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json=body).status_code == 400
    body.update(question_id="0", answer="She go to school")
    for level in (-1, 4, True, "1", 1.5):
        assert client.post(f"/api/native/lessons/{model.id}/check", headers=headers,
                           json={**body, "help_level": level}).status_code == 400
    assert submit(course, correction, {"0": "She goes to school", "1": "1"}).status_code == 400
    assert len(progress_and_attempts(course)[1]) == 1


def test_changed_content_and_foreign_account_cannot_submit_corrections(course, native_app):
    from app.utils.db import db

    first = document(course)
    submit(course, first, {"0": "She go to school", "1": "1"})
    correction = document(course)
    _, _, model, client, _ = course
    _, foreign_headers = learner(native_app)
    response = client.post(f"/api/native/lessons/{model.id}/submit", headers=foreign_headers,
        json={"session_token": correction["session_token"], "answers": {"0": "She goes to school"}})
    assert response.status_code == 403
    model.content = {**model.content, "description": "Updated theory"}
    db.session.commit()
    assert submit(course, correction, {"0": "She goes to school"}).status_code == 409
    assert document(course)["quiz_phase"] == "first"
    assert progress_and_attempts(course)[0].status == "in_progress"


def test_all_correct_and_voluntary_repeat_never_relock_completed_lesson(course):
    first = document(course)
    response = submit(course, first, {"0": "She goes to school", "1": "1"})
    assert response.json["completed"] and not response.json.get("correction_pending")
    repeated = submit(course, document(course), {"0": "She go to school", "1": "0"})
    assert repeated.status_code == 200 and not repeated.json.get("correction_pending")
    assert progress_and_attempts(course)[0].status == "completed"


def test_correction_keeps_original_nonzero_question_id(course):
    first = document(course)
    submit(course, first, {"0": "She goes to school", "1": "0"})
    correction = document(course)
    assert [q["id"] for q in correction["questions"]] == ["1"]
    result = submit(course, correction, {"1": "1"})
    assert result.status_code == 200, result.json
    assert result.json["completed"] and result.json["score"] == 50
    assert [f["id"] for f in result.json["feedback"]] == ["1"]


def test_four_errors_require_theory_even_after_passing_first_round(course):
    from app.utils.db import db
    model = course[2]
    model.content = {"description": "I + am.", "exercises": [
        {"type": "fill_blank", "question": f"Example {i}: I ___ here.", "answer": "am"}
        for i in range(9)]}
    db.session.commit()
    result = submit(course, document(course), {str(i): "are" if i < 4 else "am" for i in range(9)})
    assert result.json["score"] == 55.56 and result.json["passed"]
    correction = document(course)
    assert len(correction["questions"]) == 4 and correction["correction"]["theory_required"]


def test_module_final_never_exposes_correction_flow(course):
    from app.utils.db import db
    course[2].type = "final_test"
    course[2].content = {"questions": [{"type": "multiple_choice", "question": "Choose the correct form: I ___ a student.",
                                     "options": ["am", "is"], "correct": 0}]}
    db.session.commit()
    final = document(course)
    assert final["passing_score"] == 75 and "quiz_phase" not in final
    assert not final["immediate_feedback"]
    assert not final.get("correction")


def test_forced_correction_review_has_material_even_without_language_support(course):
    from app.curriculum.models import Lessons
    from app.utils.db import db

    model = course[2]
    model.module.level.code = "C1"
    model.number = 2
    model.type = "quiz"
    model.content = {"questions": [{"type": "fill_in_blank", "question": "She ___ to school.", "correct": "goes"}]}
    db.session.add(Lessons(module_id=model.module_id, number=1, type="grammar", title="Reference",
                          content={"description": "Use goes after she in the present simple."}))
    db.session.commit()
    first = document(course)
    assert first["support_mode"] == "off"
    assert submit(course, first, {"0": "go"}).status_code == 200
    correction = document(course)
    assert correction["correction"]["theory_required"]
    assert any("Use goes after she" in block["body"] for block in correction["theory"])


def test_legacy_correction_without_authored_theory_has_explanation_fallback(course):
    from app.utils.db import db

    model = course[2]
    model.type = "quiz"
    model.content = {"questions": [{"type": "fill_in_blank", "question": "She ___ to school.", "correct": "goes"}]}
    db.session.commit()
    assert submit(course, document(course), {"0": "go"}).status_code == 200
    correction = document(course)
    assert correction["correction"]["theory_required"]
    assert correction["theory"] and all(block["body"].strip() for block in correction["theory"])


def test_punctuation_in_learner_answer_survives_json_feedback(course):
    first = document(course)
    _, headers, model, client, _ = course
    answer = "<SHE> GOES TO SCHOOL!"
    response = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
        "session_token": first["session_token"], "question_id": "0", "answer": answer})
    assert response.status_code == 200, response.json
    assert response.json["feedback"]["correct"]
    assert response.json["feedback"]["answer"] == answer
    result = submit(course, first, {"0": answer, "1": "1"})
    assert result.status_code == 200 and result.json["score"] == 100
    assert result.json["feedback"][0]["answer"] == answer


def test_scaffold_preserves_alignment_repetitions_and_never_fills_all_gaps():
    row = {"alternatives": ["They are at home."]}
    question = {"id": "3", "input": "text", "options": []}
    feedback = {"correct": False, "expected": "They are in the house.", "explanation": "They + are."}
    help_ = correction_help(row, question, "they is at home", feedback)
    assert help_["segments"] == [{"text": "They", "editable": False}, {"text": "", "editable": True},
                                 {"text": "at", "editable": False}, {"text": "home.", "editable": False}]
    previous = None
    for level in range(4):
        current = correction_help({}, question, "We no yesterday", {**feedback, "expected": "We did not go yesterday."}, level)
        blank_count = sum(s["editable"] for s in current["segments"])
        assert blank_count >= 1
        if previous is not None:
            assert blank_count <= previous
        previous = blank_count
        assert current == correction_help({}, question, "We no yesterday", {**feedback, "expected": "We did not go yesterday."}, level)
    assert current["choices"]
    surplus = correction_help({}, question, "I am am here", {**feedback, "expected": "I am here."})
    assert any(s["editable"] for s in surplus["segments"])
    matching_gap = correction_help({}, question, "He go at school", {**feedback, "expected": "She goes to school."}, 3)
    assert set(matching_gap["choices"]) == {"to", "at"}
    many_gaps = correction_help({}, question, "", {**feedback, "expected": "We have never been to that new school before."}, 2)
    assert sum(s["editable"] for s in many_gaps["segments"]) == 1
    array_answer = correction_help({"correct_answer": ["a", "an"]}, question, "en",
                                  {**feedback, "expected": "['a', 'an']"}, 3)
    assert array_answer["segments"] == [{"text": "", "editable": True}]
    assert "an" in array_answer["choices"]


def test_choice_scaffold_never_treats_transport_values_as_text():
    question = {"id": "0", "input": "choice", "options": [{"value": "0", "label": "are"}]}
    help_ = correction_help({}, question, "0", {"correct": False, "expected": "is"}, 3)
    assert help_["segments"] == help_["choices"] == []


def test_export_mobile_contract_from_real_handlers(course, tmp_path):
    """The platform tests can decode the very same server response shapes."""
    import json

    first = document(course)
    result = submit(course, first, {"0": "She go to school", "1": "1"}).json
    correction = document(course)
    _, headers, model, client, _ = course
    checked = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
        "session_token": correction["session_token"], "question_id": "0",
        "answer": "She go to school", "help_level": 1}).json
    completed = submit(course, correction, {"0": "She goes to school"}).json
    first["session_token"], correction["session_token"] = "contract-first", "contract-correction"
    fixtures = {"first": {"success": True, "lesson": first}, "first_result": result,
                "correction": {"success": True, "lesson": correction}, "wrong_check": checked,
                "correction_result": completed}
    for name, value in fixtures.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    print("Mobile contract fixtures:", tmp_path)


def test_phrase_review_preview_and_submission_share_quiz_text_policy(native_app, monkeypatch):
    from app.api import native_activities as activities

    _, headers = learner(native_app)
    client = native_app.test_client()
    monkeypatch.setattr(activities, "_guard", lambda *a: None)
    monkeypatch.setattr(activities, "_prepare", lambda kind, item, plan_item: {
        "rows": [{"type": "translation", "prompt": "Она не ходит пешком.", "answer": "She doesn't walk.",
                  "acceptable_answers": ["She does not walk."]}],
        "source": {"items": [{"answer": "She doesn't walk.", "accepted_answers": ["She does not walk."]}]},
        "theory": [], "title": "Phrases", "level": "A1", "item_id": item, "day": activities._day()})
    response = client.post("/api/native/activities/phrase_review/start", headers=headers,
        json={"item_id": "phrase_review:test", "request_id": str(uuid4())})
    assert response.status_code == 200, response.json
    document = response.json["lesson"]
    assert document["passing_score"] == 50
    # Use the primary contracted answer without its apostrophe, even though
    # the alternative list contains only the expanded form.
    answer = "SHE DOESNT WALK!!!"
    body = {"session_token": document["session_token"], "question_id": "0", "answer": answer}
    preview = client.post("/api/native/activities/phrase_review/check", headers=headers, json=body)
    assert preview.status_code == 200 and preview.json["feedback"]["correct"], preview.json
    result = client.post("/api/native/activities/phrase_review/submit", headers=headers,
        json={"session_token": document["session_token"], "answers": {"0": answer}})
    assert result.status_code == 200 and result.json["score"] == 100, result.json
    assert result.json["feedback"][0]["answer"] == answer
