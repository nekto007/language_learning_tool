"""Short native lesson rounds preserve authored requirements and durable progress."""
# ruff: noqa: RUF001

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.api import test_native_full_integration as integration

native_app = integration.native_app
learner = integration.learner


def deck(words=12):
    return [
        dict(
            word_id=word,
            direction=direction,
            key=f"{word}:{direction}",
            front=f"word {word}",
            back=f"слово {word}",
            examples="",
            state="new",
            revision=None,
            display_only=True,
            practice_only=True,
        )
        for word in range(1, words + 1)
        for direction in ("eng-rus", "rus-eng")
    ]


def test_rounds_separate_directions_preserve_word_order_and_skip_covered():
    from app.api.native_cards import _short_round

    cards = deck()
    first = _short_round(cards, {})
    assert [c["word_id"] for c in first] == list(range(1, 6)) * 2
    assert [c["direction"] for c in first] == ["eng-rus"] * 5 + ["rus-eng"] * 5
    second = _short_round(cards, {c["key"]: 3 for c in first})
    assert [c["word_id"] for c in second] == list(range(6, 11)) * 2
    assert len(cards) == 24  # The source lesson is never truncated.


def test_retry_does_not_follow_or_precede_opposite_direction():
    from app.api.native_cards import _requeue

    queue = deck(4)
    card = queue.pop(0)
    _requeue(queue, card, 3)
    index = queue.index(card)
    assert index >= 2
    assert queue[index - 1]["word_id"] != card["word_id"]
    assert queue[index + 1]["word_id"] != card["word_id"]


@pytest.fixture
def round_case(native_app, monkeypatch):
    from app.utils.db import db
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress
    from app.api import native_cards
    from app.api.native_lessons import NativeLessonError
    import app.curriculum.security as security
    import app.daily_plan.linear.xp as xp

    user, headers = learner(native_app)
    level = CEFRLevel.query.filter_by(code="XR").first()
    if level is None:
        level = CEFRLevel(code="XR", name="Round tests")
        db.session.add(level)
        db.session.flush()
    module = Module(level_id=level.id, number=user.id, title="Round test")
    db.session.add(module)
    db.session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Twelve words",
        type="flashcards",
        min_cards_required=14,
        content={"cards": ["synthetic local fixture"]},
    )
    db.session.add(lesson)
    db.session.commit()
    awards = []

    def award(*args, **kwargs):
        awards.append(kwargs["score"])
        return SimpleNamespace(xp_awarded=18)

    def guard(*args):
        progress = LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).first()
        if progress and progress.status == "completed":
            raise NativeLessonError("lesson_locked", 403)

    monkeypatch.setattr(native_cards, "_guard_plan", guard)
    monkeypatch.setattr(security, "check_lesson_access", lambda *a: True)
    monkeypatch.setattr(native_cards, "_queue", lambda *a: deepcopy(deck()))
    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", award)
    client = native_app.test_client()
    base = f"/api/native/lessons/{lesson.id}/cards"

    def start(**kwargs):
        response = client.post(base + "/session", headers=headers, json={"request_id": str(uuid4()), **kwargs})
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    def grade(run, rating=3):
        response = client.post(
            base + "/grade",
            headers=headers,
            json={"session_id": run["session_id"], "step": run["step"], "rating": rating},
        )
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    return SimpleNamespace(
        user=user, lesson=lesson, awards=awards, start=start, grade=grade, client=client, headers=headers, base=base
    )


def test_multiple_rounds_keep_minimum_resume_and_award_completion_only_once(round_case):
    from app.curriculum.models import LessonProgress, LessonAttempt

    case = round_case
    run = case.start()
    assert run["statistics"]["total_words"] == 5
    assert run["statistics"]["total_cards"] == 10
    first_session = run["session_id"]
    for _ in range(10):
        run = case.grade(run)
    assert run["complete"] and not run["lesson_complete"]
    assert run["remaining_lesson_words"] == 7
    assert case.awards == []  # Authored minimum 14 is not clamped to this round's 10.
    progress = LessonProgress.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).one()
    assert progress.status == "in_progress"
    assert len(progress.data["native_card_rounds"]["ratings"]) == 10

    run = case.start(continue_round=True)
    assert run["session_id"] != first_session
    assert run["card"]["word_id"] == 6
    for _ in range(10):
        run = case.grade(run)
    assert run["complete"] and run["lesson_complete"] and run["more_rounds"]
    assert run["remaining_lesson_words"] == 2
    assert run["xp_earned"] == 18 and case.awards == [100]

    run = case.start(continue_round=True)
    assert run["statistics"]["total_cards"] == 4
    assert run["card"]["word_id"] == 11
    assert case.start()["session_id"] == run["session_id"]  # Recreated screen resumes practice.
    for _ in range(4):
        old_run = run
        run = case.grade(run)
    assert run["complete"] and run["lesson_complete"] and not run["more_rounds"]
    assert case.grade(old_run) == run  # Network replay has no side effects.
    assert run["xp_earned"] == 0 and case.awards == [100]
    assert LessonAttempt.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).count() == 1
    assert len(progress.data["native_card_rounds"]["ratings"]) == 24


