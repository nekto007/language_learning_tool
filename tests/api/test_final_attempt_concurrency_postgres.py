"""The retained final POST transports cannot race the rolling attempt cap."""
# ruff: noqa: F811 -- imported pytest fixtures are discovered by name.
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import event

from tests.api.test_quiz_correction_concurrency_postgres import (
    race_course as race_course, postgres_app as postgres_app,
)


@pytest.mark.parametrize("transport", ["form", "json"])
def test_retained_final_posts_serialize_cap_and_attempt_write(race_course, monkeypatch, transport):
    from app.curriculum.models import LessonProgress, LessonAttempt, Lessons
    from app.utils.db import db
    import app.curriculum.routes.grammar_quiz_lessons as forms
    import app.curriculum.routes.lessons as legacy_json
    from app.curriculum.grading import check_final_test_attempts_exhausted

    case = race_course
    lesson = db.session.get(Lessons, case.lesson_id)
    lesson.type = "final_test"
    lesson.content = {"questions": [{"type": "multiple_choice", "question": "I ___ here.",
                                      "options": ["am", "is"], "correct": 0}]}
    progress = LessonProgress(user_id=case.user_id, lesson_id=case.lesson_id, status="in_progress", score=0)
    db.session.add(progress)
    db.session.flush()
    for number in (1, 2):
        db.session.add(LessonAttempt(user_id=case.user_id, lesson_id=case.lesson_id,
                                    lesson_progress_id=progress.id, attempt_number=number,
                                    score=0, passed=False, completed_at=datetime.now(UTC)))
    db.session.commit()

    starts, unprotected_checks = Barrier(2), Barrier(2)
    competing, mutex = Event(), Lock()
    requested = acquired = 0

    def is_lock(statement):
        sql = " ".join(statement.lower().split())
        return "from users " in sql and "for update" in sql

    def before(conn, cursor, statement, parameters, context, executemany):
        nonlocal requested
        if is_lock(statement):
            with mutex:
                requested += 1
                if requested == 2:
                    competing.set()

    def after(conn, cursor, statement, parameters, context, executemany):
        nonlocal acquired
        if is_lock(statement):
            with mutex:
                acquired += 1
                first = acquired == 1
            if first:
                assert competing.wait(10), "The second final POST did not contend for the user lock"

    def checked(*args, **kwargs):
        result = check_final_test_attempts_exhausted(*args, **kwargs)
        if acquired == 0:
            # Deterministic reproduction before the fix: both unprotected
            # requests observe two failures and accept a third attempt.
            unprotected_checks.wait(timeout=10)
        return result

    monkeypatch.setattr(forms, "check_final_test_attempts_exhausted", checked)
    monkeypatch.setattr(legacy_json, "check_final_test_attempts_exhausted", checked)

    def finish():
        with case.app.test_client() as client:
            with client.session_transaction() as session:
                session["_user_id"] = case.session_id
                session["_fresh"] = True
            starts.wait(timeout=10)
            if transport == "form":
                response = client.post(f"/curriculum/lesson/{case.lesson_id}/final_test",
                                       data={"answer_0": "is"}, headers={"X-Requested-With": "XMLHttpRequest"})
            else:
                response = client.post(f"/curriculum/api/lesson/{case.lesson_id}/submit", json={"answers": {"0": "1"}})
            return response.status_code, response.json

    engine = db.engine
    db.session.remove()
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=30) for future in [pool.submit(finish), pool.submit(finish)]]
        assert sorted(code for code, _ in results) == [200, 429], results
        assert requested == acquired == 2
        db.session.remove()
        attempts = LessonAttempt.query.filter_by(user_id=case.user_id, lesson_id=case.lesson_id).all()
        assert len(attempts) == 3 and all(not a.passed for a in attempts)
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
