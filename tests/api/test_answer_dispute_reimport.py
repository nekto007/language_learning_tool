"""Owner-approved answer fixes survive only compatible admin reimports."""

from collections.abc import Callable, Iterator
from copy import deepcopy

from flask import Flask
import pytest

from app.admin.main_routes import import_curriculum_data as legacy_import
from app.admin.services.curriculum_import_service import CurriculumImportService
from app.api.native_lessons import project_questions
from app.curriculum.answer_disputes import AnswerDispute, record_rejected_answer
from app.curriculum.answer_review_editor import editor_decide, editor_preview, editor_version
from app.curriculum.models import Lessons, Module
from app.grammar_lab.guided_learning import check_answer
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin
from tests.api.test_quiz_corrections import native_app


@pytest.fixture
def review_admin(native_app: Flask) -> Iterator[int]:  # noqa: F811
    with telegram_admin() as binding:
        yield binding.user_id


def imported(importer: Callable[[dict], dict], source: dict) -> Lessons:
    result = importer(source)
    return db.session.get(Lessons, result["lesson_id"])


def approve(lesson: Lessons, answer: str, action: str, admin_id: int) -> None:
    question = project_questions(lesson)[0]
    record_rejected_answer(db.session, lesson, question, answer)
    dispute = AnswerDispute.query.filter_by(lesson_id=lesson.id, status="pending").one()
    assert editor_preview(dispute, action, answer)["accepts_report"]
    assert editor_decide(dispute.id, admin_id, editor_version(dispute), action, answer) == "Правка сохранена."
    assert dispute.review["decided_by_user_id"] == admin_id
    assert dispute.status == "applied"


def module_source(kind: str, number: int) -> dict:
    return {
        "level": "B1", "module": number, "title": "Answer-review reimport",
        "lessons": [{
            "lesson_number": 1, "lesson_type": kind, "title": "A bicycle", "xp_reward": 12,
            "theory": {"rule": "Use the past tense for a completed action."},
            "exercises": [{
                "type": "translation", "question": "Я купил велосипед.",
                "prompt": "Я купил велосипед.", "correct_answer": "I sold a bicycle.",
            }],
        }],
    }


@pytest.mark.parametrize("importer,number", [
    (CurriculumImportService.import_curriculum_data, 200),
    (legacy_import, 203),
], ids=["service", "legacy"])
@pytest.mark.parametrize("kind,offset", [("quiz", 0), ("grammar", 1)])
def test_reimport_preserves_approved_chain_and_author_changes(
    review_admin: int, importer: Callable[[dict], dict],
    number: int, kind: str, offset: int,
) -> None:
    source = module_source(kind, number + offset)
    original = deepcopy(source)
    lesson = imported(importer, source)
    lesson_id = lesson.id
    approve(lesson, "I bought a bicycle.", "replace", review_admin)
    approve(lesson, "I bought a bike.", "add", review_admin)
    approved = deepcopy(lesson.content["exercises"][0])

    for _ in range(2):
        lesson = imported(importer, source)
        assert lesson.id == lesson_id
        assert lesson.content["exercises"][0] == approved
        assert source == original
        assert db.session.get(Module, lesson.module_id).raw_content == original

    edited_source = deepcopy(original)
    edited_source["lessons"][0]["exercises"][0]["correct_answer"] = "I purchased a bicycle."
    lesson = imported(importer, edited_source)
    row = lesson.content["exercises"][0]
    assert row.get("answer", row.get("correct_answer")) == "I purchased a bicycle."
    assert "I bought a bike." not in row.get("alternative_answers", [])
    assert AnswerDispute.query.filter_by(lesson_id=lesson_id, status="applied").count() == 2


def test_reimport_does_not_choose_between_conflicting_approvals(review_admin: int) -> None:
    source = module_source("quiz", 209)
    importer = CurriculumImportService.import_curriculum_data
    lesson = imported(importer, source)
    original_content = deepcopy(lesson.content)
    approve(lesson, "I bought a bicycle.", "replace", review_admin)

    # Historic state: a pre-fix import had already reverted the stored question.
    lesson.content = deepcopy(original_content)
    db.session.commit()
    approve(lesson, "I purchased a bicycle.", "replace", review_admin)
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id, status="applied").count() == 2
    assert imported(importer, source).content == original_content


@pytest.mark.parametrize("importer,number", [
    (CurriculumImportService.import_curriculum_data, 211),
    (legacy_import, 213),
], ids=["service", "legacy"])
@pytest.mark.parametrize("kind,offset", [("quiz", 0), ("grammar", 1)])
def test_reimport_preserves_promoted_alias_and_retires_old_key(
    review_admin: int, importer: Callable[[dict], dict], number: int, kind: str, offset: int,
) -> None:
    source = module_source(kind, number + offset)
    old_key, promoted, retained = "I sold a bicycle.", "I bought a bicycle.", "I bought a bike."
    old_alias = "I SOLD A BICYCLE!"
    source["lessons"][0]["exercises"][0]["alternative_answers"] = [old_alias, promoted, retained]
    lesson = imported(importer, source)
    lesson_id = lesson.id
    question = project_questions(lesson)[0]
    record_rejected_answer(db.session, lesson, question, "I repaired a bicycle.")
    case = AnswerDispute.query.filter_by(lesson_id=lesson.id, status="pending").one()
    preview = editor_preview(case, "replace", promoted)
    assert preview["after"] == promoted
    assert preview["aliases"] == [retained]
    assert preview["removed_answers"] == [old_key, old_alias]
    editor_decide(case.id, review_admin, editor_version(case), "replace", promoted)
    for _ in range(2):
        lesson = imported(importer, source)
        assert lesson.id == lesson_id
        row = lesson.content["exercises"][0]
        assert row["alternative_answers"] == [retained]
        question = project_questions(lesson)[0]
        for answer, expected in [(old_key, False), (old_alias, False), (promoted, True), (retained, True)]:
            assert check_answer(row, question, answer, grammar=kind == "grammar")["correct"] is expected
