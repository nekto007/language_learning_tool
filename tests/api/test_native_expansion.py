"""Native expansion contracts: actual JWT/CSRF, graders and SQLite transactions."""

import json
from copy import deepcopy
from datetime import datetime, UTC
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from flask_login import LoginManager, UserMixin
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON, func
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()


class Account(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    xp = Column(Integer, default=0)


class Progress(Base):
    __tablename__ = "lesson_progress"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    lesson_id = Column(Integer)
    status = Column(String)
    data = Column(JSON)
    started_at = Column(DateTime)
    last_activity = Column(DateTime)
    completed_at = Column(DateTime)
    score = Column(Float)
    best_score = Column(Float)
    last_score = Column(Float)


class Attempt(Base):
    __tablename__ = "lesson_attempts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    lesson_id = Column(Integer)
    lesson_progress_id = Column(Integer)
    attempt_number = Column(Integer)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    score = Column(Float)
    passed = Column(Boolean)
    correct_answers = Column(Integer)
    total_questions = Column(Integer)
    mistakes = Column(JSON)


class Study(Base):
    __tablename__ = "study_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    session_type = Column(String)
    word_set_id = Column(Integer)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    words_studied = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)
    incorrect_answers = Column(Integer, default=0)

    def complete_session(self):
        self.end_time = datetime.now()


class CardsRun(Base):
    __tablename__ = "native_srs_state"
    user_id = Column(Integer, primary_key=True)
    session_id = Column(Integer)
    study_day = Column(String)
    state = Column(JSON)
    updated_at = Column(DateTime)


class ActivityRun(Base):
    __tablename__ = "native_learning_runs"
    session_id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    request_id = Column(String)
    kind = Column(String)
    payload = Column(JSON)
    response = Column(JSON)
    created_at = Column(DateTime)


class Learner(UserMixin):
    id = 7
    active = True
    is_admin = False

    @property
    def is_active(self):
        return self.active

    def has_auth_version(self, value):
        return value == 1


