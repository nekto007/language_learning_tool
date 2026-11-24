"""Use the current required plan, not the result score, to suggest the next action."""

from copy import deepcopy
from datetime import date

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.api import native_lessons
from app.auth.models import User
from app.curriculum import security
from app.curriculum.models import Lessons
from app.daily_plan import service
from app.telegram import queries
from app.utils import time_utils


DAY = "2026-11-24"
NEXT = "/api/daily-plan/next-step"


def slot(key: str, title: str, url: str, **fields: object) -> dict:
    return {"id": key, "kind": "curriculum", "title": title, "url": url, **fields}


@pytest.fixture
def daily_plan(authenticated_client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> tuple[FlaskClient, dict]:
    monkeypatch.setattr(time_utils, "get_user_local_date", lambda *_: date.fromisoformat(DAY))
    monkeypatch.setattr(queries, "get_daily_summary", lambda *_, **__: {"error_review_resolved_today": 1})
    plan = {
        "mode": "unified", "study_day": DAY, "_plan_meta": {"effective_mode": "unified"},
        "required": [], "optional": [slot("extra", "Дополнительное", "/study/extra")],
    }
    monkeypatch.setattr(service, "get_daily_plan_unified", lambda *_, **__: plan)
    return authenticated_client, plan


@pytest.fixture
def accessible_quiz(test_lesson_quiz: Lessons, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Lessons:
    test_lesson_quiz.content = {"questions": [{
        "type": "multiple_choice", "question": "They ___ ready.", "options": ["is", "are"], "correct": 1,
    }]}
    db_session.commit()
    monkeypatch.setattr(native_lessons, "_guard_plan", lambda _: "curriculum")
    monkeypatch.setattr(security, "check_lesson_access", lambda _: True)
    return test_lesson_quiz


def test_result_uses_canonical_required_title_and_url(daily_plan: tuple[FlaskClient, dict]) -> None:
    client, plan = daily_plan
    url = "/learn/13/?quiz_phase=correction&from=linear_plan&slot=curriculum"
    plan["required"] = [
        slot("done", "Ранее выполнено", "/learn/3/", completed=True),
        slot("activity", "Разбор ошибок", "/study/error-review", kind="error_review"),
        slot("skip", "Пропущено", "/learn/4/", skipped=True),
        slot("blocked", "Закрыто", "/learn/5/", blocked=True),
        slot("correction", "Работа над ошибками: Глагол to be", url,
             data={"lesson_id": 13, "quiz_phase": "correction"}),
        slot("next", "Следующий связанный урок", "/learn/14/"),
    ]
    original = deepcopy(plan)
    result = client.get(NEXT, query_string={"result_day": DAY})
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "private, no-store"
    assert result.json == {
        "success": True, "account_id": result.json["account_id"], "status": "next", "url": url,
        "title": "Работа над ошибками: Глагол to be", "lesson_id": 13, "quiz_phase": "correction",
    }
    assert result.json["account_id"].isdigit()
    assert plan == original


def test_correction_does_not_jump_ahead_of_required_review(daily_plan: tuple[FlaskClient, dict]) -> None:
    client, plan = daily_plan
    plan["required"] = [
        slot("srs", "Повтори слова", "/study/review?from=linear_plan", kind="srs"),
        slot("correction", "Работа над ошибками", "/learn/13/?quiz_phase=correction",
             data={"lesson_id": 13, "quiz_phase": "correction"}),
    ]
    value = client.get(NEXT, query_string={"result_day": DAY}).json
    assert value["status"] == "next" and value["url"] == "/study/review?from=linear_plan"
    assert value["title"] == "Повтори слова"


def test_result_done_uses_authoritative_required_completion(daily_plan: tuple[FlaskClient, dict]) -> None:
    client, plan = daily_plan
    plan["required"] = [
        slot("done", "Пройденное занятие", "/learn/13/", completed=True),
        slot("resolved", "Разбор ошибок", "/study/error-review", kind="error_review"),
    ]
    assert client.get(NEXT, query_string={"result_day": DAY}).json["status"] == "secured"
    assert client.get(NEXT).json["step_scope"] == "optional"


@pytest.mark.parametrize(("state", "expected"), [
    ("paused", "paused"), ("no_required", "plan"), ("only_skipped", "plan"),
    ("only_blocked", "plan"), ("unsafe_url", "plan"), ("missing_title", "plan"),
    ("stale_plan_payload", "plan"),
])
def test_result_avoids_optional_or_unusable_destinations(
    daily_plan: tuple[FlaskClient, dict], state: str, expected: str,
) -> None:
    client, plan = daily_plan
    if state == "paused":
        plan.update(mode="paused", required=[slot("ready", "Недоступное", "/learn/13/")])
    elif state == "only_skipped":
        plan["required"] = [slot("skip", "Пропущено", "/learn/13/", skipped=True)]
    elif state == "only_blocked":
        plan["required"] = [slot("block", "Блокировка", "/learn/13/", blocked=True)]
    elif state == "unsafe_url":
        plan["required"] = [slot("ready", "Задание", "//example.invalid/external")]
    elif state == "missing_title":
        plan["required"] = [slot("ready", "", "/learn/13/")]
    elif state == "stale_plan_payload":
        plan.update(study_day="2026-11-23", required=[slot("ready", "Вчера", "/learn/13/")])
    value = client.get(NEXT, query_string={"result_day": DAY}).json
    assert value["status"] == expected and "url" not in value


def test_stale_result_opens_today_plan_without_assembling_old_day(
    daily_plan: tuple[FlaskClient, dict], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = daily_plan

    def unexpected_plan(*_args: object, **_kwargs: object) -> dict:
        pytest.fail("An old result should not ask for a continuation plan")

    monkeypatch.setattr(service, "get_daily_plan_unified", unexpected_plan)
    value = client.get(NEXT, query_string={"result_day": "2026-11-23"}).json
    assert value["status"] == "day_changed" and "url" not in value


def test_web_lesson_document_marks_the_study_day(
    authenticated_client: FlaskClient, accessible_quiz: Lessons, test_user: User, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time_utils, "get_user_local_date", lambda *_: date.fromisoformat(DAY))
    response = authenticated_client.get(f"/curriculum/api/lesson/{accessible_quiz.id}/practice")
    assert response.status_code == 200, response.json
    assert response.json["lesson"]["study_day"] == DAY
    assert response.json["account_id"] == str(test_user.id)


def test_history_identity_revalidates_authored_revision_without_opening_the_editor(
    authenticated_client: FlaskClient, accessible_quiz: Lessons, test_user: User, db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, lesson = authenticated_client, accessible_quiz
    endpoint = f"/curriculum/api/lesson/{lesson.id}/practice"
    document = client.get(endpoint).json["lesson"]

    def paused(*_args: object) -> None:
        raise native_lessons.NativeLessonError("plan_paused", 403)

    monkeypatch.setattr(native_lessons, "_guard_plan", paused)
    identity = client.get(endpoint, query_string={"result_identity": "1"})
    assert identity.headers["Cache-Control"] == "private, no-store"
    assert identity.json == {
        "success": True, "account_id": str(test_user.id),
        "lesson": {"id": lesson.id, "type": lesson.type, "content_revision": document["content_revision"]},
    }
    assert client.get(endpoint).status_code == 403
    lesson.content = {**lesson.content, "description": "Updated grammar rule"}
    db_session.commit()
    updated = client.get(endpoint, query_string={"result_identity": "1"}).json["lesson"]
    assert updated["content_revision"] != document["content_revision"]
