"""Authenticated native daily-plan exercises outside the curriculum spine."""

from copy import deepcopy
from datetime import datetime, UTC
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.curriculum.constants import PASSING_SCORE_QUIZ
from app.api.native_lessons import (
    NativeLessonError,
    native_error,
    private_response,
    _theory,
    _digest,
)
from app.api.native_content import (
    NATIVE_PROJECTION_VERSION, _question, _converted, _plain, display_answer, matching_answer,
)
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_activities = Blueprint("api_native_activities", __name__)
api_native_activities.after_request(private_response)
api_native_activities.register_error_handler(NativeLessonError, native_error)
KINDS = {
    "grammar_review",
    "grammar_topic",
    "error_review",
    "phrase_review",
    "word_set_quiz",
    "deck_quiz",
}


def _signer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="native-activity-v1")


def _day():
    from app.utils.time_utils import get_user_local_date

    return get_user_local_date(current_user.id, db).isoformat()


def _guard(kind, item_id):
    if kind == "grammar_topic":
        return
    from app.daily_plan.service import get_daily_plan_unified
    from app.achievements.streak_service import compute_plan_steps
    from app.telegram.queries import get_daily_summary
    from app.utils.time_utils import get_user_timezone_name

    plan = get_daily_plan_unified(current_user.id, tz=get_user_timezone_name(current_user.id, db))
    if plan.get("mode") == "paused":
        raise NativeLessonError("plan_paused", 403)
    completed, *_ = compute_plan_steps(
        plan, get_daily_summary(current_user.id, tz=get_user_timezone_name(current_user.id, db))
    )
    required = plan.get("required") or []
    optional = plan.get("optional") or []
    done = lambda it: it.get("completed") or completed.get(it.get("id"), False)
    active = next(
        (it for it in required if not done(it) and not it.get("skipped") and not it.get("blocked")),
        None,
    )
    if active is None and (
        not required
        or all(done(it) or it.get("skipped") for it in required)
        or plan.get("day_secured")
    ):
        active = next((it for it in optional if not done(it)), None)
    skipped = next(
        (
            it
            for it in required
            if it.get("id") == item_id
            and it.get("skipped")
            and not done(it)
            and not it.get("blocked")
        ),
        None,
    )
    item = skipped or active
    if (
        item is None
        or item.get("id") != item_id
        or item.get("kind") != ("srs" if kind == "deck_quiz" else kind)
        or item.get("blocked")
    ):
        raise NativeLessonError("lesson_locked", 403)


def _public_topic(topic):
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES

    return topic is not None and topic.level in PUBLIC_CEFR_CODES


