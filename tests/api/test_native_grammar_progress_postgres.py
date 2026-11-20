"""Concurrent theory completion is serialized on the isolated PostgreSQL _test DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from threading import Barrier, Event, Lock
from uuid import uuid4

from flask_jwt_extended import create_access_token
import pytest
from sqlalchemy import event
from sqlalchemy.engine import make_url

from app.api.native_grammar_progress import theory_revision
from app.api.native_lessons import _theory
from app.auth.models import User
from app.grammar_lab.models import (
    GrammarAttempt,
    GrammarExercise,
    GrammarTopic,
    UserGrammarExercise,
    UserGrammarTopicStatus,
)
from app.study.models import NativeLearningRun, StudySession
from app.utils.db import db


@pytest.fixture
def postgres_app(request):
    configured = make_url(os.environ.get("DATABASE_URL", "sqlite://"))
    if configured.get_backend_name() == "sqlite":
        pytest.skip("PostgreSQL row-lock concurrency regression")
    if configured.get_backend_name() != "postgresql" or "_test" not in (configured.database or ""):
        pytest.fail("Refusing theory race test outside a named PostgreSQL _test database")
    app = request.getfixturevalue("app")
    assert db.engine.dialect.name == "postgresql" and "_test" in (db.engine.url.database or "")
    assert "_test" in db.session.execute(db.text("SELECT current_database()")).scalar()
    return app


def test_simultaneous_final_slide_posts_award_theory_xp_once(postgres_app):
    app = postgres_app
    key = uuid4().hex
    user = User(username="slide_race_" + key[:20], email=key + "@example.invalid", active=True)
    user.set_password("only-disposable-race-test-password")
    topic = GrammarTopic(
        slug="slide-race-" + key, title="To be", title_ru="Глагол to be", level="A1", content={"rule": "I am; we are."}
    )
    db.session.add_all([user, topic])
    db.session.flush()
    db.session.add(
        GrammarExercise(
            topic_id=topic.id, exercise_type="fill_blank", content={"question": "I ___ here.", "correct_answer": "am"}
        )
    )
    db.session.commit()
    user_id, topic_id = user.id, topic.id
    token = create_access_token(identity=str(user_id), additional_claims={"auth_version": user.auth_version()})
    revision = theory_revision(_theory(topic.content))
    barrier, second_lock_started, mutex = Barrier(2), Event(), Lock()
    lock_requests = 0
    lock_results = 0

    def is_user_lock(statement):
        sql = " ".join(statement.lower().split())
        return "from users " in sql and "for update" in sql

    def before(connection, cursor, statement, parameters, context, executemany):
        nonlocal lock_requests
        if is_user_lock(statement):
            with mutex:
                lock_requests += 1
                if lock_requests == 2:
                    second_lock_started.set()

    def after(connection, cursor, statement, parameters, context, executemany):
        nonlocal lock_results
        if is_user_lock(statement):
            with mutex:
                lock_results += 1
                first = lock_results == 1
            if first:
                # Hold the first real row lock until the second request starts
                # its competing SELECT FOR UPDATE, proving actual overlap.
                assert second_lock_started.wait(10), "Second request did not contend for the user lock"

    def finish():
        with app.test_client() as client:
            barrier.wait(timeout=10)
            response = client.post(
                f"/api/native/grammar/topics/{topic_id}/theory/complete",
                headers={"Authorization": "Bearer " + token},
                json={"theory_revision": revision, "completed": True},
            )
            return response.status_code, response.json

    event.listen(db.engine, "before_cursor_execute", before)
    event.listen(db.engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(finish) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        assert all(code == 200 for code, _ in results), results
        assert sorted(body["xp_earned"] for _, body in results) == [0, 20]
        assert all(
            body["progress"]
            == {"theory_completed": True, "practiced_exercises": 0, "correct_exercises": 0, "total_exercises": 1}
            for _, body in results
        )
        assert lock_requests == lock_results == 2
        status = UserGrammarTopicStatus.query.filter_by(user_id=user_id, topic_id=topic_id).one()
        assert (
            status.theory_completed
            and status.xp_earned == 20
            and status.theory_completed_at <= datetime.now(UTC).replace(tzinfo=None)
        )
        assert all(
            model.query.filter_by(user_id=user_id).count() == 0
            for model in (UserGrammarExercise, GrammarAttempt, NativeLearningRun, StudySession)
        )
    finally:
        event.remove(db.engine, "before_cursor_execute", before)
        event.remove(db.engine, "after_cursor_execute", after)
        db.session.rollback()
        User.query.filter_by(id=user_id).delete(synchronize_session=False)
        GrammarTopic.query.filter_by(id=topic_id).delete(synchronize_session=False)
        db.session.commit()
