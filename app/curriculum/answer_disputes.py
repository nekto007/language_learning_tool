"""Shared queue for answers rejected by the course grader."""

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.utils.db import db
from app.utils.normalization import normalize_quiz_answer

if TYPE_CHECKING:
    from app.curriculum.models import Lessons
    from app.grammar_lab.models import GrammarExercise


DISPUTABLE_LESSON_TYPES = frozenset(("grammar", "quiz"))
# Bump when the answer acceptance or normalization rules for these lessons change.
GRADER_VERSION = 1
DISPUTE_IDENTITY = (
    "lesson_id", "question_id", "question_revision", "grader_version", "normalized_answer_hash",
)
LAB_DISPUTE_IDENTITY = (
    "grammar_exercise_id", "question_revision", "grader_version", "normalized_answer_hash",
)


class AnswerDispute(db.Model):
    __tablename__ = "answer_disputes"
    __table_args__ = (
        db.UniqueConstraint(*DISPUTE_IDENTITY, name="uq_answer_dispute_identity"),
        db.UniqueConstraint(*LAB_DISPUTE_IDENTITY, name="uq_answer_dispute_lab_identity"),
        db.CheckConstraint(
            "(lesson_id IS NULL) <> (grammar_exercise_id IS NULL)", name="ck_answer_dispute_source",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True)
    grammar_exercise_id = db.Column(
        db.Integer, db.ForeignKey(
            "grammar_exercises.id", name="fk_answer_dispute_lab_exercise", ondelete="CASCADE",
        ), nullable=True,
    )
    question_id = db.Column(db.String(16), nullable=False)
    question_revision = db.Column(db.String(64), nullable=False)
    grader_version = db.Column(db.Integer, nullable=False)
    normalized_answer_hash = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending", server_default="pending", index=True)
    evidence = db.Column(db.JSON, nullable=False)
    review = db.Column(db.JSON(none_as_null=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    next_attempt_at = db.Column(db.DateTime, nullable=True)


class AnswerDisputeReport(db.Model):
    """Each authenticated reporter of a shared content error."""

    __tablename__ = "answer_dispute_reports"
    __table_args__ = (
        db.UniqueConstraint("dispute_id", "user_id", name="uq_answer_dispute_report_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(db.Integer, db.ForeignKey("answer_disputes.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    grammar_attempt_id = db.Column(db.Integer, db.ForeignKey("grammar_attempts.id", ondelete="SET NULL"))
    course_nonce = db.Column(db.String(32))
    course_correction_id = db.Column(db.String(32))
    course_web_reported = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    course_web_answer = db.Column(db.JSON(none_as_null=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    credited_at = db.Column(db.DateTime(timezone=True))
    thanked_at = db.Column(db.DateTime(timezone=True))


class NativeCourseDisputeReceipt(db.Model):
    """An accepted check, separate from the shared case and its per-learner report."""

    __tablename__ = "native_course_dispute_receipts"

    id = db.Column(db.String(64), primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("answer_dispute_reports.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    nonce = db.Column(db.String(32), nullable=False)
    input_kind = db.Column(db.String(8), nullable=False)
    answer = db.Column(db.Text, nullable=False)


def course_report_channel_labels(web: bool, native: bool) -> list[str]:
    return [label for used, label in ((web, 'Веб'), (native, 'Мобильный квиз')) if used]  # noqa: RUF001 -- Russian UI label.


def course_dispute_channels(session: Session, case_id: int) -> list[str]:
    """Read only channels confirmed by reports at the time of display."""
    reports = select(AnswerDisputeReport.id).where(AnswerDisputeReport.dispute_id == case_id)
    web = reports.where(AnswerDisputeReport.course_web_reported.is_(True)).exists()
    native = reports.join(NativeCourseDisputeReceipt, NativeCourseDisputeReceipt.report_id == AnswerDisputeReport.id)
    web_reported, native_reported = session.execute(select(web, native.exists())).one()
    return course_report_channel_labels(web_reported, native_reported)


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _record_report(
    session: Session, identity: tuple[str, ...], values: dict, *, user_id: int | None,
    course_nonce: str | None = None, course_correction_id: str | None = None, grammar_attempt_id: int | None = None,
    course_web_answer: str | None = None,
) -> set[int]:
    case = _record_case(session, identity, values, lock=user_id is not None)
    if user_id is None:
        return set()
    assert case is not None
    return _attribute_report(session, case, user_id, course_nonce=course_nonce,
                             course_correction_id=course_correction_id, grammar_attempt_id=grammar_attempt_id,
                             course_web_answer=course_web_answer)


def _record_case(session: Session, identity: tuple[str, ...], values: dict, *, lock: bool) -> AnswerDispute | None:
    dialect = session.get_bind().dialect.name
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[dialect]
    session.execute(insert(AnswerDispute).values(**values).on_conflict_do_nothing(index_elements=identity))
    if not lock:
        return None
    return (session.query(AnswerDispute).filter_by(**{field: values[field] for field in identity})
            .populate_existing().with_for_update().one())


def _attribute_report(
    session: Session, case: AnswerDispute, user_id: int, *,
    course_nonce: str | None = None, course_correction_id: str | None = None, grammar_attempt_id: int | None = None,
    native_receipt: NativeCourseDisputeReceipt | None = None,
    course_web_answer: str | None = None,
) -> set[int]:
    report = session.query(AnswerDisputeReport).filter_by(dispute_id=case.id, user_id=user_id).one_or_none()
    if report is None:
        report = AnswerDisputeReport(dispute_id=case.id, user_id=user_id)
        session.add(report)
    if report.course_nonce is None and course_nonce is not None:
        report.course_nonce = course_nonce
        report.course_correction_id = course_correction_id
    if report.grammar_attempt_id is None and grammar_attempt_id is not None:
        report.grammar_attempt_id = grammar_attempt_id
    if course_web_answer is not None:
        report.course_web_reported = True
        if report.course_web_answer is None:
            report.course_web_answer = course_web_answer
    if native_receipt is not None:
        session.flush()
        native_receipt.report_id = report.id
        session.add(native_receipt)
    if case.status == "applied":
        from app.curriculum.dispute_credit import credit_approved_reports

        session.flush()
        return credit_approved_reports(case)
    return set()


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


def course_answer_hash(question: dict, answer: str) -> str:
    """Fingerprint the graded representation used in the shared case and attempt."""
    form = question.get("input")
    if form in ("order", "match"):
        normalized = json.loads(answer)
    elif form == "choice":
        normalized = answer
    else:
        normalized = normalize_quiz_answer(answer)
    return _hash(normalized)


def record_rejected_answer(
    session: Session, lesson: "Lessons", question: dict, answer: str, *,
    user_id: int | None = None, course_nonce: str | None = None, course_correction_id: str | None = None,
) -> set[int]:
    """Insert a graded rejection once, retaining the first evidence and review."""
    return _record_report(session, DISPUTE_IDENTITY, _course_rejection(lesson, question, answer),
                          user_id=user_id, course_nonce=course_nonce, course_correction_id=course_correction_id,
                          course_web_answer=answer)


def _course_rejection(lesson: "Lessons", question: dict, answer: str) -> dict:
    row, context = _question_evidence(lesson, question)
    return {
        "lesson_id": lesson.id,
        "question_id": question["id"],
        "question_revision": _question_revision(lesson, row, context),
        "grader_version": GRADER_VERSION,
        "normalized_answer_hash": course_answer_hash(question, answer),
        "evidence": {"row": row, "answer": answer, "question": context},
    }


def lock_native_course_dispute(session: Session, lesson: "Lessons", question: dict, answer: str) -> AnswerDispute:
    case = _record_case(session, DISPUTE_IDENTITY, _course_rejection(lesson, question, answer), lock=True)
    assert case is not None
    return case


def attach_native_course_dispute(
    session: Session, case: AnswerDispute, user_id: int, receipt: NativeCourseDisputeReceipt,
) -> set[int]:
    return _attribute_report(session, case, user_id, course_nonce=receipt.nonce, native_receipt=receipt)


def record_lab_rejected_answer(
    session: Session, exercise: "GrammarExercise", answer: object, normalized: object, *,
    user_id: int | None = None, grammar_attempt_id: int | None = None,
) -> None:
    from app.api.native_lessons import plain
    from app.grammar_lab.answer_review import LAB_GRADER_VERSION, effective_content, lab_revision

    row = effective_content(exercise)
    question = {
        "prompt": plain(row.get("question") or row.get("statement") or row.get("sentence")
                        or row.get("original") or row.get("prompt")),
        "instruction": plain(row.get("instruction")),
    }
    _record_report(session, LAB_DISPUTE_IDENTITY, {
        "grammar_exercise_id": exercise.id,
        "question_id": "0",
        "question_revision": lab_revision(exercise),
        "grader_version": LAB_GRADER_VERSION,
        "normalized_answer_hash": _hash(normalized),
        "evidence": {"row": row, "answer": answer, "question": question},
    }, user_id=user_id, grammar_attempt_id=grammar_attempt_id)


def attach_approved_lab_report(
    session: Session, exercise: "GrammarExercise", claims: dict, answer: object, normalized: object,
) -> None:
    """Accept a verified older rejection only for its exact, still-active approved edit."""
    from app.api.native_lessons import NativeLessonError
    from app.grammar_lab.answer_review import effective_content, grade_row, lab_revision
    from app.grammar_lab.models import GrammarExercise

    case = (session.query(AnswerDispute).filter_by(
        grammar_exercise_id=exercise.id, question_revision=claims["revision"], grader_version=claims["grader"],
        normalized_answer_hash=_hash(normalized), status="applied",
    ).populate_existing().with_for_update().one_or_none())
    if case is None or claims.get("attempt") is None:
        raise NativeLessonError("lesson_changed", 409)
    current = (session.query(GrammarExercise).filter_by(id=exercise.id)
               .populate_existing().with_for_update(read=True).one_or_none())
    if (current is None or current.content.get("guided_retired")
            or (case.review or {}).get("updated_revision") != lab_revision(current)
            or grade_row(current, effective_content(current), answer).get("is_correct") is not True):
        raise NativeLessonError("lesson_changed", 409)
    _attribute_report(session, case, claims["user"], grammar_attempt_id=claims["attempt"])


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
        if not isinstance(review, dict):
            continue
        evidence = dispute.evidence if isinstance(dispute.evidence, dict) else {}
        answer = review.get("editor_answer", evidence.get("answer"))
        actor = review.get("decided_by_user_id", review.get("decided_by"))
        if (type(actor) is not int or actor <= 0 or review.get("label") not in ("valid_variant", "wrong_key")
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
