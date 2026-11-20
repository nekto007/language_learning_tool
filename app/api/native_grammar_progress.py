"""Read-only topic coverage and explicit, idempotent native theory completion."""

from datetime import UTC, datetime
import hashlib
import json

from sqlalchemy import and_, case, func, or_

from app.api.native_content import NATIVE_PROJECTION_VERSION
from app.api.native_lessons import NativeLessonError, _theory
from app.curriculum.models import LessonProgress, Lessons
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise, UserGrammarTopicStatus
from app.utils.db import db


def theory_revision(theory):
    """Seal exactly the visible material, including its projection semantics."""
    payload = {"projection_version": NATIVE_PROJECTION_VERSION, "theory": theory}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def topic_progress(user_id, topic_ids):
    """Count unique answered exercises, not preallocated SRS rows or attempts.

    Both queries are read-only. In particular, do not reuse the web topic-list
    service, whose curriculum lazy-sync creates status rows and commits on GET.
    """
    ids = list(dict.fromkeys(topic_ids))
    if not ids:
        return {}
    answered = or_(
        UserGrammarExercise.first_reviewed.isnot(None),
        UserGrammarExercise.last_reviewed.isnot(None),
        UserGrammarExercise.correct_count > 0,
        UserGrammarExercise.incorrect_count > 0,
    )
    counts = (
        db.session.query(
            GrammarExercise.topic_id,
            func.count(func.distinct(GrammarExercise.id)),
            func.count(func.distinct(case((answered, GrammarExercise.id), else_=None))),
            func.count(func.distinct(case((UserGrammarExercise.correct_count > 0, GrammarExercise.id), else_=None))),
        )
        .outerjoin(
            UserGrammarExercise,
            and_(
                UserGrammarExercise.exercise_id == GrammarExercise.id,
                UserGrammarExercise.user_id == user_id,
            ),
        )
        .filter(GrammarExercise.topic_id.in_(ids))
        .group_by(GrammarExercise.topic_id)
        .all()
    )
    recorded = db.session.query(UserGrammarTopicStatus.topic_id).filter(
        UserGrammarTopicStatus.user_id == user_id,
        UserGrammarTopicStatus.topic_id.in_(ids),
        UserGrammarTopicStatus.theory_completed.is_(True),
    )
    curriculum = (
        db.session.query(Lessons.grammar_topic_id)
        .join(
            LessonProgress,
            LessonProgress.lesson_id == Lessons.id,
        )
        .filter(
            Lessons.grammar_topic_id.in_(ids),
            Lessons.type.in_(("grammar", "language_focus")),
            LessonProgress.user_id == user_id,
            LessonProgress.status == "completed",
        )
    )
    completed = {row[0] for row in recorded.union(curriculum).all()}
    result = {
        topic_id: {
            "theory_completed": topic_id in completed,
            "practiced_exercises": 0,
            "correct_exercises": 0,
            "total_exercises": 0,
        }
        for topic_id in ids
    }
    for topic_id, total, practiced, correct in counts:
        result[topic_id].update(
            total_exercises=int(total), practiced_exercises=int(practiced), correct_exercises=int(correct)
        )
    return result


def complete_theory(user_id, topic_id, revision):
    """Explicit final-slide acknowledgement; no practice/SRS/session writes."""
    from app.auth.deletion_access import learning_suspended
    from app.auth.models import User
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.grammar_lab.services.grammar_lab_service import GRAMMAR_XP

    try:
        # Use the same user-first lock order as deletion confirmation. This also
        # serializes two native completions before either can allocate a status.
        user = User.query.filter_by(id=user_id, active=True).with_for_update().populate_existing().first()
        if user is None:
            raise NativeLessonError("access_denied", 403)
        if learning_suspended(user_id):
            raise NativeLessonError("account_deletion_pending", 403)
        topic = GrammarTopic.query.filter_by(id=topic_id).with_for_update().populate_existing().first()
        if topic is None or topic.level not in PUBLIC_CEFR_CODES:
            raise NativeLessonError("not_found", 404)
        theory = _theory(topic.content or {})
        if theory_revision(theory) != revision:
            raise NativeLessonError("lesson_changed", 409)
        if not theory:
            raise NativeLessonError("unsupported_lesson", 422)
        status = UserGrammarTopicStatus.get_or_create(user_id, topic_id)
        status = UserGrammarTopicStatus.query.filter_by(id=status.id).with_for_update().populate_existing().one()
        progress = topic_progress(user_id, [topic_id])[topic_id]
        earned = 0
        if not status.theory_completed:
            if not progress["theory_completed"]:
                earned = GRAMMAR_XP["theory_completed"]
                status.add_xp(earned)
            status.theory_completed = True
            status.theory_completed_at = datetime.now(UTC)
            # Reading theory again must never regress existing practice/mastery.
            if status.status == "new":
                status.status = "theory_completed"
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {**progress, "theory_completed": True}, earned
