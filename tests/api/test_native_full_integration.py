"""Real factory/ORM integration without production services or a running PostgreSQL."""

from datetime import datetime, timedelta, UTC
from pathlib import Path
from uuid import uuid4
import importlib.util
import runpy

import pytest
from flask_jwt_extended import create_access_token


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    from app import create_app
    from app.utils.db import db
    from config.settings import Config

    folder = tmp_path_factory.mktemp("native-real-db")

    class NativeConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(folder / "native_test.db")
        WTF_CSRF_ENABLED = True
        RATELIMIT_ENABLED = False
        SERVER_NAME = "localhost"
        MAIL_SUPPRESS_SEND = True

    application = create_app(config_class=NativeConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.engine.dispose()


def learner(app):
    from app.auth.models import User
    from app.utils.db import db

    key = "native_" + uuid4().hex[:12]
    user = User(username=key, email=key + "@example.invalid", active=True)
    user.set_password("only-disposable-local-test-password")
    db.session.add(user)
    db.session.commit()
    token = create_access_token(
        identity=str(user.id), additional_claims={"auth_version": user.auth_version()}
    )
    return user, {"Authorization": "Bearer " + token}


def test_real_grammar_lab_updates_srs_once_and_preserves_receipt(native_app):
    from app.utils.db import db
    from app.grammar_lab.models import (
        GrammarTopic,
        GrammarExercise,
        GrammarAttempt,
        UserGrammarExercise,
    )

    user, headers = learner(native_app)
    client = native_app.test_client()
    topic = GrammarTopic(
        slug="native-" + uuid4().hex[:12],
        title="To be",
        title_ru="Глагол to be",
        level="A1",
        content={"introduction": "I am. You are."},
    )
    db.session.add(topic)
    db.session.flush()
    exercise = GrammarExercise(
        topic_id=topic.id,
        exercise_type="fill_blank",
        content={"question": "I ___ here.", "correct_answer": "am"},
        difficulty=1,
    )
    db.session.add(exercise)
    db.session.commit()
    response = client.post(
        "/api/native/activities/grammar_topic/start",
        headers=headers,
        json={"item_id": f"grammar_topic:{topic.id}", "request_id": str(uuid4())},
    )
    assert response.status_code == 200, response.get_json()
    document = response.get_json()["lesson"]
    assert len(document["questions"]) == 1
    assert "correct_answer" not in document["questions"][0]
    submission = {"session_token": document["session_token"], "answers": {"0": "am"}}
    response = client.post(
        "/api/native/activities/grammar_topic/submit", headers=headers, json=submission
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["correct_count"] == 1
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 1
    progress = UserGrammarExercise.query.filter_by(user_id=user.id, exercise_id=exercise.id).one()
    assert progress.first_reviewed is not None
    before = (progress.state, progress.interval, progress.repetitions)
    repeat = client.post(
        "/api/native/activities/grammar_topic/submit", headers=headers, json=submission
    )
    assert repeat.get_json() == response.get_json()
    db.session.refresh(progress)
    assert (progress.state, progress.interval, progress.repetitions) == before
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 1
    for url in ["/api/native/courses", "/api/native/grammar/topics"]:
        response = client.get(url, headers=headers)
        assert response.status_code == 200, response.get_json()
        assert response.headers["Cache-Control"] == "private, no-store"


def test_real_reader_enforces_rights_owner_monotonic_bookmarks_and_server_clock(native_app):
    from app.utils.db import db
    from app.books.models import Book, Chapter, UserChapterProgress
    from app.books.reading_session import UserReadingSession

    user, headers = learner(native_app)
    other, foreign = learner(native_app)
    client = native_app.test_client()
    book = Book(
        title="Native public-domain test",
        author="Test",
        chapters_cnt=1,
        rights_status="public_domain",
        is_published=True,
    )
    private = Book(
        title="Native licensed test",
        author="Test",
        chapters_cnt=1,
        rights_status="licensed",
        is_published=True,
    )
    db.session.add_all([book, private])
    db.session.flush()
    chapter = Chapter(
        book_id=book.id,
        chap_num=1,
        title="Start",
        words=12,
        text_raw="This is a local integration test.",
    )
    hidden = Chapter(
        book_id=private.id, chap_num=1, title="Restricted", words=1, text_raw="Restricted."
    )
    db.session.add_all([chapter, hidden])
    db.session.commit()
    denied = client.post(
        "/api/native/reading/start", headers=headers, json={"chapter_id": hidden.id}
    )
    assert denied.status_code == 403, denied.get_json()
    chosen = client.post("/api/native/books/select", headers=headers, json={"book_id": book.id})
    assert chosen.status_code == 200, chosen.get_json()
    opened = client.post(
        "/api/native/reading/start", headers=headers, json={"chapter_id": chapter.id}
    )
    assert opened.status_code == 200, opened.get_json()
    sid = opened.get_json()["session_id"]
    for offset in [0.6, 0.2]:
        saved = client.patch(
            "/api/native/reading/progress",
            headers=headers,
            json={"book_id": book.id, "chapter_id": chapter.id, "offset_pct": offset},
        )
        assert saved.status_code == 200, saved.get_json()
        assert saved.get_json()["offset_pct"] == 0.6
    row = db.session.get(UserReadingSession, sid)
    row.started_at = datetime.now(UTC) - timedelta(hours=2)
    db.session.commit()
    refused = client.post(
        "/api/native/reading/end",
        headers=foreign,
        json={"session_id": sid, "current_offset_pct": 0.9},
    )
    assert refused.status_code == 403
    closed = client.post(
        "/api/native/reading/end",
        headers=headers,
        json={"session_id": sid, "current_offset_pct": 0.7},
    )
    assert closed.status_code == 200, closed.get_json()
    assert closed.get_json()["duration_seconds"] == 90
    closed_at = db.session.get(UserReadingSession, sid).ended_at
    again = client.post(
        "/api/native/reading/end",
        headers=headers,
        json={"session_id": sid, "current_offset_pct": 0.95},
    )
    assert again.status_code == 200
    assert db.session.get(UserReadingSession, sid).ended_at == closed_at
    assert (
        UserChapterProgress.query.filter_by(user_id=user.id, chapter_id=chapter.id).one().offset_pct
        == 0.7
    )


def test_real_factory_csrf_registry(native_app):
    policy = runpy.run_path(str(Path(__file__).parents[1] / "security/test_csrf_sweep.py"))
    policy["test_exempt_views_allowlist"](native_app)


def test_native_run_migration_round_trip_and_unique_request():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    path = Path(__file__).parents[2] / "migrations/versions/20261116_native_learning_runs.py"
    spec = importlib.util.spec_from_file_location("native_run_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE study_sessions (id INTEGER PRIMARY KEY)"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        schema = sa.inspect(connection)
        assert "native_learning_runs" in schema.get_table_names()
        assert schema.get_unique_constraints("native_learning_runs")[0]["column_names"] == [
            "user_id",
            "request_id",
        ]
        assert {fk["referred_table"] for fk in schema.get_foreign_keys("native_learning_runs")} == {
            "users",
            "study_sessions",
        }
        module.downgrade()
        assert "native_learning_runs" not in sa.inspect(connection).get_table_names()
    engine.dispose()


def test_plan_deck_quiz_uses_only_owned_decks_and_writes_its_own_completion(
    native_app, monkeypatch
):
    from app.utils.db import db
    from app.study.models import QuizDeck, QuizDeckWord, NativeLearningRun, UserWord, GameScore
    from app.modules.service import ModuleService
    from app.api import native_activities
    import app.daily_plan.linear.xp as xp
    import app.achievements.xp_service as game_xp
    from app.daily_plan.models import DailyPlanEvent

    user, headers = learner(native_app)
    other, _ = learner(native_app)
    client = native_app.test_client()
    monkeypatch.setattr(native_activities, "_guard", lambda *a: None)
    monkeypatch.setattr(ModuleService, "is_module_enabled_for_user", lambda *a: True)
    monkeypatch.setattr(xp, "maybe_award_srs_global_xp", lambda *a, **k: None)
    monkeypatch.setattr(xp, "maybe_award_linear_perfect_day", lambda *a, **k: None)
    monkeypatch.setattr(game_xp, "award_game_xp_idempotent", lambda *a, **k: None)
    deck = QuizDeck(user_id=user.id, title="Owned")
    foreign = QuizDeck(user_id=other.id, title="Foreign")
    db.session.add_all([deck, foreign])
    db.session.flush()
    db.session.add_all(
        [
            QuizDeckWord(deck_id=deck.id, custom_english="book", custom_russian="книга"),
            QuizDeckWord(
                deck_id=foreign.id, custom_english="foreign secret", custom_russian="чужое слово"
            ),
        ]
    )
    db.session.commit()
    response = client.post(
        "/api/native/activities/deck_quiz/start",
        headers=headers,
        json={"item_id": "srs:deck_quiz", "request_id": str(uuid4())},
    )
    assert response.status_code == 200, response.get_json()
    document = response.get_json()["lesson"]
    run = db.session.get(NativeLearningRun, document["id"])
    assert len(run.payload["rows"]) == 1
    row = run.payload["rows"][0]
    assert row["word_id"] is None
    assert "foreign secret" not in str(document) and "чужое слово" not in str(document)
    answer = row.get("answer") or row.get("correct_answer")
    if row.get("options"):
        answer = str(row["options"].index(answer))
    submission = {"session_token": document["session_token"], "answers": {"0": answer}}
    result = client.post(
        "/api/native/activities/deck_quiz/submit", headers=headers, json=submission
    )
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["correct_count"] == 1
    assert (
        DailyPlanEvent.query.filter_by(user_id=user.id, event_type="deck_quiz_completed").count()
        == 1
    )
    assert GameScore.query.filter_by(user_id=user.id, game_type="quiz").count() == 1
    assert UserWord.query.filter_by(user_id=user.id).count() == 0
    repeated = client.post(
        "/api/native/activities/deck_quiz/submit", headers=headers, json=submission
    )
    assert repeated.get_json() == result.get_json()
    assert (
        DailyPlanEvent.query.filter_by(user_id=user.id, event_type="deck_quiz_completed").count()
        == 1
    )
    assert GameScore.query.filter_by(user_id=user.id).count() == 1


def test_completed_course_does_not_shadow_active_challenge_target(native_app, monkeypatch):
    from flask import g
    from app.api.native_lessons import _guard_plan
    import app.daily_plan.service as plans
    import app.achievements.streak_service as streaks
    import app.telegram.queries as summaries
    import app.utils.time_utils as times

    user, _ = learner(native_app)
    course = {
        "id": "curriculum:42",
        "kind": "curriculum",
        "completed": True,
        "data": {"lesson_id": 42},
    }
    challenge = {
        "id": "challenge:5",
        "kind": "challenge",
        "completed": False,
        "data": {"lesson_id": 42},
    }
    monkeypatch.setattr(
        plans,
        "get_daily_plan_unified",
        lambda *a, **k: {"required": [course], "optional": [challenge], "day_secured": True},
    )
    monkeypatch.setattr(streaks, "compute_plan_steps", lambda *a, **k: ({}, 0, 0))
    monkeypatch.setattr(summaries, "get_daily_summary", lambda *a, **k: {})
    monkeypatch.setattr(times, "get_user_timezone_name", lambda *a, **k: "UTC")
    with native_app.test_request_context("/api/native/lessons/42"):
        g._login_user = user
        assert _guard_plan(42) == "challenge"


def test_actual_authored_card_deck_completes_without_fabricating_dictionary_entries(
    native_app, monkeypatch
):
    from app.utils.db import db
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress, LessonAttempt
    from app.study.models import UserWord
    from app.api import native_cards
    import app.curriculum.security as security
    import app.srs.counting as counting
    import app.daily_plan.linear.xp as xp

    user, headers = learner(native_app)
    client = native_app.test_client()
    level = CEFRLevel(code="X1", name="Isolated test")
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title="Local card course")
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="One authored card",
        type="flashcards",
        min_cards_required=10,
        content={"cards": [{"front": "unlisted native test word", "back": "пример перевода"}]},
    )
    db.session.add(lesson)
    db.session.commit()
    monkeypatch.setattr(native_cards, "_guard_plan", lambda *a: None)
    monkeypatch.setattr(security, "check_lesson_access", lambda *a: True)
    monkeypatch.setattr(counting, "get_new_card_budget", lambda *a: (0, 0))
    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", lambda *a, **k: None)
    response = client.post(
        f"/api/native/lessons/{lesson.id}/cards/session",
        headers=headers,
        json={"request_id": str(uuid4())},
    )
    assert response.status_code == 200, response.get_json()
    run = response.get_json()
    assert run["card"]["front"] == "unlisted native test word"
    submission = {"session_id": run["session_id"], "step": run["step"], "rating": 3}
    result = client.post(
        f"/api/native/lessons/{lesson.id}/cards/grade", headers=headers, json=submission
    )
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["lesson_complete"] is True
    assert (
        LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).one().status
        == "completed"
    )
    assert LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson.id).count() == 1
    assert UserWord.query.filter_by(user_id=user.id).count() == 0
    again = client.post(
        f"/api/native/lessons/{lesson.id}/cards/grade", headers=headers, json=submission
    )
    assert again.get_json() == result.get_json()
    assert LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson.id).count() == 1