def _prepare(kind, item_id):
    rows = []
    source = {}
    theory = []
    title = "Практика"
    level = "A1"
    if kind in ("grammar_review", "grammar_topic"):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise
        from app.grammar_lab.services.grammar_lab_service import GrammarLabService

        try:
            topic_id = int(item_id.rsplit(":", 1)[-1])
        except ValueError:
            raise NativeLessonError("invalid_input")
        topic = GrammarTopic.query.get(topic_id)
        if not _public_topic(topic):
            raise NativeLessonError("not_found", 404)
        service = GrammarLabService()
        guided = (topic.content or {}).get("guided_exercise_ids") if kind == "grammar_topic" else None
        if guided:
            from app.grammar_lab.services.grammar_lab_service import _get_unified_srs_service
            from uuid import uuid4

            if not isinstance(guided, list) or not all(type(key) is int for key in guided):
                raise NativeLessonError("unsupported_lesson", 422)
            service.srs.get_or_create_topic_status(current_user.id, topic_id)
            _get_unified_srs_service().get_or_create_grammar_exercise_progress(current_user.id, guided)
            _get_unified_srs_service().reset_grammar_session_attempts(current_user.id, topic_id=topic_id)
            selected = {"session_id": f"grammar_{topic_id}_{current_user.id}_{uuid4().hex[:8]}",
                        "exercises": [{"id": key} for key in guided]}
        else:
            targeted = item_id.startswith('grammar_review:placement:')
            if targeted:
                from app.onboarding.placement_reviews import from_item, item_for
                review = from_item(current_user.id, item_id)
                expected = item_for(review)
                if expected is None or expected.id != item_id:
                    raise NativeLessonError('lesson_changed', 409)
            selected = service.start_topic_practice(topic_id, current_user.id, max_exercises=3) if targeted else service.start_topic_practice(topic_id, current_user.id)
            if targeted and len(selected.get('exercises') or []) != 3:
                raise NativeLessonError('lesson_changed', 409)
        if selected.get("error"):
            raise NativeLessonError("not_found", 404)
        ids = [int(e["id"]) for e in selected.get("exercises") or []]
        all_ex = {e.id: e for e in GrammarExercise.query.filter(GrammarExercise.id.in_(ids)).all()}
        for key in ids:
            e = all_ex.get(key)
            if e is None or e.topic_id != topic_id or (e.content or {}).get("guided_retired"):
                raise NativeLessonError("unsupported_lesson", 422)
            rows.append(
                {
                    **deepcopy(e.content),
                    "type": "match" if e.exercise_type == "matching" else e.exercise_type,
                }
            )
        source = {
            "exercise_ids": ids,
            "topic_id": topic_id,
            "revision": {str(k): _digest(all_ex[k].content) for k in ids},
            "session_key": selected["session_id"],
        }
        if item_id.startswith('grammar_review:placement:'):
            source['placement_review_id'] = review.id
        if guided:
            from app.grammar_lab.guided_learning import learning_steps

            source["learning_steps"] = learning_steps(topic.content, len(rows))
        theory = _theory(topic.content or {})
        if item_id.startswith('grammar_review:placement:'):
            theory = [block for block in theory if len(block.get('body') or '') <= 1500][:1]
        title = topic.title_ru or topic.title
        level = topic.level
    elif kind == "phrase_review":
        from app.daily_plan.items.phrase_review import get_phrase_review_items

        items = get_phrase_review_items(current_user.id, db)
        rows = [
            {
                "type": "translation",
                "prompt": i["prompt"],
                "answer": i["answer"],
                "acceptable_answers": i.get("accepted_answers") or [],
            }
            for i in items
        ]
        source = {"items": items}
        title = "Повторение фраз"
    elif kind == "error_review":
        from app.daily_plan.linear.errors import get_review_pool
        from app.api.native_content import rows_for
        from app.curriculum.security import check_lesson_access

        errors = get_review_pool(current_user.id, db)
        ids = []
        sources = []
        revisions = []
        for error in errors:
            if not check_lesson_access(error.lesson_id):
                raise NativeLessonError("access_denied", 403)
            p = error.question_payload or {}
            revision = (error.lesson.content or {}).get("guided_catalog_digest") if error.lesson else None
            if (p.get("guided_revision") or None) != (revision or None):
                raise NativeLessonError("lesson_changed", 409)
            raw = None
            try:
                original = rows_for(error.lesson)
                index = int(p.get("question_index", -1))
                if 0 <= index < len(original):
                    raw = deepcopy(original[index])
                    if revision and raw.get("guided_key") != p.get("guided_key"):
                        raise NativeLessonError("lesson_changed", 409)
            except (ValueError, TypeError):
                pass
            if revision and raw is None:
                raise NativeLessonError("lesson_changed", 409)
            if raw is None:
                raw = {
                    "type": p.get("question_type") or "fill_in_blank",
                    "question": p.get("question_text") or "Исправь ответ",
                    "options": p.get("options") or [],
                    "answer": p.get("correct_answer"),
                }
            rows.append(raw)
            ids.append(error.id)
            sources.append("grammar" if p.get("source") == "grammar" else "quiz")
            revisions.append(revision)
            topic = error.lesson.grammar_topic if error.lesson is not None else None
            if topic and not theory:
                theory = _theory(topic.content or {})
        source = {"error_ids": ids, "sources": sources, "error_revisions": revisions}
        title = "Разбор ошибок"
    elif kind == "deck_quiz":
        from app.modules.service import ModuleService
        from app.study.models import QuizDeck, QuizDeckWord
        from app.study.services import QuizService
        from app.words.models import CollectionWords
        from app.utils.db_utils import not_blank
        from sqlalchemy import and_, or_, func

        if item_id != "srs:deck_quiz" or not ModuleService.is_module_enabled_for_user(
            current_user.id, "study"
        ):
            raise NativeLessonError("access_denied", 403)
        valid_collection = and_(
            QuizDeckWord.word_id.isnot(None),
            not_blank(CollectionWords.english_word),
            not_blank(CollectionWords.russian_word),
        )
        valid_custom = and_(
            not_blank(QuizDeckWord.custom_english), not_blank(QuizDeckWord.custom_russian)
        )
        entries = (
            db.session.query(QuizDeckWord)
            .join(QuizDeck, QuizDeckWord.deck_id == QuizDeck.id)
            .outerjoin(CollectionWords, QuizDeckWord.word_id == CollectionWords.id)
            .filter(QuizDeck.user_id == current_user.id, or_(valid_collection, valid_custom))
            .order_by(func.random())
            .limit(300)
            .all()
        )
        words = []
        seen = set()
        for entry in entries:
            english = (entry.english_word or "").strip()
            russian = (entry.russian_word or "").strip()
            if not english or not russian:
                continue
            key = (
                entry.word_id
                if entry.word_id is not None
                else ("custom", english.lower(), russian.lower())
            )
            if key in seen:
                continue
            seen.add(key)
            words.append(
                SimpleNamespace(
                    id=entry.word_id,
                    english_word=english,
                    russian_word=russian,
                    get_download=0,
                    listening=None,
                )
            )
            if len(words) >= 30:
                break
        rows = QuizService.generate_quiz_questions(
            words, min(30, len(words)), distractor_pool=words
        )
        source = {"mode": "deck_quiz"}
        title = "Квиз по словам из колод"
    elif kind == "word_set_quiz":
        from app.modules.service import ModuleService
        from app.study.services import WordSetService, QuizService

        if not ModuleService.is_module_enabled_for_user(current_user.id, "study"):
            raise NativeLessonError("access_denied", 403)
        slug = item_id.split(":", 1)[-1]
        word_set = WordSetService.get_set(
            slug, include_unpublished=bool(getattr(current_user, "is_admin", False))
        )
        if word_set is None:
            raise NativeLessonError("not_found", 404)
        words = WordSetService.get_words(word_set.id)
        rows = QuizService.generate_quiz_questions(
            words, min(20, len(words) * 2), distractor_pool=words
        )
        source = {"set_id": word_set.id}
        title = word_set.name
    if not rows:
        raise NativeLessonError("not_found", 404)
    return {
        "rows": rows,
        "source": source,
        "theory": theory,
        "title": title,
        "level": level,
        "item_id": item_id,
        "day": _day(),
    }


