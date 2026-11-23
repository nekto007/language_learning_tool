"""Cookie transport shares native scoring and retains browser CSRF protection."""
# ruff: noqa: F401,F811 -- imported pytest fixtures are discovered by name.

import re
from tests.api.test_quiz_corrections import course, native_app


def cookie_client(course):
    from app.utils.db import db
    from flask import g

    user, _, lesson, _, _ = course
    user.onboarding_completed = True
    db.session.commit()
    client = course[3]
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
        session["_fresh"] = True
    g.pop("_login_user", None)
    return client, lesson


def test_web_page_uses_shared_document_and_csrf_protected_feedback(course):
    client, lesson = cookie_client(course)
    page = client.get(f"/learn/{lesson.id}/")
    assert page.status_code == 200, page.location
    assert b"guided-practice.js" in page.data
    assert b"correct_answer" not in page.data
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    endpoint = f"/curriculum/api/lesson/{lesson.id}/practice"
    response = client.get(endpoint)
    assert response.status_code == 200, response.json
    assert response.headers["Cache-Control"] == "private, no-store"
    doc = response.json["lesson"]
    assert response.json["account_id"] == str(course[0].id)
    assert doc["quiz_phase"] == "first"
    body = {"session_token": doc["session_token"], "question_id": "0", "answer": "wrong"}
    assert client.post(endpoint + "/check", json=body).status_code == 400
    checked = client.post(endpoint + "/check", json=body, headers={"X-CSRFToken": csrf})
    assert checked.status_code == 200 and not checked.json["feedback"]["correct"], checked.json
    result = client.post(
        endpoint + "/submit",
        json={"session_token": doc["session_token"], "answers": {"0": "wrong", "1": "1"}},
        headers={"X-CSRFToken": csrf},
    )
    assert result.status_code == 200 and result.json["correction_pending"], result.json
    correction = client.get(endpoint).json["lesson"]
    assert correction["quiz_phase"] == "correction"
    assert client.get(f"/api/native/lessons/{lesson.id}").status_code == 401


def test_bookmarked_type_route_leads_to_shared_practice_without_progress_write(course):
    from app.curriculum.models import LessonProgress

    client, lesson = cookie_client(course)
    r = client.get(f"/curriculum/lesson/{lesson.id}?from=linear_plan")
    assert r.status_code == 302 and f"/learn/{lesson.id}/?from=linear_plan" in r.location
    assert LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=lesson.id).first() is None


def test_started_browser_draft_stays_in_compatible_editor(course):
    from app.curriculum.models import LessonProgress
    from app.curriculum.routes.guided_practice import uses_legacy_practice
    from app.utils.db import db
    from flask_login import login_user

    user, _, lesson, client, _ = course
    saved = {"answers": {"0": "old browser input"}}
    progress = LessonProgress(user_id=user.id, lesson_id=lesson.id, status="in_progress", data=saved)
    db.session.add(progress)
    db.session.commit()
    with client.application.test_request_context(f"/learn/{lesson.id}/"):
        login_user(user)
        assert uses_legacy_practice(lesson)
        progress.data = {**saved, "_native_submission": {"nonce": "same-engine"}}
        assert not uses_legacy_practice(lesson)
    assert progress.data["answers"] == saved["answers"]
