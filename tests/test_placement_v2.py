"""Durable diagnostic contracts; no production content, progress or email."""

from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from flask_jwt_extended import create_access_token
import pytest

from app.onboarding import placement_engine as engine
from app.onboarding.placement_bank import validate_bank, bank_digest
from app.onboarding.placement_models import PlacementAttempt, PlacementBank
from app.curriculum.models import LessonProgress
from app.daily_plan.models import DailyPlanLog
from app.utils.time_utils import study_day_date_for_tz
from tests.placement_fixtures import synthetic_bank

pytestmark = pytest.mark.smoke


@pytest.fixture
def bank(db_session):
    content = validate_bank(synthetic_bank())
    row = PlacementBank(id=bank_digest(content), label=content["label"], active=True, content=content)
    db_session.add(row)
    db_session.flush()
    return row


def complete(user_id: int, mode: str = "quick", correct: bool = True) -> dict:
    value = engine.start(user_id, mode)
    while value["status"] == "active":
        value = engine.answer(
            user_id, value["id"], value["question"]["id"], "A correct answer" if correct else "", not correct
        )
    return value


@pytest.mark.parametrize("mode,total", [("quick", 14), ("detailed", 24)])
def test_both_modes_complete_and_never_award_course_progress(db_session, test_user, bank, mode: str, total: int):
    before = LessonProgress.query.filter_by(user_id=test_user.id).count()
    value = complete(test_user.id, mode)
    assert value["answered"] == total
    assert value["result"]["recommended_level"] == "C1"
    assert value["result"]["total"] == total
    assert value["result"]["speaking_assessed"] is False
    assert value["result"]["free_writing_assessed"] is False
    assert value["result"]["domains"][-1]["total"] == (0 if mode == "quick" else 2)
    assert "question" not in value
    assert test_user.onboarding_level != "C1"
    assert LessonProgress.query.filter_by(user_id=test_user.id).count() == before
    assert DailyPlanLog.query.filter_by(user_id=test_user.id).count() == 0


def test_all_unknown_and_a_single_correct_answer_do_not_promote_user(db_session, test_user, bank):
    value = engine.start(test_user.id, "quick")
    count = 0
    while value["status"] == "active":
        count += 1
        known = count == 6
        value = engine.answer(
            test_user.id, value["id"], value["question"]["id"], "A correct answer" if known else "", not known
        )
    assert value["result"]["recommended_level"] == "A1"
    assert value["result"]["correct_count"] == 1


@pytest.mark.parametrize("correct", [False, True])
def test_detailed_extremes_never_exhaust_or_repeat_bank_items(db_session, test_user, bank, correct):
    value = complete(test_user.id, "detailed", correct)
    assert value["answered"] == 24
    row = db_session.get(PlacementAttempt, value["id"])
    asked = [q["id"] for q in row.state["asked"]]
    assert len(asked) == len(set(asked)) == 24
    assert value["result"]["recommended_level"] == ("C1" if correct else "A1")


def test_no_keys_levels_or_per_question_verdicts_are_exposed(db_session, test_user, bank):
    value = engine.start(test_user.id, "quick")
    for _ in range(4):
        serialized = json.dumps(value)
        assert not {"answers", "correct", "level", "transcript", "audio_text"} & set(value["question"])
        assert "bank_id" not in serialized and "state" not in serialized
        value = engine.answer(test_user.id, value["id"], value["question"]["id"], "", True)


def test_start_retry_resumes_and_other_mode_requires_explicit_abandon(db_session, test_user, bank):
    first = engine.start(test_user.id, "quick")
    assert engine.start(test_user.id, "quick") == first
    with pytest.raises(engine.PlacementError, match="active_attempt"):
        engine.start(test_user.id, "detailed")
    engine.abandon(test_user.id, first["id"])
    second = engine.start(test_user.id, "detailed")
    assert second["id"] != first["id"]
    assert PlacementAttempt.query.filter_by(user_id=test_user.id).count() == 2


def test_exact_answer_retry_is_idempotent_and_first_answer_cannot_be_changed(db_session, test_user, bank):
    first = engine.start(test_user.id, "quick")
    args = (test_user.id, first["id"], first["question"]["id"], "Wrong answer", False)
    saved = engine.answer(*args)
    assert engine.answer(*args) == saved
    with pytest.raises(engine.PlacementError, match="answer_already_saved"):
        engine.answer(test_user.id, first["id"], first["question"]["id"], "A correct answer", False)
    assert engine.status(test_user.id)["active"]["answered"] == 1


def test_final_answer_retry_returns_same_completed_result(db_session, test_user, bank):
    value = engine.start(test_user.id, "quick")
    last = None
    while value["status"] == "active":
        last = (test_user.id, value["id"], value["question"]["id"], "", True)
        value = engine.answer(*last)
    assert engine.answer(*last) == value
    assert engine.status(test_user.id)["latest"] == value