@pytest.fixture
def c(monkeypatch):
    from app import csrf
    from app.api import (
        native_lessons as lessons,
        native_cards as cards,
        native_srs as srs,
        native_activities as activities,
        native_reading as reading,
        decorators,
    )
    from app.utils.db import db
    import app.auth.models as auth
    import app.curriculum.models as curriculum
    import app.study.models as study
    import app.curriculum.grading as grading
    import app.curriculum.services.progress_service as progress_service
    import app.daily_plan.linear.xp as xp
    import app.curriculum.listening_service as listening
    import app.curriculum.routes.lessons as routes
    import app.daily_plan.linear.errors as errors
    import app.daily_plan.challenge as challenge

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(bind=engine))
    for cls in (Account, Progress, Attempt, Study, CardsRun, ActivityRun):
        cls.query = session.query_property()
    Progress.record_score = curriculum.LessonProgress.record_score
    monkeypatch.setattr(db, "session", session)
    for module, name, value in [
        (auth, "User", Account),
        (curriculum, "LessonProgress", Progress),
        (curriculum, "LessonAttempt", Attempt),
        (study, "StudySession", Study),
        (study, "NativeSRSState", CardsRun),
        (study, "NativeLearningRun", ActivityRun),
    ]:
        monkeypatch.setattr(module, name, value, raising=False)

    def create_attempt(uid, lid, pid):
        row = Attempt(
            user_id=uid,
            lesson_id=lid,
            lesson_progress_id=pid,
            attempt_number=(
                session.query(func.max(Attempt.attempt_number))
                .filter_by(user_id=uid, lesson_id=lid)
                .scalar()
                or 0
            )
            + 1,
        )
        session.add(row)
        return row

    monkeypatch.setattr(Attempt, "create_attempt", create_attempt, raising=False)
    session.add(Account(id=7))
    session.commit()
    user = Learner()
    monkeypatch.setattr(decorators, "db_get_user", lambda uid: user if uid == 7 else None)
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="native-contract-signing-test-only",
        JWT_SECRET_KEY="native-auth-signing-test-only-32-chars",
        WTF_CSRF_ENABLED=True,
        RATELIMIT_ENABLED=False,
    )
    csrf.init_app(app)
    JWTManager(app)
    login = LoginManager(app)
    login.user_loader(lambda key: user if key == "7" else None)
    for bp in (
        lessons.api_native_lessons,
        cards.api_native_cards,
        activities.api_native_activities,
        reading.api_native_reading,
    ):
        app.register_blueprint(bp, url_prefix="/api/native")
    with app.app_context():
        token = create_access_token(identity="7", additional_claims={"auth_version": 1})
    lesson = SimpleNamespace(
        id=42,
        type="sentence_completion",
        title="Native lesson",
        content={"items": [{"prompt": "I", "answer": "am here."}]},
        module=SimpleNamespace(level=SimpleNamespace(code="A1")),
        module_id=1,
        collection_id=None,
        number=1,
        min_cards_required=10,
        content_version=1,
    )
    lookup = lambda lid: (
        lesson,
        session.query(Progress).filter_by(user_id=7, lesson_id=42).first(),
    )
    monkeypatch.setattr(lessons, "_lesson_and_progress", lookup)
    monkeypatch.setattr(cards, "_lesson", lookup)
    monkeypatch.setattr(lessons, "_guard_plan", lambda *a: None)
    # This fixture replaces progress/account persistence with a tiny schema;
    # module-reference lookup belongs to the real ORM integration fixtures.
    monkeypatch.setattr("app.grammar_lab.guided_learning.lesson_reference", lambda *a: [])
    monkeypatch.setattr(cards, "_guard_plan", lambda *a: None)
    monkeypatch.setattr(activities, "_guard", lambda *a: None)
    monkeypatch.setattr(srs, "_day", lambda: "2026-11-16")
    monkeypatch.setattr(activities, "_day", lambda: "2026-11-16")
    monkeypatch.setattr(progress_service, "_invalidate_user_progress_cache", lambda *a: None)

    def award(uid, *args, **kwargs):
        session.get(Account, uid).xp += 25
        return SimpleNamespace(xp_awarded=25)

    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", award)
    monkeypatch.setattr(xp, "maybe_award_listening_xp", lambda *a, **k: None)
    monkeypatch.setattr(xp, "maybe_award_writing_xp", lambda *a, **k: None)
    monkeypatch.setattr(xp, "maybe_award_grammar_review_xp", lambda *a, **k: None)
    monkeypatch.setattr(xp, "maybe_award_error_review_xp", lambda *a, **k: None)
    monkeypatch.setattr(challenge, "maybe_auto_complete_challenge", lambda *a, **k: None)
    monkeypatch.setattr(errors, "log_quiz_errors_from_result", lambda *a, **k: [])
    monkeypatch.setattr(grading, "check_final_test_attempts_exhausted", lambda *a, **k: None)
    monkeypatch.setattr(routes, "_count_writing_attempts_today", lambda *a: 0)
    monkeypatch.setattr(routes, "_count_pronunciation_attempts_today", lambda *a: 0)
    telemetry = []
    monkeypatch.setattr(
        listening, "log_listening_attempt", lambda *a: telemetry.append(("listening", a[2]))
    )
    monkeypatch.setattr(
        listening,
        "log_pronunciation_attempt",
        lambda *a: telemetry.append(("speech", a[1], a[2], a[3])),
    )
    monkeypatch.setattr(
        curriculum, "save_writing_attempt", lambda *a, **k: telemetry.append(("writing", a[2]))
    )
    import app.utils.languagetool as lt

    monkeypatch.setattr(lt, "check_text", lambda *a: None)
    yield SimpleNamespace(
        app=app,
        client=app.test_client(),
        headers={"Authorization": "Bearer " + token},
        db=session,
        lesson=lesson,
        user=user,
        lessons=lessons,
        cards=cards,
        activities=activities,
        reading=reading,
        telemetry=telemetry,
    )
    session.remove()
    engine.dispose()


def fetch(c):
    r = c.client.get("/api/native/lessons/42", headers=c.headers)
    assert r.status_code == 200, r.data
    return r.json["lesson"]


