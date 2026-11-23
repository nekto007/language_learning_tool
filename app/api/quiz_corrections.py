"""Versioned, assisted course corrections without overwriting independent scores.

Only opted-in native course sessions create this state. Checks are pure;
committing a fully correct correction round is the only completion write.
"""

from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
import random
from uuid import uuid4

FLOW = "deferred_v1"


def eligible(lesson):
    from app.curriculum.constants import is_objective_practice

    return is_objective_practice(lesson) and not getattr(lesson, "_native_challenge", False)


def pending_state(progress):
    data = getattr(progress, "data", None)
    state = data.get("quiz_correction") if isinstance(data, dict) else None
    if (isinstance(state, dict) and state.get("version") == 1
            and state.get("status") == "pending" and state.get("pending_ids")):
        return state
    return None


def first_round_state(lesson, progress, grade, feedback, answers, sealed):
    """Prepare state before the same transaction saves the independent attempt."""
    if (sealed.get("quiz_flow") != FLOW or not eligible(lesson)
            or getattr(progress, "status", None) == "completed"):
        return None
    wrong = [f["id"] for f in feedback if not f["correct"]]
    if not wrong:
        return None
    return {
        "version": 1, "attempt_id": uuid4().hex,
        "revision": sealed["revision"], "status": "pending",
        "first_score": grade["score"], "first_passed": bool(grade["passed"]),
        "first_correct_count": sum(f["correct"] for f in feedback),
        "first_total_count": len(feedback), "pending_ids": wrong,
        **({"first_units_correct": grade['correct_items'],
            "first_units_total": grade['total_items'],
            "first_unit_label": 'Слов' if lesson.type == 'dictation' else 'Пар'}
           if lesson.type in ('dictation', 'matching', 'collocation_matching')
           and grade.get('total_items') is not None else {}),
        "first_answers": deepcopy(answers), "feedback": deepcopy(feedback),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _candidate_answers(row, expected):
    candidates = []
    for key in ("correct_answer", "answer", "correct_sentence", "full_correct", "correct"):
        value = row.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(v for v in value if isinstance(v, str))
    if not candidates:
        candidates = [expected]
    for key in ("alternatives", "alternative_answers", "acceptable_answers", "answers", "accepted_answers"):
        values = row.get(key)
        if isinstance(values, list):
            candidates.extend(v for v in values if isinstance(v, str))
    return list(dict.fromkeys(v for v in candidates if isinstance(v, str) and v.strip()))


def correction_help(row, question, answer, feedback, level=0):
    """Keep aligned correct words, not a positional prefix of a wrong sentence.

    At least one target word always remains to be entered. Choice/order/match
    controls are kept intact, rather than serialising their values as prose.
    """
    from app.utils.normalization import normalize_quiz_answer

    hint = feedback.get("explanation") or "Исправь выделенные части ответа."
    result = {"level": level, "segments": [], "hint": hint, "choices": []}
    if (question.get("options") or question.get("input") not in (None, "text", "short_text")
            or feedback.get("correct")):
        return result
    candidates = _candidate_answers(row, feedback.get("expected", ""))
    if not candidates:
        return result
    source = [normalize_quiz_answer(t) for t in str(answer).split()]
    # Punctuation-only tokens are never a word the learner must reproduce.
    source = [t for t in source if t]

    def tokens(candidate):
        return [t for t in candidate.split() if normalize_quiz_answer(t)]

    target = max(candidates, key=lambda candidate: (
        SequenceMatcher(None, source, [normalize_quiz_answer(t) for t in tokens(candidate)],
                        autojunk=False).ratio(),
        SequenceMatcher(None, normalize_quiz_answer(answer), normalize_quiz_answer(candidate),
                        autojunk=False).ratio(),
    ))
    words = tokens(target)
    matcher = SequenceMatcher(None, source, [normalize_quiz_answer(t) for t in words], autojunk=False)
    fixed = set()
    for block in matcher.get_matching_blocks():
        fixed.update(range(block.b, block.b + block.size))
    missing = [i for i in range(len(words)) if i not in fixed]
    if not missing:
        # Wrong answer containing only surplus words: removing those words
        # would prefill the complete target. Keep one meaningful decision.
        missing = [len(words) - 1] if words else []
        fixed.difference_update(missing)
    if not missing:
        return result
    if level >= 2:
        # Each extra support level fills more gaps but never the last one.
        fill = len(missing) - 1
        fixed.update(missing[:fill])
        missing = missing[fill:]
    result["segments"] = [{"text": word if i in fixed else "", "editable": i not in fixed}
                          for i, word in enumerate(words)]
    if level >= 1:
        letter = next((c for c in words[missing[0]] if c.isalnum()), "")
        if letter:
            result["hint"] += f"\nНачало нужного слова: {letter}…"  # noqa: RUF001
    if level >= 3 and len(missing) == 1:
        correct = words[missing[0]]
        choices = [correct]
        # Offer the learner's incorrect word, not unrelated fixed subject /
        # preposition tokens from the same sentence as fake distractors.
        raw_source = [t for t in str(answer).split() if normalize_quiz_answer(t)]
        remaining = missing[0]
        wrong_words = []
        for tag, start, end, target_start, target_end in matcher.get_opcodes():
            if tag != "replace" or not target_start <= remaining < target_end:
                continue
            if end - start == target_end - target_start:
                wrong_words.append(raw_source[start + remaining - target_start])
            elif target_end - target_start == 1 or end - start == 1:
                wrong_words.extend(raw_source[start:end])
        for word in wrong_words:
            if (normalize_quiz_answer(word)
                    and all(normalize_quiz_answer(word) != normalize_quiz_answer(v) for v in choices)):
                choices.append(word)
            if len(choices) == 3:
                break
        # Stable shuffle: repeating a read-only check must return the same help.
        random.Random(question["id"] + target).shuffle(choices)
        result["choices"] = choices
    return result


def project_correction(lesson, progress, questions, content):
    from app.api.native_content import rows_for
    from app.api.native_lessons import _digest, NativeLessonError
    from app.grammar_lab.guided_learning import question_help
    from app.api.native_content import check_course_answer

    state = pending_state(progress)
    if not state or state["revision"] != _digest(content):
        return None
    selected = [q for q in questions if q["id"] in state["pending_ids"]]
    if len(selected) != len(state["pending_ids"]):
        raise NativeLessonError("lesson_changed", 409)
    rows = dict(zip((q["id"] for q in questions), rows_for(lesson), strict=True))
    for q in selected:
        if not q.get("theory_help"):
            blocks = question_help(content, rows[q["id"]], int(q["id"]), len(questions))
            if blocks:
                q["theory_help"] = blocks
        answer = state["first_answers"][q["id"]]
        feedback = check_course_answer(lesson, q, answer)
        q["correction_help"] = correction_help(rows[q["id"]], q, answer, feedback)
        gaps = sum(s["editable"] for s in q["correction_help"]["segments"])
        if gaps:
            q["instruction"] = ("Впиши пропущенное слово." if gaps == 1 else "Заполни пропуски.") + " Верные части ответа уже сохранены."
    return {"questions": selected, "quiz_phase": "correction", "learning_steps": [],
            "correction": {"attempt_id": state["attempt_id"],
                           **{key: state[key] for key in (
                               "first_score", "first_passed", "first_correct_count", "first_total_count")},
                           **{key: state[key] for key in ('first_units_correct', 'first_units_total', 'first_unit_label')
                              if key in state},
                           "previous_answers": {key: state["first_answers"][key] for key in state["pending_ids"]},
                           "theory_required": not state["first_passed"] or len(state["pending_ids"]) >= 4}}


def check_correction(lesson, progress, sealed):
    from app.api.native_lessons import NativeLessonError

    state = pending_state(progress)
    if not state or state["attempt_id"] != sealed.get("correction_attempt"):
        raise NativeLessonError("lesson_changed", 409)
    return state


def submit_correction(lesson, progress, sealed, questions, answers):
    from app.api.native_lessons import NativeLessonError
    from app.curriculum.services.progress_service import _invalidate_user_progress_cache
    from app.api.native_content import check_course_answer
    from app.utils.db import db

    state = check_correction(lesson, progress, sealed)
    if set(answers) != set(state["pending_ids"]):
        raise NativeLessonError("invalid_input")
    feedback = [check_course_answer(lesson, q, answers[q["id"]])
                for q in questions]
    completed = all(f["correct"] for f in feedback)
    response = {"success": True, "lesson_id": lesson.id, "score": state["first_score"],
                "passed": state["first_passed"], "completed": completed,
                "correction_pending": not completed,
                "correct_count": sum(f["correct"] for f in feedback),
                "total_count": len(feedback), "feedback": feedback}
    if not completed:
        return response
    now = datetime.now(UTC)
    updated = {**state, "status": "completed", "completed_at": now.isoformat(),
               "corrected_answers": deepcopy(answers),
               "receipt": {"nonce": sealed["nonce"], "response": response}}
    progress.data = {**progress.data, "quiz_correction": updated}
    progress.status = "completed"
    progress.completed_at = progress.completed_at or now
    progress.last_activity = now
    # Retire only errors from this revision and these corrected question IDs.
    from app.daily_plan.linear.errors import current_error_revision_clause
    from app.daily_plan.linear.models import QuizErrorLog

    errors = QuizErrorLog.query.filter(
        QuizErrorLog.user_id == progress.user_id, QuizErrorLog.lesson_id == lesson.id,
        QuizErrorLog.resolved_at.is_(None), current_error_revision_clause(),
    ).all()
    for error in errors:
        payload = error.question_payload or {}
        if (str(payload.get("question_index")) in state["pending_ids"]
                and payload.get("quiz_attempt_id") == state["attempt_id"]):
            error.resolved_at = now
    from app.daily_plan.linear.xp import maybe_award_curriculum_xp

    maybe_award_curriculum_xp(progress.user_id, lesson, db_session=db, score=state["first_score"])
    db.session.commit()
    _invalidate_user_progress_cache(progress.user_id)
    return response
