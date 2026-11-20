"""Author goals and public starter lines survive projection without answer keys."""
# ruff: noqa: RUF001 -- Russian teaching text is intentional.

import json
from types import SimpleNamespace

import pytest

from app.api.learning_guidance import learning_guidance
from tests.api import test_native_card_rounds as rounds
from tests.api import test_native_lessons as lessons

native_app = rounds.native_app
round_case = rounds.round_case
native_context = lessons.native_context


def starter():
    return {
        "title": "Первое знакомство",
        "goal": "Назови своё имя и скажи, откуда ты.",
        "lines": [{"english": "My name is Anna.", "russian": "Меня зовут Анна."}],
        "builder": {"secret_answer": "never expose arbitrary metadata"},
    }


def test_explicit_goal_overrides_starter_goal_and_only_public_lines_are_projected():
    content = {"learning_goal": "<b>Представь друга.</b>", "starter": starter(), "answers": ["private"]}
    result = learning_guidance(SimpleNamespace(content=content))
    assert result == {
        "learning_goal": "Представь друга.",
        "introduction": {"title": "Первое знакомство", "lines": starter()["lines"]},
    }
    assert learning_guidance(SimpleNamespace(content=json.dumps(content))) == result
    assert content["starter"]["builder"]  # Projection does not mutate authored data.


@pytest.mark.parametrize("bad", [None, [], "invalid JSON", {"learning_goal": {"answer": "private"}}])
def test_missing_or_malformed_optional_guidance_does_not_break_old_lessons(bad):
    assert learning_guidance(SimpleNamespace(content=bad)) == {}


@pytest.mark.parametrize("lines", [[], ["not a row"], [{"english": "hello"}], starter()["lines"] * 9])
def test_incomplete_or_overlong_starter_does_not_create_an_empty_required_screen(lines):
    result = learning_guidance(SimpleNamespace(content={"starter": {**starter(), "lines": lines}}))
    assert result == {"learning_goal": starter()["goal"]}


def test_starter_is_resumable_and_is_not_a_completion_or_an_answer(round_case):
    from app.utils.db import db
    from app.curriculum.models import LessonProgress, LessonAttempt

    case = round_case
    case.lesson.content = {**case.lesson.content, "starter": starter()}
    db.session.commit()
    run = case.start()
    assert run["learning_goal"] == starter()["goal"]
    assert run["introduction"]["lines"] == starter()["lines"]
    assert "builder" not in run["introduction"]
    assert run["reviewed"] == 0 and not run["lesson_complete"]
    assert case.start()["introduction"] == run["introduction"]
    assert LessonAttempt.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).count() == 0
    for _ in range(10):
        run = case.grade(run)
    progress = LessonProgress.query.filter_by(user_id=case.user.id, lesson_id=case.lesson.id).one()
    assert progress.status == "in_progress"
    assert not run["lesson_complete"]  # Authored minimum remains 14 answers.
    following = case.start(continue_round=True)
    assert "introduction" not in following
    assert following["learning_goal"] == starter()["goal"]
    assert following["card"]["word_id"] == 6  # Work completed in the first round stays covered.


def test_native_lesson_returns_authored_goal_without_changing_graded_questions(native_context):
    case = native_context
    before = lessons.fetch(case)
    case.lesson.content = {**case.lesson.content, "learning_goal": "Расскажи о себе."}
    after = lessons.fetch(case)
    assert after["learning_goal"] == "Расскажи о себе."
    assert after["questions"] == before["questions"]
    assert all("answer" not in question for question in after["questions"])
    assert case.writes == []


@pytest.mark.parametrize("level,expected", [("A1", "Представься."), ("A2", "Представься."), ("B1", None)])
def test_writing_uses_only_authored_task_translation_at_the_appropriate_level(native_context, level, expected):
    case = native_context
    case.lesson.type = "writing_prompt"
    case.lesson.module = SimpleNamespace(level=SimpleNamespace(code=level))
    case.lesson.content = {
        "prompt": "Introduce yourself.",
        "prompt_ru": "Представься.",
        "example_response": "PRIVATE MODEL ANSWER IS NOT A QUESTION TRANSLATION",
        "min_words": 2,
        "checklist": ["Greeting", "Name"],
    }
    question = lessons.fetch(case)["questions"][0]
    assert question["translation"] == expected
    assert question["prompt"] == "Introduce yourself."
    assert "PRIVATE MODEL" not in str(question)