def submit(c, doc, answers):
    return c.client.post(
        "/api/native/lessons/42/submit",
        headers=c.headers,
        json={"session_token": doc["session_token"], "answers": answers},
    )


@pytest.mark.parametrize(
    "kind,content,answers,score",
    [
        (
            "sentence_completion",
            {"items": [{"prompt": "I", "answer": "am here."}]},
            {"0": "am here."},
            100,
        ),
        (
            "sentence_correction",
            {"incorrect_sentence": "He are here.", "correct_sentence": "He is here."},
            {"0": "He is here."},
            100,
        ),
        ("translation", {"russian": "Я здесь.", "english": "I am here."}, {"0": "I am here."}, 100),
        (
            "ordering_quiz",
            {
                "exercises": [
                    {"type": "ordering", "words": ["here", "am", "I"], "correct": "I am here"}
                ]
            },
            {"0": '["2","1","0"]'},
            100,
        ),
        (
            "dialogue_completion_quiz",
            {
                "exercises": [
                    {
                        "type": "dialogue_completion",
                        "dialogue": "A: Hi. B: ___",
                        "options": ["Bye", "Hello"],
                        "correct": "Hello",
                    }
                ]
            },
            {"0": "1"},
            100,
        ),
        (
            "listening_quiz",
            {
                "exercises": [
                    {
                        "type": "listening_choice",
                        "question": "What?",
                        "audio": "[sound:test.mp3]",
                        "options": ["Yes", "No"],
                        "correct": 0,
                    }
                ]
            },
            {"0": "0"},
            100,
        ),
        (
            "audio_fill_blank",
            {
                "audio_url": "/static/audio/a.mp3",
                "items": [
                    {"text_with_gap": "I ___ here.", "answer": "am", "options": ["am", "is"]}
                ],
            },
            {"0": "0"},
            100,
        ),
        (
            "dictation",
            {"audio_url": "/static/audio/a.mp3", "transcript": "I am here."},
            {"0": "I am here."},
            100,
        ),
        (
            "dictation",
            {
                "audio_url": "/static/audio/a.mp3",
                "transcript": "I am here.",
                "gap_text": "I {0} here.",
                "gaps": [{"index": 0, "answer": "am", "hint": "a"}],
            },
            {"0": "am"},
            100,
        ),
        (
            "collocation_matching",
            {
                "pairs": [
                    {"phrase": "have breakfast", "translation": "завтракать"},
                    {"phrase": "go home", "translation": "идти домой"},
                ]
            },
            {"0": '{"0":"0","1":"1"}'},
            100,
        ),
        (
            "final_test",
            {
                "test_sections": [
                    {
                        "title": "Grammar",
                        "exercises": [
                            {
                                "type": "fill_blank",
                                "question": "I ___ here.",
                                "options": ["am", "is"],
                                "correct": "am",
                            }
                        ],
                    }
                ]
            },
            {"0": "0"},
            100,
        ),
    ],
)
def test_extended_objective_lessons_grade_and_persist(c, kind, content, answers, score):
    c.lesson.type = kind
    c.lesson.content = content
    doc = fetch(c)
    assert all(
        not (
            set(q)
            & {"answer", "correct", "correct_answer", "transcript", "explanation", "evidence"}
        )
        for q in doc["questions"]
    )
    response = submit(c, doc, answers)
    assert response.status_code == 200, response.data
    assert response.json["score"] == score and response.json["completed"]
    assert c.db.query(Progress).one().status == "completed"
    assert c.db.query(Attempt).count() == 1
    again = submit(c, doc, answers)
    assert again.json == response.json and c.db.query(Attempt).count() == 1
    assert c.db.get(Account, 7).xp == 25