def test_shared_deck_quiz_srs_can_join_the_native_atomic_transaction(native_app):
    from flask import g
    from app.utils.db import db
    from app.words.models import CollectionWords
    from app.study.models import UserWord, UserCardDirection
    from app.study.game_routes import _grade_quiz_answer
    user,_=learner(native_app)
    word=CollectionWords(english_word='native atomic '+uuid4().hex[:10],russian_word='проверка',get_download=0)
    db.session.add(word);db.session.flush()
    owned=UserWord.get_or_create(user.id,word.id)
    card=UserCardDirection.get_or_create(owned.id,'eng-rus',source='native_test')
    card.state='review';card.interval=4;card.first_reviewed=datetime.now(UTC)-timedelta(days=10);card.repetitions=2
    db.session.commit();card_id=card.id;word_id=word.id
    with native_app.test_request_context('/api/native/activities/deck_quiz/submit'):
        g._login_user=user
        assert _grade_quiz_answer(word_id,'eng_to_rus',True,commit=False)
        assert db.session.get(UserCardDirection,card_id).repetitions>2
        db.session.rollback()
        assert db.session.get(UserCardDirection,card_id).repetitions==2
        assert _grade_quiz_answer(word_id,'eng_to_rus',True)
        db.session.rollback()
        assert db.session.get(UserCardDirection,card_id).repetitions>2