def _document(run):
    p = run.payload
    proxy = SimpleNamespace(
        id=run.session_id,
        type="grammar" if run.kind in ("grammar_topic", "grammar_review") else "quiz",
        module=SimpleNamespace(level=SimpleNamespace(code=p.get("level", "A1"))),
        content={"exercises": p["rows"], "learning_steps": p["source"].get("learning_steps")},
    )
    questions = [_question(proxy, row, i) for i, row in enumerate(p["rows"])]
    token = _signer().dumps(
        {"user": current_user.id, "session": run.session_id, "kind": run.kind, "day": p["day"],
         "projection_version": NATIVE_PROJECTION_VERSION}
    )
    return {
        "id": run.session_id,
        "title": p["title"],
        "type": proxy.type,
        "passing_score": PASSING_SCORE_QUIZ,
        "assessment": "practice",
        "allow_repeat": not bool(p["source"].get("placement_review_id")),
        "theory": p["theory"],
        "questions": questions,
        "learning_steps": p["source"].get("learning_steps", []),
        "immediate_feedback": True,
        "support_mode": (
            "inline"
            if p.get("level") in ("A0", "A1")
            else "toggle" if p.get("level") == "A2" else "off"
        ),
        "session_token": token,
        "learning_goal": "Проверь тему на трёх примерах и разбери ответы." if p["source"].get("placement_review_id") else None,
    }


