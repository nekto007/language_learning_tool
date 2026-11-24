"""Owner-approved answer fixes survive only compatible admin reimports."""

from collections.abc import Callable
from copy import deepcopy

from flask import Flask
import pytest

from app.admin.main_routes import import_curriculum_data as legacy_import
from app.admin.services.curriculum_import_service import CurriculumImportService
from app.api.native_lessons import project_questions
from app.curriculum.answer_disputes import AnswerDispute, record_rejected_answer
from app.curriculum.answer_review import decide, decision_tag, proposed_edit
from app.curriculum.models import Lessons, Module
from app.utils.db import db
from tests.api.test_quiz_corrections import native_app


OWNER = 44121


def imported(importer: Callable[[dict], dict], source: dict) -> Lessons:
    result = importer(source)
    return db.session.get(Lessons, result["lesson_id"])


def approve(lesson: Lessons, answer: str, label: str) -> None:
    question = project_questions(lesson)[0]
    record_rejected_answer(db.session, lesson, question, answer)
    dispute = AnswerDispute.query.filter_by(lesson_id=lesson.id, status="pending").one()
    row = lesson.content["exercises"][0]
    patch = proposed_edit(lesson, row, question, answer, label)
    assert patch
    dispute.review = {"label": label, "patch": patch}
    dispute.status = "ready"
    db.session.commit()
    assert decide(dispute.id, decision_tag(dispute), "approve", OWNER, OWNER) == "Правка применена"
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
    native_app: Flask, monkeypatch: pytest.MonkeyPatch, importer: Callable[[dict], dict],
    number: int, kind: str, offset: int,
) -> None:
    monkeypatch.setitem(native_app.config, "ANSWER_REVIEW_OWNER_TELEGRAM_ID", str(OWNER))
    source = module_source(kind, number + offset)
    original = deepcopy(source)
    lesson = imported(importer, source)
    lesson_id = lesson.id
    approve(lesson, "I bought a bicycle.", "wrong_key")
    approve(lesson, "I bought a bike.", "valid_variant")
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


def test_reimport_does_not_choose_between_conflicting_approvals(native_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setitem(native_app.config, "ANSWER_REVIEW_OWNER_TELEGRAM_ID", str(OWNER))
    source = module_source("quiz", 209)
    importer = CurriculumImportService.import_curriculum_data
    lesson = imported(importer, source)
    original_content = deepcopy(lesson.content)
    approve(lesson, "I bought a bicycle.", "wrong_key")

    # Historic state: a pre-fix import had already reverted the stored question.
    lesson.content = deepcopy(original_content)
    db.session.commit()
    approve(lesson, "I purchased a bicycle.", "wrong_key")
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id, status="applied").count() == 2
    assert imported(importer, source).content == original_content
