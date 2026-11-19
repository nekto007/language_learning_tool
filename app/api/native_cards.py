"""Native vocabulary/card lessons with server-owned resumable queues."""

from copy import deepcopy
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import UUID

from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user
from sqlalchemy.orm.attributes import flag_modified
from app import csrf, limiter
from app.api.decorators import api_bearer_required
from app.api.native_lessons import (
    NativeLessonError,
    native_error,
    private_response,
    _lesson_and_progress,
    _guard_plan,
    _digest,
)
from app.api.native_content import media_url, _plain
from app.api import native_srs as srs
from app.utils.db import db
from app.utils.rate_limit_helpers import get_authenticated_user_key

api_native_cards = Blueprint("api_native_cards", __name__)
api_native_cards.after_request(private_response)
api_native_cards.register_error_handler(NativeLessonError, native_error)
TYPES = {"vocabulary", "card", "flashcards"}
ROUND_WORD_LIMIT = 5


def _lesson(lesson_id):
    lesson, progress = _lesson_and_progress(lesson_id)
    if lesson.type not in TYPES:
        raise NativeLessonError("unsupported_lesson", 422)
    return lesson, progress


def _queue(lesson):
    from app.curriculum.routes.card_lessons import _resolve_lesson_deck, _build_cards_for_words
    from app.curriculum.card_service import apply_lesson_card_context
    from app.srs.counting import get_new_card_budget
    from app.study.models import UserCardDirection, UserWord

    content = lesson.content
    if isinstance(content, list):
        content = {"words": content}
    if isinstance(content, str):
        import json

        content = json.loads(content)
    if not isinstance(content, dict):
        raise NativeLessonError("unsupported_lesson", 422)
    if lesson.type in ("vocabulary", "flashcards") and "cards" not in content:
        content = {
            **content,
            "cards": content.get("words") or content.get("items") or content.get("vocabulary") or [],
        }
    proxy = SimpleNamespace(
        content=content,
        collection_id=lesson.collection_id,
        module_id=lesson.module_id,
        number=lesson.number,
        id=lesson.id,
    )
    words, missing, _ = _resolve_lesson_deck(proxy)
    budget, _ = get_new_card_budget(current_user.id, db)
    cards = _build_cards_for_words(words, current_user.id, activate_srs=budget > 0) + missing
    cards = apply_lesson_card_context(cards, content)
    if not cards or len(cards) > 1000:
        raise NativeLessonError("unsupported_lesson", 422)
    queue = []
    seen = set()
    for i, item in enumerate(cards):
        front = _plain(item.get("front") or item.get("word") or item.get("english"))
        back = _plain(item.get("back") or item.get("translation") or item.get("russian"))
        if not front or not back:
            raise NativeLessonError("unsupported_lesson", 422)
        word_id = item.get("word_id")
        direction = item.get("direction") or "eng-rus"
        key = f"{word_id}:{direction}" if word_id else f"display:{i}"
        if key in seen:
            continue
        seen.add(key)
        card = UserCardDirection.query.get(item["direction_id"]) if item.get("direction_id") else None
        excluded = bool(card and card.user_word.srs_excluded)
        display_only = not card or excluded or bool(card.is_buried)
        practice_reason = "not_scheduled" if display_only else None
        if card and card.first_reviewed is None and not display_only:
            if budget <= 0:
                display_only = True
                practice_reason = "daily_limit"
            else:
                budget -= 1
        if card:
            card.session_attempts = 0
        queue.append(
            {
                "word_id": word_id or 1000000000 + i,
                "direction": direction,
                "front": front,
                "back": back,
                "examples": srs._examples(item.get("sentences") or item.get("examples") or item.get("example")),
                "state": item.get("status") or item.get("state") or "new",
                "revision": srs._revision(card),
                "display_only": display_only,
                "practice_only": display_only,
                "practice_reason": practice_reason,
                "key": key,
                "audio_url": media_url(item.get("audio_url") or item.get("audio")),
            }
        )
    return queue


def _short_round(queue, covered):
    """Keep authored word order; separate recall directions by other words."""
    pending = [card for card in queue if card["key"] not in covered]
    word_ids = list(dict.fromkeys(card["word_id"] for card in pending))[:ROUND_WORD_LIMIT]
    return [
        card
        for direction in ("eng-rus", "rus-eng")
        for word in word_ids
        for card in pending
        if card["word_id"] == word and card["direction"] == direction
    ]


def _coverage(progress, revision):
    data = (progress.data or {}) if progress else {}
    saved = data.get("native_card_rounds") or {}
    return dict(saved.get("ratings") or {}) if saved.get("revision") == revision else {}


def _save_coverage(lesson, progress, state):
    from app.curriculum.models import LessonProgress

    if progress is None:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            status="in_progress",
            started_at=datetime.fromisoformat(state["started_at"]),
        )
        db.session.add(progress)
    progress.data = {
        **(progress.data or {}),
        "native_card_rounds": {"revision": state["revision"], "ratings": state["seen"]},
    }
    progress.last_activity = datetime.now(UTC)
    return progress