@api_native_activities.route("/grammar/topics", methods=["GET"])
@api_bearer_required
def grammar_topics():
    from app.grammar_lab.models import GrammarTopic
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
    from app.api.native_grammar_progress import topic_progress

    topics = (
        GrammarTopic.query.filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .order_by(GrammarTopic.level, GrammarTopic.order)
        .all()
    )
    progress = topic_progress(current_user.id, [topic.id for topic in topics])
    fields = ('id', 'slug', 'title', 'title_ru', 'level', 'order', 'estimated_time', 'difficulty')
    return jsonify(success=True, topics=[{
        **{field: getattr(topic, field) for field in fields},
        'exercise_count': progress[topic.id]['total_exercises'],
        'progress': progress[topic.id],
    } for topic in topics])


@api_native_activities.get('/grammar/topics/<int:topic_id>')
@api_bearer_required
@limiter.limit('60 per minute', key_func=get_authenticated_user_key)
def grammar_topic_material(topic_id):
    """Read rules without opening practice or mutating the learner's SRS."""
    from app.grammar_lab.models import GrammarTopic
    from app.api.native_grammar_progress import topic_progress, theory_revision

    topic = db.session.get(GrammarTopic, topic_id)
    if not _public_topic(topic):
        raise NativeLessonError('not_found', 404)
    theory = _theory(topic.content or {})
    progress = topic_progress(current_user.id, [topic.id])[topic.id]
    return jsonify(success=True, topic={
        'id': topic.id,
        'title': _plain(topic.title) or _plain(topic.title_ru) or 'Грамматика',
        'title_ru': _plain(topic.title_ru) or None,
        'level': topic.level,
        'exercise_count': progress['total_exercises'],
        'theory': theory,
        'theory_revision': theory_revision(theory),
        'guided_learning': bool((topic.content or {}).get('learning_steps')),
        'progress': progress,
    })


@api_native_activities.post('/grammar/topics/<int:topic_id>/theory/complete')
@csrf.exempt
@api_bearer_required
@limiter.limit('30 per minute', key_func=get_authenticated_user_key)
def complete_grammar_theory(topic_id):
    from app.api.native_grammar_progress import complete_theory

    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) != {'theory_revision', 'completed'}
            or body.get('completed') is not True
            or not isinstance(body.get('theory_revision'), str)
            or len(body['theory_revision']) != 64
            or any(character not in '0123456789abcdef' for character in body['theory_revision'])):
        raise NativeLessonError('invalid_input', 400)
    progress, earned = complete_theory(current_user.id, topic_id, body['theory_revision'])
    return jsonify(success=True, progress=progress, xp_earned=earned)