@pytest.mark.parametrize(
    "kind,content,answers",
    [
        (
            "shadow_reading",
            {"text": "I am here.", "audio_url": "/static/audio/a.mp3"},
            {"0": "confirmed"},
        ),
        ("listening_immersion", {"text": "I am here.", "audio": "a.mp3"}, {"0": "confirmed"}),
        (
            "idiom",
            {
                "items": [
                    {"phrase": "take a seat", "meaning": "садиться", "example": "Take a seat."}
                ]
            },
            {"0": "confirmed"},
        ),
        (
            "pronunciation",
            {"items": [{"word": "three"}]},
            {"0": '{"recognized":"three","self_assessed":false}'},
        ),
        (
            "writing_prompt",
            {"prompt": "Introduce yourself", "min_words": 2, "checklist": ["Greeting", "Name"]},
            {"0": '{"text":"Hello. I am Anna.","checked":["Greeting","Name"]}'},
        ),
    ],
)
def test_self_assessment_and_writing_do_not_invent_an_exam_score(c, kind, content, answers):
    c.lesson.type = kind
    c.lesson.content = content
    response = submit(c, fetch(c), answers)
    assert response.status_code == 200, response.data
    assert response.json["score"] is None and response.json["completed"]
    assert c.db.query(Progress).one().status == "completed"
    assert c.db.query(Attempt).count() == 0


def test_writing_missing_checks_saves_attempt_without_completion(c):
    c.lesson.type = "writing_prompt"
    c.lesson.content = {
        "prompt": "Introduce yourself",
        "min_words": 2,
        "checklist": ["Greeting", "Name"],
    }
    response = submit(c, fetch(c), {"0": json.dumps({"text": "Hello. I am Anna.", "checked": []})})
    assert response.status_code == 200 and not response.json["completed"]
    assert c.db.query(Progress).one().status == "in_progress"
    assert c.db.get(Account, 7).xp == 0
    assert c.telemetry[0][0] == "writing"


def test_failed_storage_rolls_back_progress_attempt_and_xp(c, monkeypatch):
    doc = fetch(c)
    commit = c.db.commit
    monkeypatch.setattr(c.db, "commit", Mock(side_effect=RuntimeError("storage failed")))
    response = submit(c, doc, {"0": "am here."})
    assert response.status_code == 500
    c.db.expire_all()
    assert c.db.query(Progress).count() == c.db.query(Attempt).count() == 0
    assert c.db.get(Account, 7).xp == 0
    monkeypatch.setattr(c.db, "commit", commit)
    assert submit(c, doc, {"0": "am here."}).json["completed"]


def test_failed_reading_comprehension_records_real_accuracy_but_completes_practice(c):
    c.lesson.type = "reading"
    c.lesson.content = {
        "text": "I am here.",
        "exercises": [
            {
                "type": "multiple_choice",
                "question": "Where?",
                "options": ["Here", "Away"],
                "correct": 0,
            }
        ],
    }
    r = submit(c, fetch(c), {"0": "1"})
    assert r.status_code == 200, r.data
    assert r.json["score"] == 0 and r.json["completed"] and not r.json["passed"]
    assert c.db.query(Attempt).one().score == 0


def test_translation_review_requires_server_proof_and_can_complete_without_false_grade(c):
    c.lesson.type = "translation"
    c.lesson.content = {
        "mode": "rubric",
        "items": [{"russian": "Я здесь.", "english": "I am here."}],
    }
    doc = fetch(c)
    value = {"text": "I am right here.", "reviewed": True}
    assert submit(c, doc, {"0": json.dumps(value)}).status_code == 409
    body = {"session_token": doc["session_token"], "index": 0, "answer": value["text"]}
    r = c.client.post("/api/native/lessons/42/review", headers=c.headers, json=body)
    assert r.status_code == 200 and r.json["status"] == "needs_review"
    body.update(review_token=r.json["review_token"], confirm=True)
    r = c.client.post("/api/native/lessons/42/review", headers=c.headers, json=body)
    assert r.json["status"] == "self_reviewed"
    value["review_token"] = r.json["review_token"]
    response = submit(c, doc, {"0": json.dumps(value)})
    assert response.status_code == 200, response.data
    assert response.json["score"] is None and response.json["completed"]