def test_ratings_are_distinct_and_counts_separate_attempts_cards_and_words(round_case):
    case = round_case
    run = case.start()
    for rating in [1, 2, 3]:
        run = case.grade(run, rating)
    stats = run["statistics"]
    assert (stats["unknown"], stats["hesitant"], stats["known"]) == (1, 1, 1)
    assert stats["unique_cards"] == 3 and stats["unique_words"] == 3
    while not run["complete"]:
        run = case.grade(run)
    assert run["reviewed"] == 12  # Weak display-only cards repeat once.
    assert run["statistics"]["unique_cards"] == 10
    assert run["statistics"]["unique_words"] == 5
    assert sum(run["statistics"][k] for k in ("unknown", "hesitant", "known")) == 12


def test_practice_never_bypasses_paused_plan_and_start_input_stays_strict(round_case, monkeypatch):
    from app.api import native_cards
    from app.api.native_lessons import NativeLessonError

    case = round_case
    for bad in ("true", 1, None):
        response = case.client.post(
            case.base + "/session", headers=case.headers, json={"request_id": str(uuid4()), "continue_round": bad}
        )
        assert response.status_code == 400
    run = case.start()

    def paused(*a):
        raise NativeLessonError("plan_paused", 403)

    monkeypatch.setattr(native_cards, "_guard_plan", paused)
    response = case.client.post(
        case.base + "/grade", headers=case.headers, json={"session_id": run["session_id"], "step": 0, "rating": 3}
    )
    assert response.status_code == 403 and response.get_json()["error"] == "plan_paused"
    response = case.client.post(
        case.base + "/session", headers=case.headers, json={"request_id": str(uuid4()), "continue_round": True}
    )
    assert response.status_code == 403


def test_legacy_session_statistics_are_not_invented():
    from app.api.native_srs import _statistics

    assert _statistics({"reviewed": 4, "remembered": 3}) is None


@pytest.mark.parametrize(
    "stored",
    [
        "This is my friend.<br>Это мой друг.",
        "This is my friend.|Это мой друг.",
        '[{"en":"This is my friend.","ru":"Это мой друг."}]',
        {"english": "This is my friend.", "translation": "Это мой друг."},
    ],
)
def test_examples_normalize_both_html_and_structured_dictionary_records(stored):
    from app.api.native_srs import _examples

    assert _examples(stored) == "This is my friend.\nЭто мой друг."


def test_partial_coverage_survives_replaced_srs_session(round_case):
    from app.study.models import NativeSRSState
    from app.utils.db import db

    case = round_case
    run = case.start()
    for _ in range(3):
        run = case.grade(run)
    record = NativeSRSState.query.filter_by(user_id=case.user.id).one()
    record.state = {**record.state, "lesson_id": None}  # Another study activity replaced it.
    db.session.commit()
    resumed = case.start()
    assert resumed["card"]["word_id"] == 4
    assert resumed["statistics"]["total_words"] == 5
    while not resumed["complete"]:
        resumed = case.grade(resumed)
    assert not resumed["lesson_complete"]  # Only 13 of the required 14 directions covered.


def test_failed_completion_rolls_back_rating_coverage_and_receipt(round_case, monkeypatch):
    import app.daily_plan.linear.xp as xp
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.utils.db import db

    case = round_case
    case.lesson.min_cards_required = 10
    db.session.commit()
    run = case.start()
    for _ in range(9):
        run = case.grade(run)

    def failure(*a, **kw):
        raise RuntimeError("simulated local award failure")

    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", failure)
    response = case.client.post(
        case.base + "/grade",
        headers=case.headers,
        json={"session_id": run["session_id"], "step": run["step"], "rating": 3},
    )
    assert response.status_code == 500
    progress = LessonProgress.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).one()
    assert progress.status == "in_progress"
    assert len(progress.data["native_card_rounds"]["ratings"]) == 9
    assert LessonAttempt.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).count() == 0
    assert case.start()["step"] == 9
    monkeypatch.setattr(xp, "maybe_award_curriculum_xp", lambda *a, **k: None)
    assert case.grade(run)["lesson_complete"]


def test_uncertain_answers_do_not_become_known_in_lesson_summary(round_case):
    from app.curriculum.models import LessonProgress
    from app.utils.db import db

    case = round_case
    case.lesson.min_cards_required = 10
    db.session.commit()
    run = case.start()
    while not run["complete"]:
        run = case.grade(run, 2)
    assert run["statistics"]["known"] == 0
    assert run["statistics"]["hesitant"] == 20
    progress = LessonProgress.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).one()
    assert progress.data["correct"] == 0 and progress.data["assessment"] == "self_assessed"


def test_real_dictionary_br_example_is_normalized_without_changing_srs_identity(native_app, monkeypatch):
    from flask import g
    from app.api import native_cards
    from app.words.models import CollectionWords
    from app.study.models import UserWord
    from app.utils.db import db
    import app.srs.counting as counting

    user, _ = learner(native_app)
    word = CollectionWords(
        english_word="native round " + uuid4().hex, russian_word="друг", sentences="This is my friend.<br>Это мой друг."
    )
    db.session.add(word)
    db.session.commit()
    lesson = SimpleNamespace(
        content={"cards": [{"word_id": word.id}]},
        collection_id=None,
        module_id=None,
        number=1,
        id=999999,
        type="flashcards",
    )
    monkeypatch.setattr(counting, "get_new_card_budget", lambda *a: (2, 0))
    with native_app.test_request_context("/api/native/lessons/999999/cards/session"):
        g._login_user = user
        cards = native_cards._queue(lesson)
        assert len(cards) == 2
        assert all(c["word_id"] == word.id for c in cards)
        assert all(c["examples"] == "This is my friend.\nЭто мой друг." for c in cards)
        assert all(c["practice_only"] is False for c in cards)
        assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).count() == 1
    db.session.rollback()