def _requeue(queue, card, position):
    # A retry should not sit beside the opposite direction of the same word.
    start = max(0, min(max(position - 1, 2), len(queue)))
    for index in range(start, len(queue) + 1):
        before = queue[index - 1]["word_id"] if index else None
        after = queue[index]["word_id"] if index < len(queue) else None
        if card["word_id"] not in (before, after):
            queue.insert(index, card)
            return
    queue.append(card)


def _response(run):
    response = srs._response(run)
    if response["card"]:
        response["card"] = {
            k: v
            for k, v in response["card"].items()
            if k
            in {
                "word_id",
                "direction",
                "front",
                "back",
                "examples",
                "state",
                "audio_url",
                "practice_only",
                "practice_reason",
            }
        }
    response.update(
        lesson_id=run.state["lesson_id"],
        lesson_complete=run.state.get("lesson_complete", False),
        more_rounds=bool(set(run.state.get("full_keys", [])) - set(run.state.get("seen", {}))),
        lesson_words=run.state.get("lesson_words"),
        remaining_lesson_words=len(
            {word for key, word in run.state.get("full_keys", {}).items() if key not in run.state.get("seen", {})}
        ),
    )
    response["next_round_words"] = min(ROUND_WORD_LIMIT, response["remaining_lesson_words"])
    return response


def _complete(lesson, progress, run, state):
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.daily_plan.linear.xp import maybe_award_curriculum_xp
    from app.study.models import StudySession

    total = len(state["seen"])
    minimum = min(max(1, int(lesson.min_cards_required or 10)), state["deck_size"])
    already_completed = progress is not None and progress.status == "completed"
    completed = already_completed or total >= minimum
    state["complete"] = True
    state["lesson_complete"] = completed
    session = StudySession.query.filter_by(id=run.session_id, user_id=current_user.id).one()
    session.complete_session()
    if not completed:
        return
    now = datetime.now(UTC)
    correct = sum(v == 3 for v in state["seen"].values())
    accuracy = round(correct / max(1, total) * 100)
    if progress is None:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            status="in_progress",
            started_at=state["started_at"],
        )
        # JSON carries timestamps as strings; ORM columns receive datetimes.
        progress.started_at = datetime.fromisoformat(state["started_at"])
        db.session.add(progress)
    progress.status = "completed"
    progress.record_score(accuracy)
    progress.completed_at = progress.completed_at or now
    progress.last_activity = now
    progress.data = {
        **(progress.data or {}),
        "cards_studied": total,
        "correct": correct,
        "accuracy": accuracy,
        "assessment": "self_assessed",
        "native_cards_session": run.session_id,
    }
    db.session.flush()
    if already_completed:
        # Additional words are practice, never a second completion/XP award.
        return
    attempt = LessonAttempt.create_attempt(current_user.id, lesson.id, progress.id)
    attempt.started_at = progress.started_at or now
    attempt.completed_at = now
    attempt.score = accuracy
    attempt.passed = True
    attempt.correct_answers = correct
    attempt.total_questions = total
    award = maybe_award_curriculum_xp(current_user.id, lesson, db_session=db, score=accuracy)
    state["xp_earned"] = award.xp_awarded if award else 0