@pytest.mark.parametrize(
    "route,body,method",
    [
        ("/books/select", {"book_id": 1}, "post"),
        ("/reading/progress", {"book_id": 1, "chapter_id": 1, "offset_pct": 0.5}, "patch"),
        ("/reading/start", {"chapter_id": 1}, "post"),
        ("/reading/end", {"session_id": 1, "current_offset_pct": 0.5}, "post"),
        (
            "/activities/grammar_topic/start",
            {"request_id": str(uuid4()), "item_id": "grammar_topic:1"},
            "post",
        ),
        ("/activities/grammar_topic/submit", {"session_token": "invalid", "answers": {}}, "post"),
        ("/lessons/42/cards/session", {"request_id": str(uuid4())}, "post"),
        ("/lessons/42/cards/grade", {"session_id": 1, "step": 0, "rating": 3}, "post"),
        (
            "/lessons/42/review",
            {"session_token": "invalid", "index": 0, "answer": "I am here."},
            "post",
        ),
    ],
)
def test_all_new_mutations_reject_cookie_only_and_invalid_bearer(c, route, body, method):
    with c.client.session_transaction() as value:
        value["_user_id"] = "7"
    call = getattr(c.client, method)
    assert call("/api/native" + route, json=body).status_code == 401
    assert (
        call(
            "/api/native" + route, json=body, headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )


def test_cards_finish_once_from_server_queue_and_cannot_submit_client_score(c, monkeypatch):
    c.lesson.type = "card"
    c.lesson.content = {"cards": []}
    monkeypatch.setattr(
        c.cards,
        "_queue",
        lambda l: [
            {
                "word_id": 10001,
                "direction": "eng-rus",
                "front": "book",
                "back": "книга",
                "examples": "A book.",
                "state": "new",
                "revision": None,
                "display_only": True,
                "key": "display:1",
                "audio_url": None,
            }
        ],
    )
    r = c.client.post(
        "/api/native/lessons/42/cards/session", headers=c.headers, json={"request_id": str(uuid4())}
    )
    assert r.status_code == 200, r.data
    body = {"session_id": r.json["session_id"], "step": 0, "rating": 3}
    forged = c.client.post(
        "/api/native/lessons/42/cards/grade", headers=c.headers, json={**body, "score": 100}
    )
    assert forged.status_code == 400
    r = c.client.post("/api/native/lessons/42/cards/grade", headers=c.headers, json=body)
    assert r.status_code == 200, r.data
    assert r.json["lesson_complete"] and c.db.query(Progress).one().status == "completed"
    again = c.client.post("/api/native/lessons/42/cards/grade", headers=c.headers, json=body)
    assert again.json == r.json and c.db.query(Attempt).count() == 1
    assert c.db.get(Account, 7).xp == 25


class GameResult(Base):
    __tablename__ = "game_scores"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    game_type = Column(String)
    score = Column(Integer)
    time_taken = Column(Integer)
    correct_answers = Column(Integer)
    total_questions = Column(Integer)
    date_achieved = Column(DateTime)


class SetResult(Base):
    __tablename__ = "word_set_quiz_results"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    set_id = Column(Integer)
    total_questions = Column(Integer)
    correct_answers = Column(Integer)
    score_percentage = Column(Float)
    time_taken = Column(Integer)
    completed_at = Column(DateTime)


def _activity_setup(c, monkeypatch):
    import app.study.models as study
    import app.achievements.xp_service as xp

    monkeypatch.setattr(study, "WordSetQuizResult", SetResult)
    monkeypatch.setattr(study, "GameScore", GameResult)
    payload = {
        "rows": [
            {
                "type": "multiple_choice",
                "question": "book",
                "options": ["книга", "дом"],
                "answer": 0,
            }
        ],
        "source": {"set_id": 5},
        "theory": [],
        "title": "Books",
        "level": "A1",
        "item_id": "word_set_quiz:books",
        "day": "2026-11-16",
    }
    monkeypatch.setattr(c.activities, "_prepare", lambda *a: deepcopy(payload))

    def award(uid, sid, source, amount, day):
        c.db.get(Account, uid).xp += amount
        return SimpleNamespace(xp_awarded=amount)

    monkeypatch.setattr(xp, "award_game_xp_idempotent", award)
    return payload


def test_activity_is_selected_on_server_and_replayed_once(c, monkeypatch):
    _activity_setup(c, monkeypatch)
    body = {"item_id": "word_set_quiz:books", "request_id": str(uuid4())}
    r = c.client.post("/api/native/activities/word_set_quiz/start", headers=c.headers, json=body)
    assert r.status_code == 200, r.data
    doc = r.json["lesson"]
    assert not (set(doc["questions"][0]) & {"answer", "correct", "correct_answer"})
    repeated = c.client.post(
        "/api/native/activities/word_set_quiz/start", headers=c.headers, json=body
    )
    assert repeated.json["lesson"]["id"] == doc["id"] and c.db.query(ActivityRun).count() == 1
    submission = {"session_token": doc["session_token"], "answers": {"0": "0"}}
    r = c.client.post(
        "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
    )
    assert r.status_code == 200, r.data
    assert r.json["completed"] and c.db.query(SetResult).count() == 1
    assert c.db.get(Account, 7).xp == 30
    repeated = c.client.post(
        "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
    )
    assert (
        repeated.json == r.json
        and c.db.query(SetResult).count() == 1
        and c.db.get(Account, 7).xp == 30
    )


def test_activity_storage_failure_rolls_back_result_and_xp(c, monkeypatch):
    _activity_setup(c, monkeypatch)
    body = {"item_id": "word_set_quiz:books", "request_id": str(uuid4())}
    doc = c.client.post(
        "/api/native/activities/word_set_quiz/start", headers=c.headers, json=body
    ).json["lesson"]
    submission = {"session_token": doc["session_token"], "answers": {"0": "0"}}
    commit = c.db.commit
    monkeypatch.setattr(c.db, "commit", Mock(side_effect=RuntimeError("fail")))
    r = c.client.post(
        "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
    )
    assert r.status_code == 500
    c.db.expire_all()
    assert c.db.query(SetResult).count() == 0 and c.db.get(Account, 7).xp == 0
    assert (
        c.db.query(ActivityRun).one().response is None and c.db.query(Study).one().end_time is None
    )
    monkeypatch.setattr(c.db, "commit", commit)
    assert c.client.post(
        "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
    ).json["completed"]


def test_activity_rejects_changed_day_and_foreign_seal(c, monkeypatch):
    _activity_setup(c, monkeypatch)
    doc = c.client.post(
        "/api/native/activities/word_set_quiz/start",
        headers=c.headers,
        json={"item_id": "word_set_quiz:books", "request_id": str(uuid4())},
    ).json["lesson"]
    submission = {"session_token": doc["session_token"], "answers": {"0": "0"}}
    monkeypatch.setattr(c.activities, "_day", lambda: "2026-11-17")
    assert (
        c.client.post(
            "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
        ).status_code
        == 409
    )
    with c.app.app_context():
        submission["session_token"] = c.activities._signer().dumps(
            {"user": 8, "kind": "word_set_quiz", "session": doc["id"], "day": "2026-11-17"}
        )
    assert (
        c.client.post(
            "/api/native/activities/word_set_quiz/submit", headers=c.headers, json=submission
        ).status_code
        == 403
    )
    assert c.db.query(SetResult).count() == 0


@pytest.mark.parametrize(
    "route,method,body",
    [
        ("/books/select", "post", {"book_id": True}),
        ("/books/select", "post", {"book_id": -1}),
        ("/reading/start", "post", {"chapter_id": False}),
        ("/reading/start", "post", {"chapter_id": "1"}),
        ("/reading/end", "post", {"session_id": 1, "current_offset_pct": float("nan")}),
        ("/reading/end", "post", {"session_id": 1, "current_offset_pct": float("inf")}),
        ("/reading/end", "post", {"session_id": 1, "current_offset_pct": 1.5}),
        ("/reading/progress", "patch", {"book_id": 1, "chapter_id": 1, "offset_pct": True}),
        (
            "/reading/progress",
            "patch",
            {"book_id": 1, "chapter_id": 1, "offset_pct": 0.5, "seconds": 99999},
        ),
    ],
)
def test_reading_native_input_cannot_forge_time_or_invalid_ids(c, route, method, body):
    assert (
        getattr(c.client, method)("/api/native" + route, headers=c.headers, json=body).status_code
        == 400
    )


def test_reading_end_adapter_requires_owner_core_and_caps_one_window(c, monkeypatch):
    import app.books.api as books_api

    called = []

    def close(body, **kwargs):
        called.append((body, kwargs))
        return {"success": True}

    monkeypatch.setattr(books_api, "close_reading_session_response", close, raising=False)
    r = c.client.post(
        "/api/native/reading/end",
        headers=c.headers,
        json={"session_id": 9, "current_offset_pct": 0.5},
    )
    assert r.status_code == 200
    assert called == [({"session_id": 9, "current_offset_pct": 0.5}, {"max_duration_seconds": 90})]
    assert r.headers["Cache-Control"] == "private, no-store" and "Set-Cookie" not in r.headers


def test_server_reading_cap_is_idempotent_and_preserves_browser_default():
    # Exercise the isolated service function without registering a duplicate ORM
    # table in Flask-SQLAlchemy; SQL operations below are an injected unit double.
    import ast, typing
    from datetime import timedelta, timezone

    path = Path(__file__).parents[2] / "app/books/reading_session.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "end_session")
    started = datetime(2026, 11, 16, 12, tzinfo=UTC)
    now = started + timedelta(hours=2)
    row = SimpleNamespace(
        user_id=7,
        chapter_id=1,
        started_at=started,
        ended_at=None,
        start_offset_pct=0,
        offset_delta=0,
    )
    session = Mock()
    session.get.return_value = row
    namespace = {
        "Any": typing.Any,
        "Optional": typing.Optional,
        "UserReadingSession": object,
        "db": SimpleNamespace(session=session),
        "_utcnow": lambda: now,
        "_current_chapter_offset": lambda *a: 0.5,
        "timezone": timezone,
        "timedelta": timedelta,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    result = namespace["end_session"](1, max_duration_seconds=90)
    assert result.ended_at == started + timedelta(seconds=90)
    assert namespace["end_session"](1, max_duration_seconds=90).ended_at == result.ended_at
    row.ended_at = None
    assert namespace["end_session"](1).ended_at == now


@pytest.mark.parametrize("kind", ["quiz", "listening_quiz"])
def test_numeric_choice_feedback_is_not_decoded_as_a_second_index(c, kind, monkeypatch):
    import app.curriculum.routes.grammar_quiz_lessons as quiz_routes

    monkeypatch.setattr(quiz_routes, "_log_quiz_errors", lambda *a, **k: None, raising=False)
    # Force the expanded path; the legacy simple path is covered separately.

    c.lesson.type = kind
    item = {
        "type": "multiple_choice",
        "question": "Choose two",
        "options": ["1", "2", "3"],
        "correct_answer": 1,
    }
    if kind == "listening_quiz":
        item.update(audio="sound.mp3")
        c.lesson.content = {"exercises": [item]}
    else:
        c.lesson.content = {"questions": [item], "audio_url": "sound.mp3"}
    doc = fetch(c)
    r = submit(c, doc, {"0": "1"})
    assert r.status_code == 200, r.data
    assert r.json["feedback"][0]["expected"] == "2"


def test_retake_attempt_uses_new_server_opening_time(c):
    from datetime import timedelta

    old = datetime.now(UTC) - timedelta(days=10)
    c.db.add(
        Progress(
            user_id=7,
            lesson_id=42,
            status="completed",
            started_at=old,
            last_activity=old,
            data={},
            score=80,
            best_score=80,
            last_score=80,
        )
    )
    c.db.commit()
    doc = fetch(c)
    result = submit(c, doc, {"0": "am here."})
    assert result.status_code == 200, result.get_json()
    attempt = c.db.query(Attempt).one()
    assert attempt.started_at.date() == datetime.now(UTC).date()
    assert c.db.query(Progress).one().started_at.date() == old.date()
