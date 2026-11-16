"""Authenticated native daily-plan exercises outside the curriculum spine."""

from copy import deepcopy
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import UUID

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import (
    NativeLessonError,
    native_error,
    private_response,
    _theory,
    _digest,
)
from app.api.native_content import _question, _converted, _plain
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
        selected = service.start_topic_practice(topic_id, current_user.id)
        if selected.get("error"):
            raise NativeLessonError("not_found", 404)
        ids = [int(e["id"]) for e in selected.get("exercises") or []]
        all_ex = {e.id: e for e in GrammarExercise.query.filter(GrammarExercise.id.in_(ids)).all()}
        for key in ids:
            e = all_ex[key]
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
        theory = _theory(topic.content or {})
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
        for error in errors:
            if not check_lesson_access(error.lesson_id):
                raise NativeLessonError("access_denied", 403)
            p = error.question_payload or {}
            raw = None
            try:
                original = rows_for(error.lesson)
                index = int(p.get("question_index", -1))
                if 0 <= index < len(original):
                    raw = deepcopy(original[index])
            except (ValueError, TypeError):
                pass
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
            topic = error.lesson.grammar_topic if error.lesson is not None else None
            if topic and not theory:
                theory = _theory(topic.content or {})
        source = {"error_ids": ids, "sources": sources}
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
        content={},
    )
    questions = [_question(proxy, row, i) for i, row in enumerate(p["rows"])]
    token = _signer().dumps(
        {"user": current_user.id, "session": run.session_id, "kind": run.kind, "day": p["day"]}
    )
    return {
        "id": run.session_id,
        "title": p["title"],
        "type": proxy.type,
        "passing_score": 70,
        "assessment": "practice",
        "theory": p["theory"],
        "questions": questions,
        "support_mode": (
            "inline"
            if p.get("level") in ("A0", "A1")
            else "toggle" if p.get("level") == "A2" else "off"
        ),
        "session_token": token,
    }


@api_native_activities.route("/grammar/topics", methods=["GET"])
@api_bearer_required
def grammar_topics():
    from app.grammar_lab.models import GrammarTopic
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES

    topics = (
        GrammarTopic.query.filter(GrammarTopic.level.in_(PUBLIC_CEFR_CODES))
        .order_by(GrammarTopic.level, GrammarTopic.order)
        .all()
    )
    return jsonify(success=True, topics=[t.to_dict() for t in topics])


@api_native_activities.route("/activities/<kind>/start", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def start_activity(kind):
    if kind not in KINDS:
        raise NativeLessonError("not_found", 404)
    body = request.get_json(silent=True)
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
        db.session.commit()
        return jsonify(success=True, lesson=_document(run))
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
            from app.daily_plan.items.phrase_review import normalise_phrase

            item = p["source"]["items"][i]
            folded = normalise_phrase(value)
            ok = bool(
                folded
                and folded
                in {normalise_phrase(a) for a in item.get("accepted_answers") or [item["answer"]]}
            )
            expected = item["answer"]
            explanation = ""
            if ok and item.get("error_id"):
                from app.daily_plan.linear.errors import resolve_quiz_error

                resolve_quiz_error(item["error_id"], current_user.id, db, commit=False)
        else:
            grammar = kind == "error_review" and p["source"]["sources"][i] == "grammar"
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
        if q.get("input") == "choice":
            given = next((o["label"] for o in q["options"] if o["value"] == value), value)
            if (
                kind == "error_review"
                and p["source"]["sources"][i] == "grammar"
                and str(expected).isdigit()
                and row.get("options")
                and int(expected) < len(row["options"])
            ):
                expected = row["options"][int(expected)]
        else:
            given = (
                "\n".join(f"{a} → {b}" for a, b in converted.items())
                if isinstance(converted, dict)
                else str(converted)
            )
        feedback.append(
            {
                "id": str(i),
                "prompt": q["prompt"],
                "correct": ok,
                "answer": _plain(given),
                "expected": _plain(expected),
                "explanation": _plain(explanation),
            }
        )
    score = round(correct / len(rows) * 100)
    study = StudySession.query.filter_by(id=run.session_id, user_id=current_user.id).one()
    study.words_studied = len(rows)
    study.correct_answers = correct
    study.incorrect_answers = len(rows) - correct
    study.complete_session()
    if kind in ("grammar_review", "grammar_topic"):
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
        "passed": score >= 70,
        "completed": completed,
        "assessment": "practice",
        "correct_count": correct,
        "total_count": len(rows),
        "feedback": feedback,
    }


@api_native_activities.route("/activities/<kind>/submit", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def submit_activity(kind):
    if kind not in KINDS:
        raise NativeLessonError("not_found", 404)
    body = request.get_json(silent=True)
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