@api_native_cards.route("/lessons/<int:lesson_id>/cards/session", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("30 per minute", key_func=get_authenticated_user_key)
def start_cards(lesson_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) not in ({"request_id"}, {"request_id", "continue_round"})
        or not isinstance(body["request_id"], str)
        or ("continue_round" in body and type(body["continue_round"]) is not bool)
    ):
        raise NativeLessonError("invalid_input")
    try:
        UUID(body["request_id"])
    except (ValueError, AttributeError):
        raise NativeLessonError("invalid_input") from None
    try:
        lesson, progress = _lesson(lesson_id)
        guard_error = None
        try:
            _guard_plan(lesson_id)
        except NativeLessonError as error:
            guard_error = error
        day = srs._day()
        srs._lock_user()
        lesson, progress = _lesson(lesson_id)
        run = srs._run()
        version = _digest(lesson.content)
        completed_practice = (
            progress is not None
            and progress.status == "completed"
            and (
                body.get("continue_round") is True
                or (
                    run
                    and run.state.get("lesson_id") == lesson_id
                    and run.state.get("practice_round")
                    and not run.state.get("complete")
                    and run.study_day == day
                )
            )
        )
        if guard_error and guard_error.code == "lesson_locked" and completed_practice:
            guard_error = None
        if (
            run
            and run.state.get("lesson_id") == lesson_id
            and run.study_day == day
            and run.state.get("revision") == version
            and (
                (run.state.get("start_id") == body["request_id"] and run.state["complete"])
                or (not run.state["complete"] and guard_error is None)
            )
        ):
            return jsonify(_response(run))
        if guard_error:
            raise guard_error
        full_queue = _queue(lesson)
        covered = _coverage(progress, version)
        allowed = {card["key"] for card in full_queue}
        covered = {key: value for key, value in covered.items() if key in allowed and value in (1, 2, 3)}
        queue = _short_round(full_queue, covered)
        from app.study.models import NativeSRSState, StudySession

        session = StudySession(user_id=current_user.id, session_type="cards", start_time=datetime.now(UTC))
        db.session.add(session)
        db.session.flush()
        if run is None:
            run = NativeSRSState(user_id=current_user.id)
            db.session.add(run)
        run.session_id = session.id
        run.study_day = day
        run.updated_at = datetime.now(UTC)
        run.state = {
            "start_id": body["request_id"],
            "lesson_id": lesson_id,
            "revision": version,
            "queue": queue,
            "deck_size": len(full_queue),
            "full_keys": {card["key"]: card["word_id"] for card in full_queue},
            "lesson_words": len({card["word_id"] for card in full_queue}),
            "practice_round": bool(completed_practice),
            "step": 0,
            "reviewed": 0,
            "remembered": 0,
            "complete": False,
            "xp_earned": 0,
            "seen": covered,
            "started_at": datetime.now(UTC).isoformat(),
            **srs._round_metadata(queue),
        }
        if not queue:
            state = deepcopy(run.state)
            _complete(lesson, progress, run, state)
            run.state = state
        db.session.commit()
        return jsonify(_response(run))
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Native cards start failed user=%s lesson=%s", current_user.id, lesson_id)
        return jsonify(success=False, error="server_error"), 500


@api_native_cards.route("/lessons/<int:lesson_id>/cards/grade", methods=["POST"])
@csrf.exempt
@api_bearer_required
@limiter.limit("120 per minute", key_func=get_authenticated_user_key)
def grade_cards(lesson_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"session_id", "step", "rating"}
        or any(type(v) is not int for v in body.values())
        or body["rating"] not in (1, 2, 3)
        or body["step"] < 0
    ):
        raise NativeLessonError("invalid_input")
    try:
        lesson, progress = _lesson(lesson_id)
        guard_error = None
        try:
            _guard_plan(lesson_id)
        except NativeLessonError as error:
            guard_error = error
        day = srs._day()
        srs._lock_user()
        lesson, progress = _lesson(lesson_id)
        run = srs._run()
        if (
            not run
            or run.session_id != body["session_id"]
            or run.study_day != day
            or run.state.get("lesson_id") != lesson_id
        ):
            raise NativeLessonError("srs_changed", 409)
        state = deepcopy(run.state)
        if state.get("last_step") == body["step"]:
            return jsonify(state["last_response"])
        if (
            guard_error
            and guard_error.code == "lesson_locked"
            and state.get("practice_round")
            and progress is not None
            and progress.status == "completed"
        ):
            guard_error = None
        if guard_error:
            raise guard_error
        if state["complete"] or state["step"] != body["step"] or state["revision"] != _digest(lesson.content):
            raise NativeLessonError("srs_changed", 409)
        head = state["queue"].pop(0)
        result = None
        notice = None
        if not head["display_only"]:
            result, notice = srs._grade_card(head, body["rating"], run.session_id)
        if result is None:
            from app.study.models import StudySession

            session = StudySession.query.filter_by(id=run.session_id, user_id=current_user.id).one()
            head["display_only"] = head["practice_only"] = True
            session.words_studied += 1
            if body["rating"] >= 2:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1
        else:
            card, position = result
            if position is not None:
                _requeue(state["queue"], card, position)
        if head["display_only"] and body["rating"] < 3:
            head["practice_attempts"] = head.get("practice_attempts", 0) + 1
            if head["practice_attempts"] < 2:
                _requeue(state["queue"], head, 3 if body["rating"] == 1 else 6)
        state["seen"][head["key"]] = body["rating"]
        state["reviewed"] += 1
        state["remembered"] += int(body["rating"] >= 2)
        srs._record_rating(state, head, body["rating"])
        state["step"] += 1
        state["notice"] = notice
        progress = _save_coverage(lesson, progress, state)
        if not state["queue"]:
            _complete(lesson, progress, run, state)
        run.state = state
        run.updated_at = datetime.now(UTC)
        response = _response(run)
        state["last_step"] = body["step"]
        state["last_response"] = response
        run.state = deepcopy(state)
        flag_modified(run, "state")
        db.session.commit()
        from app.curriculum.services.progress_service import _invalidate_user_progress_cache

        _invalidate_user_progress_cache(current_user.id)
        return jsonify(response)
    except NativeLessonError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Native cards grade failed user=%s lesson=%s", current_user.id, lesson_id)
        return jsonify(success=False, error="server_error"), 500
