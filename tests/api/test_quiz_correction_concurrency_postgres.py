"""Exercise actual row-lock contention for first-round and correction receipts.

Only the disposable local PostgreSQL test database is used. Content/access and
XP projection are isolated so these tests measure transaction semantics rather
than the current daily-plan fixture.
"""
# ruff: noqa: F811 -- imported pytest fixtures are discovered by name.
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from tests.api.test_native_full_integration import learner
from tests.api.test_native_grammar_progress_postgres import postgres_app as postgres_app


@pytest.fixture
def race_course(postgres_app, monkeypatch):
    from app.api import native_lessons
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.utils.db import db
    import app.curriculum.security as security
    import app.daily_plan.linear.xp as xp

    user, headers = learner(postgres_app)
    user.onboarding_completed = True
    user.last_login = datetime.now(UTC)
    # CEFRLevel.code has a two-character limit on PostgreSQL.
    from tests.conftest import unique_level_code
    level = CEFRLevel(code=unique_level_code(), name="Isolated race", order=10000)
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title="Race")
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(module_id=module.id, number=1, type="grammar", title="To be", content={
        "description": "Use am with I and are with we.",
        "exercises": [
            {"type": "fill_blank", "question": "I ___ here.", "answer": "am"},
            {"type": "fill_blank", "question": "We ___ here.", "answer": "are"},
        ],
    })
    db.session.add(lesson)
    db.session.commit()
    monkeypatch.setattr(native_lessons, "_guard_plan", lambda *a: "curriculum")
    monkeypatch.setattr(security, "check_lesson_access", lambda *a: True)
    awards = []
    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", lambda *a, **kw: awards.append(kw["score"]))
    case = SimpleNamespace(app=postgres_app, user_id=user.id, lesson_id=lesson.id,
                           level_id=level.id, module_id=module.id, session_id=user.get_id(),
                           headers=headers, awards=awards)
    yield case
    from app.auth.models import User
    db.session.remove()
    User.query.filter_by(id=case.user_id).delete(synchronize_session=False)
    Lessons.query.filter_by(id=case.lesson_id).delete(synchronize_session=False)
    Module.query.filter_by(id=case.module_id).delete(synchronize_session=False)
    CEFRLevel.query.filter_by(id=case.level_id).delete(synchronize_session=False)
    db.session.commit()


def document(case):
    response = case.app.test_client().get(
        f"/api/native/lessons/{case.lesson_id}?quiz_flow=deferred_v1", headers=case.headers)
    assert response.status_code == 200, response.json
    return response.json["lesson"]


def post(case, token, answers):
    return case.app.test_client().post(
        f"/api/native/lessons/{case.lesson_id}/submit", headers=case.headers,
        json={"session_token": token, "answers": answers})


def contend(case, tokens, answers):
    """Block the first real lock until the second SQL lock starts competing."""
    from app.utils.db import db
    barrier, competing, mutex = Barrier(2), Event(), Lock()
    requested = acquired = 0

    def user_lock(statement):
        sql = " ".join(statement.lower().split())
        return "from users " in sql and "for update" in sql

    def before(conn, cursor, statement, parameters, context, executemany):
        nonlocal requested
        if user_lock(statement):
            with mutex:
                requested += 1
                if requested == 2:
                    competing.set()

    def after(conn, cursor, statement, parameters, context, executemany):
        nonlocal acquired
        if user_lock(statement):
            with mutex:
                acquired += 1
                first = acquired == 1
            if first:
                assert competing.wait(10), "No second competing PostgreSQL row lock"

    def submit(token):
        barrier.wait(timeout=10)
        response = post(case, token, answers)
        return response.status_code, response.json

    engine = db.engine
    db.session.remove()
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, token) for token in tokens]
            results = [future.result(timeout=30) for future in futures]
        assert requested == acquired == 2
        return results
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


@pytest.mark.parametrize("phase", ["first", "correction"])
@pytest.mark.parametrize("same_nonce", [True, False])
def test_competing_submissions_preserve_one_independent_attempt(race_course, phase, same_nonce):
    from app.curriculum.models import LessonAttempt, LessonProgress
    from app.utils.db import db
    case = race_course
    if phase == "correction":
        result = post(case, document(case)["session_token"], {"0": "is", "1": "are"})
        assert result.status_code == 200 and result.json["correction_pending"], result.json
    first = document(case)
    assert first["quiz_phase"] == phase
    second = first if same_nonce else document(case)
    answers = {"0": "am"} if phase == "correction" else {"0": "is", "1": "are"}
    results = contend(case, [first["session_token"], second["session_token"]], answers)
    if same_nonce:
        assert results[0] == results[1] and results[0][0] == 200, results
    else:
        assert sorted(code for code, _ in results) == [200, 409], results
        assert next(body for code, body in results if code == 409)["error"] == "lesson_changed"
    db.session.remove()
    progress = LessonProgress.query.filter_by(user_id=case.user_id, lesson_id=case.lesson_id).one()
    attempts = LessonAttempt.query.filter_by(user_id=case.user_id, lesson_id=case.lesson_id).all()
    assert len(attempts) == 1 and attempts[0].score == 50
    assert progress.last_score == progress.best_score == 50
    state = progress.data["quiz_correction"]
    assert state["first_score"] == 50 and state["first_answers"] == {"0": "is", "1": "are"}
    assert state["status"] == ("completed" if phase == "correction" else "pending")
    assert case.awards == ([50] if phase == "correction" else [])
