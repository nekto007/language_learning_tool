"""Anonymous diagnostics and voluntary, account-bound homepage invitations."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from flask_login import login_user

from app.auth.models import User
from app.onboarding import placement_engine as engine
from app.onboarding.placement_models import PlacementAttempt, PlacementGuest, PlacementPreference, utcnow
from app.onboarding.placement_home import invitation, dismiss
from app.onboarding.placement_guests import claim_after_login
from tests.test_placement_v2 import bank, complete

pytestmark = pytest.mark.smoke


def test_guest_can_complete_without_user_and_result_is_available_before_registration(client, db_session, bank):
    count = User.query.count()
    page = client.get("/placement")
    assert page.status_code == 200
    assert b'data-guest="true"' in page.data
    assert b"public-header" in page.data
    value = client.post("/onboarding/placement/v2/start", json={"mode": "quick"}).get_json()["attempt"]
    while value["status"] == "active":
        value = client.post(
            f"/onboarding/placement/v2/{value['id']}/answer",
            json={"question_id": value["question"]["id"], "answer": "", "dont_know": True},
        ).get_json()["attempt"]
    assert value["result"]["total"] == 14
    assert User.query.count() == count
    row = db_session.get(PlacementAttempt, value["id"])
    assert row.user_id is None and row.guest_key
    assert client.post(f"/onboarding/placement/v2/{value['id']}/apply", json={}).status_code == 401
    assert client.post("/placement/continue").status_code == 302


def test_anonymous_attempt_does_not_leak_to_another_cookie_jar(client, app, bank):
    client.get("/placement")
    value = client.post("/onboarding/placement/v2/start", json={"mode": "quick"}).get_json()["attempt"]
    other = app.test_client()
    other.get("/placement")
    assert other.get("/onboarding/placement/v2/status").get_json()["active"] is None
    assert (
        other.post(
            f"/onboarding/placement/v2/{value['id']}/answer",
            json={"question_id": value["question"]["id"], "answer": "", "dont_know": True},
        ).status_code
        == 404
    )


def test_guest_expiry_rejects_stale_api_but_page_can_create_fresh_identity(client, db_session, bank):
    client.get("/placement")
    first = PlacementGuest.query.one()
    first.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert client.get("/onboarding/placement/v2/status").status_code == 409
    client.get("/placement")
    assert PlacementGuest.query.count() == 2
    assert client.get("/onboarding/placement/v2/status").status_code == 200


def test_claim_requires_explicit_handoff_and_keeps_completed_answers(app, client, db_session, test_user, bank):
    client.get("/placement")
    guest = PlacementGuest.query.one()
    value = complete(guest.key)
    with client.session_transaction() as saved:
        token = saved["placement_guest"]
    with app.test_request_context("/login"):
        from flask import session

        session["placement_guest"] = token
        claim_after_login(app, test_user)
        assert db_session.get(PlacementAttempt, value["id"]).user_id is None
        session["placement_handoff"] = guest.key
        claim_after_login(app, test_user)
        row = db_session.get(PlacementAttempt, value["id"])
        assert row.user_id == test_user.id and row.guest_key is None
        assert row.result == value["result"] and row.applied_at is None
        assert session.get("placement_guest") is None


def test_home_initial_and_resume_are_voluntary_and_dismissible(db_session, test_user, bank):
    card = invitation(test_user.id)
    assert card["kind"] == "initial"
    dismiss(test_user.id, card["key"])
    assert invitation(test_user.id) is None
    attempt = engine.start(test_user.id, "quick")
    assert invitation(test_user.id)["key"] == "resume:" + attempt["id"]
    dismiss(test_user.id, "resume:" + attempt["id"])
    assert invitation(test_user.id) is None
    assert engine.status(test_user.id)["active"]["id"] == attempt["id"]
    engine.abandon(test_user.id, attempt["id"])
    assert invitation(test_user.id) is None


def test_completed_test_offers_result_not_initial_invitation(db_session, test_user, bank):
    result = complete(test_user.id)
    assert invitation(test_user.id)["kind"] == "result"
    with patch("app.utils.activity_tracker.has_learning_activity", return_value=False):
        engine.adopt_level(test_user.id, result["id"])
    assert invitation(test_user.id) is None


def test_existing_unstarted_learner_can_choose_level_today(db_session, test_user, bank):
    value = complete(test_user.id)
    with patch("app.utils.activity_tracker.has_learning_activity", return_value=False):
        receipt = engine.adopt_level(test_user.id, value["id"])
    assert receipt["effective_on"] is None
    assert test_user.onboarding_level == "C1"


@pytest.fixture
def mapped_review(db_session, test_user, bank):
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.onboarding.placement_reviews import seed

    topic = GrammarTopic(
        slug="fixture-topic", title="Synthetic topic", title_ru="Синтетическая тема", level="A1", order=1, content={}
    )
    db_session.add(topic)
    db_session.flush()
    for i in range(5):
        db_session.add(
            GrammarExercise(
                topic_id=topic.id,
                exercise_type="fill_blank",
                difficulty=1,
                content={
                    "question": f"Synthetic example {i}: I ___ here.",
                    "correct_answer": "am",
                    "explanation": "Synthetic explanation.",
                },
            )
        )
    row = PlacementAttempt(
        user_id=test_user.id,
        bank_id=bank.id,
        mode="quick",
        status="completed",
        state={"asked": []},
        completed_at=utcnow(),
        applied_at=utcnow(),
        result={"recommended_level": "A1", "review_topics": [{"slug": topic.slug}], "effective_on": None},
    )
    db_session.add(row)
    db_session.flush()
    seed(row)
    from app.onboarding.placement_reviews import due_review

    return due_review(test_user.id)


def test_targeted_review_replaces_second_lesson_without_growing_load(db_session, test_user, mapped_review):
    from app.onboarding.placement_reviews import replace_slot

    items = [
        {"id": "one", "kind": "curriculum", "eta_minutes": 8, "lesson_type": "quiz"},
        {"id": "srs", "kind": "srs", "eta_minutes": 5},
        {"id": "two", "kind": "curriculum", "eta_minutes": 8, "lesson_type": "quiz"},
    ]
    result = replace_slot(test_user.id, items)
    assert len(result) == len(items)
    assert result[0] == items[0] and result[1] == items[1]
    assert result[2]["data"]["placement_review_id"] == mapped_review.id
    assert result[2]["eta_minutes"] == 3
    assert replace_slot(test_user.id, items[:1]) == items[:1]
    assert replace_slot(test_user.id, [items[0], {**items[2], "lesson_type": "final_test"}])[1]["id"] == "two"


def test_native_and_web_followup_share_three_exercises_and_exact_completion(
    app, authenticated_client, db_session, test_user, mapped_review
):
    from app.onboarding.placement_reviews import item_for, due_review
    from app.daily_plan.snapshot import _is_item_completed
    from app.utils.db import db
    from flask_jwt_extended import create_access_token
    from uuid import uuid4

    item = item_for(mapped_review, "required")
    payload = {"item_id": item.id, "request_id": str(uuid4())}
    headers = {
        "Authorization": "Bearer "
        + create_access_token(identity=str(test_user.id), additional_claims={"auth_version": test_user.auth_version()})
    }
    native = app.test_client()
    with patch("app.api.native_activities._guard", return_value=None):
        response = authenticated_client.post(f"/onboarding/placement/review/{mapped_review.id}/start", json=payload)
        assert response.status_code == 200, response.get_json()
        doc = response.get_json()["lesson"]
        assert len(doc["questions"]) == 3
        assert response.get_json()["account_id"] == test_user.id
        assert not _is_item_completed(test_user.id, item.to_dict(), db)
        for q in doc["questions"]:
            checked = native.post(
                "/api/native/activities/grammar_review/check",
                headers=headers,
                json={"session_token": doc["session_token"], "question_id": q["id"], "answer": "AM!"},
            )
            assert checked.status_code == 200
            assert checked.get_json()["feedback"]["correct"]
        body = {"session_token": doc["session_token"], "answers": {str(i): "am" for i in range(3)}}
        saved = native.post("/api/native/activities/grammar_review/submit", headers=headers, json=body)
        assert saved.status_code == 200, saved.get_json()
        assert saved.get_json()["correct_count"] == 3
        assert _is_item_completed(test_user.id, item.to_dict(), db)
        assert due_review(test_user.id) is None
        retry = native.post("/api/native/activities/grammar_review/submit", headers=headers, json=body)
        assert retry.get_json() == saved.get_json()
        reloaded = authenticated_client.get(f"/placement/review/{mapped_review.id}")
        assert reloaded.status_code == 200
        assert "Тренировка на сегодня завершена" in reloaded.get_data(as_text=True)
        assert b'id="guided-practice"' not in reloaded.data


def test_guest_handoff_survives_real_registration_and_stale_guest_tab_is_denied(client, db_session, bank):
    from uuid import uuid4
    client.get("/placement")
    row = complete(PlacementGuest.query.one().key)
    handoff = client.post("/placement/continue")
    assert "level=C1" in handoff.location
    suffix = uuid4().hex[:10]
    with patch("app.auth.welcome_email.enqueue_welcome_email"):
        registered = client.post(handoff.location, data={
            "username": "guest_" + suffix, "email": suffix + "@example.com",
            "password": "Xk9$mP2vL!qw", "password2": "Xk9$mP2vL!qw",
        })
    assert registered.status_code == 302
    user = User.query.filter_by(username="guest_" + suffix).one()
    claimed = db_session.get(PlacementAttempt, row["id"])
    assert claimed.user_id == user.id and claimed.guest_key is None
    assert claimed.result == row["result"]
    stale = client.get("/onboarding/placement/v2/status", headers={"X-LLT-Placement-Guest": "1"})
    assert stale.status_code == 403
    assert client.get("/onboarding/placement/v2/status").get_json()["latest"]["id"] == row["id"]


def test_guest_handoff_can_explicitly_choose_existing_account_login(client, db_session, bank):
    client.get("/placement")
    complete(PlacementGuest.query.one().key)
    response = client.post("/placement/continue", data={"destination": "login"})
    assert "/login" in response.location and "next=" in response.location


def test_guest_writes_and_handoff_require_csrf(app, client, bank):
    previous = app.config["WTF_CSRF_ENABLED"]
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        client.get("/placement")
        assert client.post("/onboarding/placement/v2/start", json={"mode": "quick"}).status_code == 400
        from tests.security.test_csrf_sweep import _csrf_blocked
        assert _csrf_blocked(client.post("/placement/continue", headers={"Accept": "application/json"}))
    finally:
        app.config["WTF_CSRF_ENABLED"] = previous


def test_whole_level_checkpoint_is_not_a_module_checkpoint_and_replay_does_not_retrigger(
    db_session, test_user, bank
):
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
    stamp = utcnow()
    diagnostic = complete(test_user.id)
    attempt = db_session.get(PlacementAttempt, diagnostic["id"])
    attempt.applied_at = stamp - timedelta(days=2)
    attempt.completed_at = stamp - timedelta(days=2)
    level = CEFRLevel(code="A1", name="Synthetic level", order=1)
    db_session.add(level); db_session.flush()
    progress = []
    for number in (1, 2):
        module = Module(level_id=level.id, number=number, title="Synthetic module")
        db_session.add(module); db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, type="quiz", title="Synthetic lesson")
        db_session.add(lesson); db_session.flush()
        row = LessonProgress(user_id=test_user.id, lesson_id=lesson.id,
            status="completed" if number == 1 else "not_started",
            completed_at=stamp - timedelta(days=1) if number == 1 else None)
        db_session.add(row); progress.append(row)
    db_session.flush()
    assert invitation(test_user.id) is None
    progress[1].status = "completed"; progress[1].completed_at = stamp - timedelta(hours=1)
    db_session.flush()
    assert invitation(test_user.id)["kind"] == "checkpoint"
    dismiss(test_user.id, "level:A1")
    assert invitation(test_user.id) is None
    # A later diagnostic supersedes the checkpoint. Repeating an old lesson
    # must not manufacture another whole-level completion milestone.
    newer = complete(test_user.id)
    db_session.get(PlacementAttempt, newer["id"]).applied_at = stamp
    progress[0].completed_at = stamp + timedelta(hours=1)
    db_session.flush()
    assert invitation(test_user.id) is None


def test_imperfect_review_is_due_again_after_two_days_without_growing_today(db_session, test_user, mapped_review):
    from app.onboarding.placement_reviews import complete as finish, due_review, _today
    finish(test_user.id, mapped_review.id, 2, 3)
    assert mapped_review.state == "practice"
    assert mapped_review.practice == {"first_correct": 2, "total": 3}
    assert mapped_review.due_on == _today(test_user.id) + timedelta(days=2)
    assert due_review(test_user.id) is None


def test_review_cannot_be_opened_by_another_account_or_completed_by_unrelated_practice(
    authenticated_client, db_session, test_user, mapped_review
):
    from app.onboarding.placement_reviews import owned_review, item_for
    from app.daily_plan.snapshot import _is_item_completed
    from app.utils.db import db
    with pytest.raises(engine.PlacementError, match="not_found"):
        owned_review(test_user.id + 99999, mapped_review.id)
    item = item_for(mapped_review)
    with patch("app.daily_plan.items.grammar_review._grammar_reviewed_today", return_value=True):
        assert not _is_item_completed(test_user.id, item.to_dict(), db)


def test_retired_exercise_pool_drops_unreachable_review(db_session, test_user, mapped_review):
    from app.grammar_lab.models import GrammarExercise
    from app.onboarding.placement_reviews import due_review, unreachable
    for exercise in GrammarExercise.query.all():
        exercise.content = {**exercise.content, "guided_retired": True}
    db_session.flush()
    assert due_review(test_user.id) is None
    assert unreachable(test_user.id, mapped_review.id)


def test_expired_guest_cleanup_keeps_claimed_attempts(app, client, db_session, test_user, bank):
    from app.onboarding.placement_guests import cleanup_guests
    client.get("/placement")
    guest = PlacementGuest.query.one()
    result = complete(guest.key)
    with client.session_transaction() as saved:
        token = saved["placement_guest"]
    with app.test_request_context("/login"):
        from flask import session
        session.update(placement_guest=token, placement_handoff=guest.key)
        login_user(test_user)
    expired = PlacementGuest(key="e" * 64, expires_at=utcnow() - timedelta(days=1))
    db_session.add(expired);db_session.flush()
    assert cleanup_guests() == 1
    assert db_session.get(PlacementAttempt, result["id"]).user_id == test_user.id


def test_two_first_home_requests_can_recover_preference_creation_race(db_session, test_user, bank, monkeypatch):
    from app.utils.db import db
    from app.onboarding.placement_home import _preference
    existing = _preference(test_user.id)
    real_get = db.session.get
    missed = False
    def concurrent_get(model, key, **kwargs):
        nonlocal missed
        if model is PlacementPreference and not missed:
            missed = True
            return None
        return real_get(model, key, **kwargs)
    monkeypatch.setattr(db.session, "get", concurrent_get)
    assert _preference(test_user.id).user_id == existing.user_id
    assert invitation(test_user.id)["kind"] == "initial"


def test_guest_can_resume_after_browser_session_cookie_is_lost(client, app, db_session, bank):
    page = client.get("/placement")
    assert any("llt_placement_guest=" in value and "HttpOnly" in value and "SameSite=Lax" in value
        for value in page.headers.getlist("Set-Cookie"))
    attempt = client.post("/onboarding/placement/v2/start", json={"mode": "quick"}).get_json()["attempt"]
    client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"), domain="localhost")
    client.get("/placement")
    assert client.get("/onboarding/placement/v2/status").get_json()["active"]["id"] == attempt["id"]
    assert PlacementGuest.query.count() == 1