def test_draft_survives_reload_but_late_previous_question_draft_cannot_overwrite(db_session, test_user, bank):
    value = engine.start(test_user.id, "quick")
    qid = value["question"]["id"]
    engine.save_draft(test_user.id, value["id"], qid, "Wrong answer")
    db_session.expire_all()
    assert engine.status(test_user.id)["active"]["question"]["draft"] == "Wrong answer"
    saved = engine.answer(test_user.id, value["id"], qid, "Wrong answer", False)
    with pytest.raises(engine.PlacementError, match="stale_question"):
        engine.save_draft(test_user.id, value["id"], qid, "A correct answer")
    assert engine.status(test_user.id)["active"] == saved


@pytest.mark.parametrize(
    "value,unknown",
    [(None, False), ([], False), (True, False), ("", False), ("x", 1), ("x", True), ("x" * 1001, False)],
)
def test_malformed_answers_do_not_advance(db_session, test_user, bank, value, unknown):
    current = engine.start(test_user.id, "quick")
    with pytest.raises(engine.PlacementError):
        engine.answer(test_user.id, current["id"], current["question"]["id"], value, unknown)
    assert engine.status(test_user.id)["active"]["answered"] == 0


def test_text_writing_is_case_and_punctuation_insensitive(db_session, test_user, bank):
    value = engine.start(test_user.id, "detailed")
    while value["status"] == "active":
        typed = value["question"]["input"] == "text"
        value = engine.answer(
            test_user.id,
            value["id"],
            value["question"]["id"],
            "A CORRECT ANSWER!!!" if typed else "A correct answer",
            False,
        )
    assert value["result"]["domains"][-1]["correct"] == 2


def test_owner_boundary_and_incomplete_adoption(db_session, test_user, second_user, bank):
    value = engine.start(test_user.id, "quick")
    with pytest.raises(engine.PlacementError, match="not_found"):
        engine.save_draft(second_user.id, value["id"], value["question"]["id"], "Wrong answer")
    with pytest.raises(engine.PlacementError, match="test_not_completed"):
        engine.adopt_level(test_user.id, value["id"])


def test_new_bank_does_not_change_existing_attempt(db_session, test_user, bank):
    first = engine.start(test_user.id, "quick")
    content = deepcopy(bank.content)
    content["label"] = "A new private bank"
    for q in content["items"]:
        q["prompt"] = "New content"
    bank.active = False
    db_session.add(PlacementBank(id=bank_digest(content), label=content["label"], active=True, content=content))
    db_session.flush()
    assert engine.status(test_user.id)["active"] == first
    value = engine.answer(test_user.id, first["id"], first["question"]["id"], "", True)
    assert value["question"]["prompt"] != "New content"


def test_existing_learner_adoption_is_deferred_and_keeps_today_plan(db_session, test_user, bank):
    test_user.onboarding_level = "A1"
    today = study_day_date_for_tz(test_user.timezone)
    frozen = {"version": 2, "items": [{"id": "existing-course"}]}
    log = DailyPlanLog(user_id=test_user.id, plan_date=today, plan_json=frozen)
    db_session.add(log)
    db_session.flush()
    value = complete(test_user.id)
    adoption = engine.adopt_level(test_user.id, value["id"])
    assert adoption["effective_on"] == (today + timedelta(days=1)).isoformat()
    assert test_user.onboarding_level == "A1"
    assert test_user.placement_pending_level == "C1"
    assert log.plan_json == frozen
    assert engine.adopt_level(test_user.id, value["id"]) == adoption


def test_new_learner_applies_immediately(db_session, test_user, bank):
    test_user.onboarding_completed = False
    value = complete(test_user.id)
    assert engine.adopt_level(test_user.id, value["id"])["effective_on"] is None
    assert test_user.onboarding_level == "C1"
    assert not test_user.onboarding_completed


def test_activation_waits_for_next_study_day_and_postpones_if_learning_started(db_session, test_user, bank):
    today = study_day_date_for_tz(test_user.timezone)
    test_user.onboarding_level = "A1"
    test_user.placement_pending_level = "B1"
    test_user.placement_pending_on = today + timedelta(days=1)
    db_session.flush()
    engine.activate_pending(test_user)
    assert test_user.onboarding_level == "A1"
    test_user.placement_pending_on = today
    db_session.flush()
    with patch("app.utils.activity_tracker.has_learning_activity", return_value=True):
        engine.activate_pending(test_user)
    assert test_user.onboarding_level == "A1"
    assert test_user.placement_pending_on == today + timedelta(days=1)
    test_user.placement_pending_on = today
    db_session.flush()
    with patch("app.utils.activity_tracker.has_learning_activity", return_value=False):
        engine.activate_pending(test_user)
    assert test_user.onboarding_level == "B1"
    assert test_user.placement_pending_level is None
    assert DailyPlanLog.query.filter_by(user_id=test_user.id, plan_date=today).one().plan_json == {
        "placement_rebuild": True
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["items"].pop(),
        lambda p: p["items"][0].update(answers=["not an option"]),
        lambda p: p["items"][0].update(level="C2"),
        lambda p: p["items"][0].update(audio_url="https://untrusted.invalid/x.mp3"),
    ],
)
def test_bank_validation_rejects_incomplete_or_unsafe_content(mutation):
    pack = synthetic_bank()
    mutation(pack)
    with pytest.raises(ValueError):
        validate_bank(pack)


