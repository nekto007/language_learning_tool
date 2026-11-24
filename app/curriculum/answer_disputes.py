"""Shared queue for answers rejected by the course grader."""

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.utils.db import db
from app.utils.normalization import normalize_quiz_answer

if TYPE_CHECKING:
    from app.curriculum.models import Lessons


DISPUTABLE_LESSON_TYPES = frozenset(("grammar", "quiz"))
# Bump when the answer acceptance or normalization rules for these lessons change.
GRADER_VERSION = 1
DISPUTE_IDENTITY = (
    "lesson_id", "question_id", "question_revision", "grader_version", "normalized_answer_hash",
)


class AnswerDispute(db.Model):
    __tablename__ = "answer_disputes"
    __table_args__ = (db.UniqueConstraint(*DISPUTE_IDENTITY, name="uq_answer_dispute_identity"),)

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False)
    question_id = db.Column(db.String(16), nullable=False)
    question_revision = db.Column(db.String(64), nullable=False)
    grader_version = db.Column(db.Integer, nullable=False)
    normalized_answer_hash = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending", server_default="pending", index=True)
    evidence = db.Column(db.JSON, nullable=False)
    review = db.Column(db.JSON(none_as_null=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    next_attempt_at = db.Column(db.DateTime, nullable=True)


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_rows_field(lesson: "Lessons", content: dict) -> str:
    return "questions" if lesson.type == "quiz" and content.get("questions") else "exercises"


def _question_evidence(lesson: "Lessons", question: dict) -> tuple[dict, dict]:
    from app.api.native_content import extras, is_extended
    from app.api.native_lessons import _content, plain

    content = _content(lesson)
    rows = content[_source_rows_field(lesson, content)]
    row = rows[int(question["id"])]
    context = {key: question[key] for key in ("prompt", "instruction", "context") if key in question}
    instruction = plain(content.get("instruction") or content.get("instructions"))
    if is_extended(lesson):
        instruction = extras(lesson)["instruction"] or instruction
    if instruction:
        context["lesson_instruction"] = instruction
    return row, context


def _question_revision(lesson: "Lessons", row: dict, context: dict) -> str:
    from app.api.native_lessons import _content

    content = _content(lesson)
    inherited_audio = None
    if not any(row.get(field) for field in ("audio", "audio_url", "audio_clip_url")):
        inherited_audio = content.get("audio_url") or content.get("audio")
    return _hash({
        "lesson_type": lesson.type, "row": row, "context": context, "inherited_audio": inherited_audio,
    })


def current_dispute_row(dispute: AnswerDispute, lesson: "Lessons") -> dict | None:
    """Revalidate the source row before applying a review to the current lesson."""
    from app.api.native_lessons import NativeLessonError, project_questions

    if (dispute.lesson_id != lesson.id or dispute.grader_version != GRADER_VERSION
            or lesson.type not in DISPUTABLE_LESSON_TYPES):
        return None
    try:
        question = next((q for q in project_questions(lesson) if q["id"] == dispute.question_id), None)
        if question is None:
            return None
        row, context = _question_evidence(lesson, question)
    except (NativeLessonError, KeyError, IndexError, TypeError):
        return None
    return row if dispute.question_revision == _question_revision(lesson, row, context) else None


def record_rejected_answer(session: Session, lesson: "Lessons", question: dict, answer: str) -> None:
    """Insert a graded rejection once, retaining the first evidence and review."""
    row, context = _question_evidence(lesson, question)
    form = question.get("input")
    if form in ("order", "match"):
        normalized = json.loads(answer)
    elif form == "choice":
        normalized = answer
    else:
        normalized = normalize_quiz_answer(answer)
    dialect = session.get_bind().dialect.name
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[dialect]
    statement = insert(AnswerDispute).values(
        lesson_id=lesson.id,
        question_id=question["id"],
        question_revision=_question_revision(lesson, row, context),
        grader_version=GRADER_VERSION,
        normalized_answer_hash=_hash(normalized),
        evidence={"row": row, "answer": answer, "question": context},
    ).on_conflict_do_nothing(index_elements=DISPUTE_IDENTITY)
    session.execute(statement)


def preserve_approved_answers(session: Session, lesson: "Lessons") -> None:
    """Replay owner decisions onto an exact imported source, before it is flushed."""
    if (lesson.type not in DISPUTABLE_LESSON_TYPES or not isinstance(lesson.content, dict)
            or lesson.content.get("learning_steps")):
        return
    with session.no_autoflush:
        disputes = session.query(AnswerDispute).filter_by(
            lesson_id=lesson.id, grader_version=GRADER_VERSION, status="applied",
        ).all()
    if not disputes:
        return

    from app.api.native_lessons import NativeLessonError, project_questions
    from app.curriculum.answer_review import proposed_edit

    approved = []
    changes_by_revision = defaultdict(set)
    for dispute in disputes:
        review = dispute.review
        answer = dispute.evidence.get("answer") if isinstance(dispute.evidence, dict) else None
        if (not isinstance(review, dict) or type(review.get("decided_by")) is not int
                or review["decided_by"] <= 0 or review.get("label") not in ("valid_variant", "wrong_key")
                or not isinstance(review.get("patch"), dict) or not review["patch"]
                or not isinstance(answer, str)):
            continue
        try:
            decided_at = datetime.fromisoformat(review["decided_at"])
            if decided_at.utcoffset() is None:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        identity = (dispute.question_id, dispute.question_revision)
        changes_by_revision[identity].add(_hash(review["patch"]))
        approved.append((decided_at, dispute.id, dispute, answer))

    for _, _, dispute, answer in sorted(approved, key=lambda decision: decision[:2]):
        if len(changes_by_revision[(dispute.question_id, dispute.question_revision)]) != 1:
            continue
        source_row = current_dispute_row(dispute, lesson)
        if source_row is None:
            continue
        try:
            question = next(q for q in project_questions(lesson) if q["id"] == dispute.question_id)
            patch = proposed_edit(lesson, source_row, question, answer, dispute.review["label"])
        except NativeLessonError:
            continue
        if not patch or patch != dispute.review["patch"]:
            continue
        content = lesson.content
        field = _source_rows_field(lesson, content)
        rows = list(content[field])
        rows[int(dispute.question_id)] = {**source_row, **deepcopy(patch)}
        lesson.content = {**content, field: rows}