@api_native_activities.route("/activities/<kind>/start", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def start_activity(kind):
    return start_activity_document(kind, request.get_json(silent=True))


def start_activity_document(kind: str, body: Any) -> Any:
    if kind not in KINDS:
        raise NativeLessonError("not_found", 404)
    if (
        not isinstance(body, dict)
        or set(body) != {"item_id", "request_id"}
        or not isinstance(body["item_id"], str)
        or len(body["item_id"]) > 160
        or not isinstance(body["request_id"], str)
        or len(body["request_id"]) != 36
    ):
        raise NativeLessonError("invalid_input")
    try:
        UUID(body["request_id"])
    except (ValueError, AttributeError):
        raise NativeLessonError("invalid_input")
    from app.study.models import NativeLearningRun, StudySession
    from app.api.native_srs import _lock_user

    try:
        _guard(kind, body["item_id"])
        existing = NativeLearningRun.query.filter_by(
            user_id=current_user.id, request_id=body["request_id"]
        ).first()
        if existing:
            if existing.payload.get("day") != _day():
                raise NativeLessonError("lesson_changed", 409)
            if existing.kind != kind or existing.payload["item_id"] != body["item_id"]:
                raise NativeLessonError("invalid_input")
            return jsonify(success=True, lesson=_document(existing))
        payload = _prepare(kind, body["item_id"])
        _lock_user()
        existing = (
            NativeLearningRun.query.filter_by(
                user_id=current_user.id, request_id=body["request_id"]
            )
            .populate_existing()
            .first()
        )
        if existing:
            return jsonify(success=True, lesson=_document(existing))
        study = StudySession(
            user_id=current_user.id,
            session_type=(
                "quiz_word_set"
                if kind == "word_set_quiz"
                else (
                    "quiz_linear_plan"
                    if kind == "deck_quiz"
                    else "grammar" if kind.startswith("grammar") else "quiz"
                )
            ),
            word_set_id=payload["source"].get("set_id"),
            start_time=datetime.now(UTC),
        )
        db.session.add(study)
        db.session.flush()
        run = NativeLearningRun(
            session_id=study.id,
            user_id=current_user.id,
            request_id=body["request_id"],
            kind=kind,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        db.session.add(run)
        document = _document(run)
        db.session.commit()
        return jsonify(success=True, lesson=document)
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Native activity start failed user=%s kind=%s", current_user.id, kind
        )
        return jsonify(success=False, error="server_error"), 500


def _event(kind, reason):
    from app.daily_plan.models import DailyPlanEvent
    from app.utils.time_utils import get_user_local_date

    today = get_user_local_date(current_user.id, db)
    if not DailyPlanEvent.query.filter_by(
        user_id=current_user.id, event_type=kind, plan_date=today
    ).first():
        db.session.add(
            DailyPlanEvent(
                user_id=current_user.id,
                event_type=kind,
                plan_date=today,
                step_kind=kind.removesuffix("_completed"),
                reason_text=reason,
            )
        )


def _validate_error_revision(run, index):
    """An in-flight review cannot resolve an unrelated question after import."""
    if run.kind != "error_review":
        return
    from app.daily_plan.linear.models import QuizErrorLog

    source = run.payload["source"]
    error = QuizErrorLog.query.filter_by(id=source["error_ids"][index], user_id=current_user.id).first()
    if error is None:
        raise NativeLessonError("lesson_changed", 409)
    current = (error.lesson.content or {}).get("guided_catalog_digest") if error.lesson else None
    revisions = source.get("error_revisions")
    expected = revisions[index] if isinstance(revisions, list) and index < len(revisions) else None
    logged = (error.question_payload or {}).get("guided_revision")
    if (current or None) != (expected or None) or (current or None) != (logged or None):
        raise NativeLessonError("lesson_changed", 409)


def _grade_activity(run, answers):
    from app.curriculum.grading import process_quiz_submission, process_grammar_submission
    from app.study.models import StudySession

    p = run.payload
    kind = run.kind
    doc = _document(run)
    rows = p["rows"]
    questions = doc["questions"]
    feedback = []
    correct = 0
    resolved_today = 0
    for i, (row, q) in enumerate(zip(rows, questions, strict=True)):
        _validate_error_revision(run, i)
        value = answers[str(i)]
        if not isinstance(value, str) or not value.strip() or len(value) > 20000:
            raise NativeLessonError("invalid_input")
        converted = _converted(
            row,
            q,
            value,
            kind in ("grammar_review", "grammar_topic")
            or (kind == "error_review" and p["source"]["sources"][i] == "grammar"),
        )
        if kind in ("grammar_review", "grammar_topic"):
            from app.grammar_lab.models import (
                GrammarExercise,
                GrammarAttempt,
                UserGrammarTopicStatus,
                UserGrammarExercise,
            )
            from app.grammar_lab.services.grammar_lab_service import (
                GrammarLabService,
                _get_unified_srs_service,
            )
            from app.grammar_lab.services.grader import GrammarExerciseGrader

            exercise = GrammarExercise.query.get(p["source"]["exercise_ids"][i])
            if exercise is not None and not _public_topic(exercise.topic):
                raise NativeLessonError("access_denied", 403)
            if (
                exercise is None
                or _digest(exercise.content) != p["source"]["revision"][str(exercise.id)]
            ):
                raise NativeLessonError("lesson_changed", 409)
            grade = GrammarExerciseGrader().grade(exercise, converted)
            if grade.get("error"):
                raise NativeLessonError("grading_failed", 500)
            ok = grade["is_correct"]
            expected = grade.get("correct_answer", "")
            explanation = grade.get("explanation", "")
            update = _get_unified_srs_service().grade_grammar_exercise(
                exercise.id, 3 if ok else 1, current_user.id, p["source"]["session_key"]
            )
            if not update.get("success"):
                raise NativeLessonError("grading_failed", 500)
            db.session.add(
                GrammarAttempt(
                    user_id=current_user.id,
                    exercise_id=exercise.id,
                    is_correct=ok,
                    user_answer=str(grade.get("user_answer", converted)),
                    session_id=p["source"]["session_key"],
                    source="topic_practice",
                    time_spent=None,
                )
            )
            status = UserGrammarTopicStatus.query.filter_by(
                user_id=current_user.id, topic_id=exercise.topic_id
            ).first()
            if status is not None:
                if ok:
                    from app.grammar_lab.services.grammar_lab_service import GRAMMAR_XP

                    earned = GRAMMAR_XP["exercise_correct"]
                    if (
                        update.get("state") == "review"
                        and update.get("interval", 0) >= UserGrammarExercise.MASTERED_THRESHOLD_DAYS
                    ):
                        earned += GRAMMAR_XP["exercise_mastered"]
                    status.add_xp(earned)
                    if status.status == "theory_completed":
                        status.transition_to("practicing")
                GrammarLabService().check_and_update_mastery(exercise.topic_id, current_user.id)
        elif kind == "phrase_review":
            from app.curriculum.grading import quiz_text_matches

            item = p["source"]["items"][i]
            ok = quiz_text_matches(value, [item["answer"], *(item.get("accepted_answers") or [])])
            expected = item["answer"]
            explanation = ""
            if ok and item.get("error_id"):
                from app.daily_plan.linear.errors import resolve_quiz_error

                resolve_quiz_error(item["error_id"], current_user.id, db, commit=False)
        else:
            grammar = kind == "error_review" and p["source"]["sources"][i] == "grammar"
            if grammar and row.get("guided_key"):
                from app.grammar_lab.guided_learning import grade_guided_answers

                grade = grade_guided_answers([row], {"0": converted})
            else:
                grade = (process_grammar_submission if grammar else process_quiz_submission)(
                    [row], {"0": converted}
                )
            checked = grade["feedback"].get("0") or {}
            ok = checked.get("status") == "correct"
            expected = checked.get("correct_matches") or checked.get("correct_answer") or ""
            explanation = checked.get("explanation") or row.get("explanation", "")
            if kind == "error_review" and ok:
                from app.daily_plan.linear.errors import resolve_quiz_error

                resolved = resolve_quiz_error(
                    p["source"]["error_ids"][i], current_user.id, db, commit=False
                )
                if resolved is not None and resolved.resolved_at is not None:
                    from app.utils.time_utils import get_user_local_day_bounds

                    start, end = get_user_local_day_bounds(current_user.id, db)
                    stamp = resolved.resolved_at.replace(tzinfo=None)
                    resolved_today += int(start <= stamp < end)
        if kind == "deck_quiz":
            from app.study.game_routes import _grade_quiz_answer

            _grade_quiz_answer(row.get("word_id"), row.get("direction"), bool(ok), commit=False)
        correct += int(ok)
        if isinstance(expected, dict):
            expected = "\n".join(f"{a} → {b}" for a, b in expected.items())
        elif isinstance(expected, list):
            expected = " / ".join(map(str, expected))
        if q.get("input") == "match":
            expected = matching_answer(row)
        if q.get("input") == "choice":
            given = next((o["label"] for o in q["options"] if o["value"] == value), value)
            if (
                kind == "error_review"
                and p["source"]["sources"][i] == "grammar"
                and str(expected).isdigit()
                and row.get("options")
                and expected not in row["options"]
                and int(expected) < len(row["options"])
            ):
                expected = row["options"][int(expected)]
        else:
            given = display_answer(q, value)
        feedback.append(
            {
                "id": str(i),
                "prompt": q["prompt"],
                "correct": ok,
                "answer": str(given),
                "expected": _plain(expected),
                "explanation": _plain(explanation),
            }
        )
    if p['source'].get('placement_review_id'):
        from app.onboarding.placement_reviews import complete
        complete(current_user.id, p['source']['placement_review_id'], correct, len(rows))
    score = round(correct / len(rows) * 100, 2)
    study = StudySession.query.filter_by(id=run.session_id, user_id=current_user.id).one()
    study.words_studied = len(rows)
    study.correct_answers = correct
    study.incorrect_answers = len(rows) - correct
    study.complete_session()
    if kind in ("grammar_review", "grammar_topic"):
        if p["source"].get("learning_steps"):
            # The native flow explicitly visits every authored rule and checks
            # every exercise before submitting. Reading is separate from SRS
            # mastery; completing this flow must never mark a topic mastered.
            from app.grammar_lab.models import UserGrammarTopicStatus
            from app.grammar_lab.services.grammar_lab_service import GRAMMAR_XP

            status = UserGrammarTopicStatus.get_or_create(current_user.id, p["source"]["topic_id"])
            if not status.theory_completed:
                from app.api.native_grammar_progress import topic_progress

                already_read = topic_progress(current_user.id, [status.topic_id])[status.topic_id]["theory_completed"]
                status.theory_completed = True
                status.theory_completed_at = datetime.now(UTC)
                if not already_read:
                    status.add_xp(GRAMMAR_XP["theory_completed"])
                if status.status == "new":
                    status.status = "practicing"
        from app.daily_plan.linear.xp import maybe_award_grammar_review_xp

        maybe_award_grammar_review_xp(current_user.id, db_session=db)
    elif kind == "phrase_review":
        _event("phrase_review_completed", f"{correct}/{len(rows)} phrases recalled")
    elif kind == "error_review" and resolved_today > 0:
        from app.daily_plan.linear.xp import maybe_award_error_review_xp

        maybe_award_error_review_xp(current_user.id, db_session=db)
    elif kind in ("word_set_quiz", "deck_quiz"):
        from app.study.models import WordSetQuizResult, GameScore
        from app.study.game_routes import _calculate_quiz_xp
        from app.achievements.xp_service import award_game_xp_idempotent
        from app.utils.time_utils import get_user_local_date

        now = datetime.now(UTC)
        started = study.start_time
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = max(0, int((now - started).total_seconds()))
        if kind == "word_set_quiz":
            db.session.add(
                WordSetQuizResult(
                    user_id=current_user.id,
                    set_id=p["source"]["set_id"],
                    total_questions=len(rows),
                    correct_answers=correct,
                    score_percentage=score,
                    time_taken=elapsed,
                    completed_at=now,
                )
            )
        db.session.add(
            GameScore(
                user_id=current_user.id,
                game_type="quiz",
                score=score,
                time_taken=elapsed,
                correct_answers=correct,
                total_questions=len(rows),
                date_achieved=now,
            )
        )
        xp = _calculate_quiz_xp(correct, len(rows), elapsed, has_streak=False)["total_xp"]
        award_game_xp_idempotent(
            current_user.id, run.session_id, "quiz", xp, get_user_local_date(current_user.id, db)
        )
        if kind == "deck_quiz":
            from app.daily_plan.linear.xp import (
                record_deck_quiz_completion,
                maybe_award_srs_global_xp,
                maybe_award_linear_perfect_day,
            )

            record_deck_quiz_completion(current_user.id, db_session=db)
            maybe_award_srs_global_xp(current_user.id, db_session=db)
            maybe_award_linear_perfect_day(current_user.id, db_session=db)
    completed = kind != "error_review" or resolved_today > 0
    return {
        "success": True,
        "lesson_id": run.session_id,
        "score": score,
        "passed": score >= PASSING_SCORE_QUIZ,
        "completed": completed,
        "assessment": "practice",
        "correct_count": correct,
        "total_count": len(rows),
        "feedback": feedback,
    }


@api_native_activities.post("/activities/<kind>/check")
@csrf.exempt
@api_bearer_required
@limiter.limit("90 per minute", key_func=get_authenticated_user_key)
def check_learning_answer(kind):
    return check_activity_document(kind, request.get_json(silent=True))


def check_activity_document(kind: str, body: Any) -> Any:
    from app.study.models import NativeLearningRun
    from app.grammar_lab.models import GrammarExercise
    from app.grammar_lab.guided_learning import check_answer

    if kind not in KINDS:
        raise NativeLessonError("not_found", 404)
    if (not isinstance(body, dict) or set(body) != {"session_token", "question_id", "answer"}
            or not isinstance(body["session_token"], str) or not isinstance(body["question_id"], str)):
        raise NativeLessonError("invalid_input")
    try:
        sealed = _signer().loads(body["session_token"], max_age=21600)
    except (BadSignature, SignatureExpired, TypeError):
        raise NativeLessonError("lesson_changed", 409) from None
    if not isinstance(sealed, dict) or sealed.get("user") != current_user.id or sealed.get("kind") != kind:
        raise NativeLessonError("access_denied", 403)
    run = NativeLearningRun.query.filter_by(
        session_id=sealed.get("session"), user_id=current_user.id, kind=kind).first()
    if run is None:
        raise NativeLessonError("not_found", 404)
    if (sealed.get("day") != _day() or sealed.get("projection_version") != NATIVE_PROJECTION_VERSION
            or run.response is not None):
        raise NativeLessonError("lesson_changed", 409)
    _guard(kind, run.payload["item_id"])
    questions = _document(run)["questions"]
    index = next((i for i, q in enumerate(questions) if q["id"] == body["question_id"]), None)
    if index is None:
        raise NativeLessonError("invalid_input")
    _validate_error_revision(run, index)
    exercise = None
    if kind in ("grammar_topic", "grammar_review"):
        exercise = GrammarExercise.query.get(run.payload["source"]["exercise_ids"][index])
        if exercise is None or _digest(exercise.content) != run.payload["source"]["revision"][str(exercise.id)]:
            raise NativeLessonError("lesson_changed", 409)
        if not _public_topic(exercise.topic):
            raise NativeLessonError("access_denied", 403)
    if kind == "phrase_review":
        from app.curriculum.grading import quiz_text_matches
        item = run.payload["source"]["items"][index]
        answer = body["answer"]
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 2000:
            raise NativeLessonError("invalid_input")
        accepted = [item["answer"], *(item.get("accepted_answers") or [])]
        return jsonify(success=True, feedback={"id": questions[index]["id"], "prompt": questions[index]["prompt"],
            "correct": quiz_text_matches(answer, accepted),
            "answer": answer, "expected": item["answer"], "explanation": "Образец перевода: " + item["answer"]})
    return jsonify(success=True, feedback=check_answer(
        run.payload["rows"][index], questions[index], body["answer"], exercise=exercise,
        grammar=kind in ("grammar_topic", "grammar_review") or (
            kind == "error_review" and run.payload["source"]["sources"][index] == "grammar")))


@api_native_activities.route("/activities/<kind>/submit", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def submit_activity(kind):
    return submit_activity_document(kind, request.get_json(silent=True))


def submit_activity_document(kind: str, body: Any) -> Any:
    if kind not in KINDS:
        raise NativeLessonError("not_found", 404)
    if (
        not isinstance(body, dict)
        or set(body) != {"session_token", "answers"}
        or not isinstance(body["session_token"], str)
        or not isinstance(body["answers"], dict)
    ):
        raise NativeLessonError("invalid_input")
    try:
        sealed = _signer().loads(body["session_token"], max_age=21600)
    except (BadSignature, SignatureExpired, TypeError):
        raise NativeLessonError("lesson_changed", 409)
    if (
        not isinstance(sealed, dict)
        or sealed.get("user") != current_user.id
        or sealed.get("kind") != kind
    ):
        raise NativeLessonError("access_denied", 403)
    from app.study.models import NativeLearningRun
    from app.api.native_srs import _lock_user

    try:
        run = NativeLearningRun.query.filter_by(
            session_id=sealed["session"], user_id=current_user.id, kind=kind
        ).first()
        if run is None:
            raise NativeLessonError("not_found", 404)
        guard_error = None
        try:
            _guard(kind, run.payload["item_id"])
        except NativeLessonError as error:
            guard_error = error
        _lock_user()
        run = (
            NativeLearningRun.query.filter_by(
                session_id=sealed["session"], user_id=current_user.id, kind=kind
            )
            .populate_existing()
            .one()
        )
        if run.response is not None:
            return jsonify(run.response)
        if sealed.get('projection_version') != NATIVE_PROJECTION_VERSION:
            raise NativeLessonError('lesson_changed', 409)
        if sealed.get("day") != _day():
            raise NativeLessonError("lesson_changed", 409)
        if guard_error:
            raise guard_error
        if set(body["answers"]) != set(map(str, range(len(run.payload["rows"])))):
            raise NativeLessonError("answers_required")
        response = _grade_activity(run, body["answers"])
        run.response = response
        db.session.commit()
        return jsonify(response)
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Native activity grade failed user=%s kind=%s", current_user.id, kind
        )
        return jsonify(success=False, error="grading_failed"), 500