def test_browser_and_bearer_share_attempt_but_cookie_cannot_use_native_mutations(
    authenticated_client, app, db_session, test_user, bank
):
    started = authenticated_client.post("/onboarding/placement/v2/start", json={"mode": "quick"})
    assert started.status_code == 200
    value = started.get_json()["attempt"]
    headers = {
        "Authorization": "Bearer "
        + create_access_token(identity=str(test_user.id), additional_claims={"auth_version": test_user.auth_version()})
    }
    native = app.test_client()
    got = native.get("/api/native/placement/status", headers=headers)
    assert got.get_json()["active"] == value
    assert got.headers["Cache-Control"] == "private, no-store"
    assert authenticated_client.post("/api/native/placement/start", json={"mode": "quick"}).status_code == 401
    response = native.post(
        "/api/native/placement/" + value["id"] + "/answer",
        headers=headers,
        json={"question_id": value["question"]["id"], "answer": "", "dont_know": True},
    )
    assert response.status_code == 200
    assert authenticated_client.get("/onboarding/placement/v2/status").get_json()["active"]["answered"] == 1


def test_browser_start_requires_csrf_when_enabled(authenticated_client, app, bank):
    with patch.dict(app.config, {"WTF_CSRF_ENABLED": True}):
        assert authenticated_client.post("/onboarding/placement/v2/start", json={"mode": "quick"}).status_code == 400


def test_browser_page_is_private_and_exposes_both_choices(authenticated_client, bank):
    response = authenticated_client.get("/placement")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert 'data-mode="quick"' in response.text and 'data-mode="detailed"' in response.text
    assert "getUserMedia" not in response.text


def test_bank_cli_dry_run_is_read_only_and_activation_is_idempotent(app, db_session, tmp_path):
    pack = synthetic_bank()
    path = tmp_path / "private-placement.json"
    path.write_text(json.dumps(pack))
    runner = app.test_cli_runner()
    before = PlacementBank.query.count()
    first = runner.invoke(args=["placement-bank-install", "--pack", str(path)])
    assert first.exit_code == 0, first.output
    assert PlacementBank.query.count() == before
    first = runner.invoke(args=["placement-bank-install", "--pack", str(path), "--apply"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(args=["placement-bank-install", "--pack", str(path), "--apply"])
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["changed"] is False
    assert PlacementBank.query.filter_by(active=True).count() == 1


def test_deferred_floor_explicitly_replaces_rollover_only_before_activity(db_session, test_user):
    from app.daily_plan.snapshot import resolve_snapshot_for_today, SNAPSHOT_VERSION
    from app.utils.db import db

    today = study_day_date_for_tz(test_user.timezone)
    previous = {
        "version": SNAPSHOT_VERSION,
        "date": (today - timedelta(days=1)).isoformat(),
        "items": [{"id": "old-required"}],
    }
    db_session.add(DailyPlanLog(user_id=test_user.id, plan_date=today - timedelta(days=1), plan_json=previous))
    test_user.placement_pending_level = "B1"
    test_user.placement_pending_on = today
    db_session.flush()
    fresh = {"version": SNAPSHOT_VERSION, "date": today.isoformat(), "items": [{"id": "new-level"}]}
    with (
        patch("app.utils.activity_tracker.has_learning_activity", return_value=False),
        patch("app.daily_plan.snapshot._build_fresh_snapshot", return_value=fresh) as build,
    ):
        value = resolve_snapshot_for_today(test_user.id, today, db)
    assert value == fresh
    build.assert_called_once()
    assert test_user.onboarding_level == "B1"


def test_migration_up_and_down_on_empty_sqlite_schema():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.operations import Operations
    from alembic.migration import MigrationContext

    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261124_placement_tests.py"
    spec = importlib.util.spec_from_file_location("placement_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    local = create_engine("sqlite://")
    with local.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {"placement_banks", "placement_attempts"} <= set(inspect(connection).get_table_names())
            migration.downgrade()
        assert inspect(connection).get_table_names() == ["users"]
        assert [c["name"] for c in inspect(connection).get_columns("users")] == ["id"]
    local.dispose()
