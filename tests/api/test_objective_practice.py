"""Same pure feedback/grade, immutable score and receipt for ordinary formats."""
# ruff: noqa: F401,F811 -- imported pytest fixtures are discovered by name.

import json
import pytest
from tests.api.test_quiz_corrections import course, native_app, document, submit, progress_and_attempts

CASES = [
    (
        "audio_fill_blank",
        {
            "items": [
                {"text_with_gap": "I ___ here.", "answer": "am", "options": ["am", "is"]},
                {"text_with_gap": "They are at ___.", "answer": "home"},
            ]
        },
        {"0": "1", "1": "HOME!"},
        {"0": "0"},
    ),
    (
        "dictation",
        {"gap_text": "I {0} at {1}.", "gaps": [{"answer": "am"}, {"answer": "home"}]},
        {"0": "is", "1": "HOME!"},
        {"0": "AM!"},
    ),
    ("dictation", {"transcript": "I am at home"}, {"0": "I is at home"}, {"0": "I AM AT HOME!"}),
    (
        "sentence_completion",
        {"items": [{"prompt": "I ___ here.", "answer": "am"}, {"prompt": "They ___ here.", "answer": "are"}]},
        {"0": "is", "1": "ARE!"},
        {"0": "AM!"},
    ),
    (
        "sentence_correction",
        {
            "items": [
                {"incorrect_sentence": "He are here.", "correct_sentence": "He is here."},
                {"incorrect_sentence": "They is here.", "correct_sentence": "They are here."},
            ]
        },
        {"0": "He are here", "1": "They ARE here!"},
        {"0": "HE IS HERE!"},
    ),
    (
        "translation",
        {
            "items": [
                {"russian": "Я здесь.", "english": "I am here."},
                {"russian": "Мы дома.", "english": "We are at home."},
            ]
        },
        {"0": "wrong", "1": "We ARE AT HOME!"},
        {"0": "I AM HERE!"},
    ),
    (
        "reading",
        {
            "text": "I am here. We are home.",
            "questions": [
                {"type": "multiple_choice", "question": "Who is here?", "options": ["I", "They"], "correct": 0},
                {"type": "multiple_choice", "question": "Where?", "options": ["home", "away"], "correct": 0},
            ],
        },
        {"0": "1", "1": "0"},
        {"0": "0"},
    ),
    (
        "collocation_matching",
        {
            "pairs": [
                {"phrase": "Hello", "translation": "Привет"},
                {"phrase": "Bye", "translation": "Пока"},
                {"phrase": "Thanks", "translation": "Спасибо"},
                {"phrase": "Please", "translation": "Пожалуйста"},
            ]
        },
        {"0": '{"0":"0","1":"1","2":"3","3":"2"}'},
        {"0": '{"0":"0","1":"1","2":"2","3":"3"}'},
    ),
]


@pytest.mark.parametrize("kind,content,initial,corrected", CASES)
def test_objective_feedback_first_and_correction_agree(course, kind, content, initial, corrected):
    from app.utils.db import db

    model = course[2]
    model.type = kind
    model.content = {**content, "passing_score_percent": 90}
    db.session.commit()
    first = document(course)
    assert first["quiz_phase"] == "first" and first["passing_score"] == 50 and first["immediate_feedback"]
    user, headers, model, client, awards = course
    checks = []
    for q in first["questions"]:
        check = client.post(
            f"/api/native/lessons/{model.id}/check",
            headers=headers,
            json={"session_token": first["session_token"], "question_id": q["id"], "answer": initial[q["id"]]},
        )
        assert check.status_code == 200, check.json
        assert check.json["feedback"]["correct"] == (q["id"] not in corrected)
        checks.append(check.json)
    assert awards == []
    from app.curriculum.models import LessonProgress, LessonAttempt

    assert LessonProgress.query.filter_by(user_id=user.id, lesson_id=model.id).first() is None
    assert LessonAttempt.query.filter_by(user_id=user.id, lesson_id=model.id).count() == 0
    result = submit(course, first, initial)
    assert result.status_code == 200, result.json
    assert result.json["correction_pending"] and not result.json["completed"]
    score = result.json["score"]
    correction = document(course)
    assert set(q["id"] for q in correction["questions"]) == set(corrected)
    assert correction["correction"]["first_score"] == score
    for q in correction["questions"]:
        check = client.post(
            f"/api/native/lessons/{model.id}/check",
            headers=headers,
            json={
                "session_token": correction["session_token"],
                "question_id": q["id"],
                "answer": corrected[q["id"]],
                "help_level": 2,
            },
        )
        assert check.status_code == 200 and check.json["feedback"]["correct"], check.json
        if q.get("input") in ("match", "order", "long_text"):
            assert check.json["feedback"]["correction_help"]["segments"] == []
    fragments = correction["questions"][0].get("correction_help", {}).get("segments", [])
    fragment_answer = corrected[correction["questions"][0]["id"]]
    if fragments:
        words = fragment_answer.split()
        fragment_answer = " ".join(words[i] if s["editable"] else s["text"] for i, s in enumerate(fragments))
    fragment_check = client.post(
        f"/api/native/lessons/{model.id}/check",
        headers=headers,
        json={
            "session_token": correction["session_token"],
            "question_id": correction["questions"][0]["id"],
            "answer": fragment_answer,
            "help_level": 2,
        },
    )
    assert fragment_check.status_code == 200 and fragment_check.json["feedback"]["correct"], fragment_check.json
    done = submit(course, correction, corrected)
    assert done.status_code == 200, done.json
    assert done.json["completed"] and done.json["score"] == score
    assert done.json["correct_count"] == done.json["total_count"] == len(corrected)
    assert len(progress_and_attempts(course)[1]) == 1
    assert submit(course, correction, corrected).json == done.json
    assert submit(course, first, initial).json == result.json
    assert len(progress_and_attempts(course)[1]) == 1 and awards == [score]
    import os

    if os.environ.get("LLT_FIXTURE_DIR"):
        from pathlib import Path

        folder = Path(os.environ["LLT_FIXTURE_DIR"])
        folder.mkdir(parents=True, exist_ok=True)
        label = f"{kind}-{len(first['questions'])}"
        for suffix, value in [
            ("first", {"success": True, "lesson": first}),
            ("result", result.json),
            ("correction", {"success": True, "lesson": correction}),
            ("check", check.json),
            ("done", done.json),
            ("first-checks", checks),
            ("fragment-check", fragment_check.json),
            ("answers", {"initial": initial, "corrected": corrected, "fragment_answer": fragment_answer}),
        ]:
            (folder / f"{label}-{suffix}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
