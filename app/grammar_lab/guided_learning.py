"""Explicitly authored rule → practice sequences, shared by course and Grammar Lab.

No inference from answer keys: question-specific help must be authored or linked
to a named step. Older clients can still read the complete theory normally.
"""

from copy import deepcopy
from types import SimpleNamespace


def grade_guided_answers(rows, answers):
    """Use the same existing grammar grader in the course and Grammar Lab.

    In this grammar pilot, case/spacing/a final full stop are not separate
    learning targets. Do not accept an answer in one entry point and reject
    the same answer in the other.
    """
    from datetime import datetime, UTC
    from app.grammar_lab.services.grader import GrammarExerciseGrader
    from app.api.native_lessons import NativeLessonError

    feedback = {}
    correct = 0
    for i, row in enumerate(rows):
        kind = "matching" if row["type"] == "match" else row["type"]
        exercise = SimpleNamespace(id=i, exercise_type=kind, content=row)
        checked = GrammarExerciseGrader().grade(exercise, answers[str(i)])
        if checked.get("error"):
            raise NativeLessonError("grading_failed", 500)
        ok = checked["is_correct"]
        correct += int(ok)
        feedback[str(i)] = {**checked, "status": "correct" if ok else "incorrect"}
    return {"correct_exercises": correct, "correct_answers": correct,
            "total_exercises": len(rows), "total_questions": len(rows),
            "score": round(correct / len(rows) * 100) if rows else 0,
            "feedback": feedback, "timestamp": datetime.now(UTC).isoformat()}


def learning_steps(content, question_count):
    from app.api.native_lessons import NativeLessonError

    steps = content.get("learning_steps") if isinstance(content, dict) else None
    if steps is None:
        return []
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise NativeLessonError("unsupported_lesson", 422)
    ids, covered, result = set(), [], []
    for step in steps:
        if not isinstance(step, dict):
            raise NativeLessonError("unsupported_lesson", 422)
        key, title, theory, questions = (step.get(k) for k in ("id", "title", "theory", "question_ids"))
        if (
            not isinstance(key, str) or not key or key in ids
            or not isinstance(title, str) or not title
            or not isinstance(theory, list) or not 1 <= len(theory) <= 6
            or not isinstance(questions, list) or not 1 <= len(questions) <= 6
            or any(not isinstance(q, str) for q in questions)
            or any(not isinstance(b, dict) or not isinstance(b.get("title"), str)
                   or not isinstance(b.get("body"), str) or not b["body"].strip()
                   or len(b["body"]) > 2000 for b in theory)
        ):
            raise NativeLessonError("unsupported_lesson", 422)
        ids.add(key)
        covered.extend(questions)
        # Whitelist fields; never project nested exercises or answer keys.
        result.append({"id": key, "title": title,
                       "theory": [{"title": b["title"], "body": b["body"], "kind": "text"} for b in theory],
                       "question_ids": list(questions)})
    if covered != list(map(str, range(question_count))):
        raise NativeLessonError("unsupported_lesson", 422)
    return result


def question_help(content, row, index, count):
    """Return only explicit help. Do not use fuzzy keywords to guess a rule."""
    blocks = row.get("theory_help")
    if isinstance(blocks, list):
        return [{"title": b["title"], "body": b["body"], "kind": "text"}
                for b in blocks[:6] if isinstance(b, dict)
                and isinstance(b.get("title"), str) and isinstance(b.get("body"), str)
                and b["body"].strip() and len(b["body"]) <= 2000]
    return next((deepcopy(s["theory"]) for s in learning_steps(content, count)
                 if str(index) in s["question_ids"]), [])


def lesson_reference(lesson):
    """Fallback reference for a module quiz, clearly labelled as full material."""
    from app.api.native_lessons import _theory

    module_id = getattr(lesson, "module_id", None)
    if not isinstance(module_id, int):
        return []
    from app.curriculum.models import Lessons

    # Prefer an explicit topic link, then the nearest preceding grammar lesson.
    topic = getattr(lesson, "grammar_topic", None)
    if topic is not None:
        return _theory(topic.content or {})
    grammar = (Lessons.query.filter_by(module_id=module_id, type="grammar")
               .filter(Lessons.order <= lesson.order).order_by(Lessons.order.desc()).first())
    return _theory(grammar.content or {}) if grammar else []


def check_answer(row, question, answer, *, grammar=True, exercise=None):
    """Feedback only: no attempts, XP, mastery, or SRS writes."""
    from app.api.native_content import _converted, display_answer, matching_answer
    from app.api.native_lessons import NativeLessonError, plain

    if (not isinstance(answer, str) or not answer.strip() or len(answer) > 20000
            or (question.get("input") in (None, "choice") and question.get("options")
                and answer not in {o["value"] for o in question["options"]})):
        raise NativeLessonError("invalid_input")
    converted = _converted(row, question, answer, grammar)
    if exercise is None and grammar and row.get("guided_key"):
        exercise = SimpleNamespace(id=question["id"], exercise_type=row["type"], content=row)
    if exercise is not None:
        from app.grammar_lab.services.grader import GrammarExerciseGrader

        checked = GrammarExerciseGrader().grade(exercise, converted)
        if checked.get("error"):
            raise NativeLessonError("grading_failed", 500)
        correct = checked["is_correct"]
    else:
        from app.curriculum.grading import process_grammar_submission, process_quiz_submission

        checked = (process_grammar_submission if grammar else process_quiz_submission)(
            [row], {"0": converted})["feedback"]["0"]
        correct = checked.get("status") == "correct"
    expected = checked.get("correct_matches")
    if expected is None:
        expected = checked.get("correct_answer")
    if expected is None:
        expected = checked.get("correct_pairs", "")
    if question.get("options") and row.get("type") in ("true_false", "tf"):
        expected = next((option["label"] for option in question["options"]
                         if option["value"] == str(expected).lower()), expected)
    if (question.get("input") == "choice" and str(expected).isdigit() and row.get("options")
            and expected not in row["options"]):
        position = int(expected)
        if position < len(row["options"]):
            expected = row["options"][position]
    if question.get("input") == "match":
        expected = matching_answer(row)
    elif isinstance(expected, list):
        if question.get("input") == "order":
            # Native order values are authored token positions, never shuffled
            # display positions. The canonical sentence is preferable if given.
            expected = row.get("correct_answer") or row.get("answer") or " ".join(map(str, expected))
            if isinstance(expected, list):
                expected = " ".join(map(str, expected))
        else:
            expected = " / ".join(map(str, expected))
    elif isinstance(expected, dict):
        expected = "\n".join(f"{key} → {value}" for key, value in expected.items())
    explanation = plain(checked.get("explanation") or row.get("explanation"))
    if not correct and not explanation:
        explanation = "\n".join(b["body"] for b in question.get("theory_help", [])
                                if isinstance(b, dict) and isinstance(b.get("body"), str))
        explanation = explanation or "Сравни свой ответ с правильным вариантом: " + plain(expected)  # noqa: RUF001
    return {"id": question["id"], "prompt": question["prompt"], "correct": bool(correct),
            "answer": display_answer(question, answer), "expected": plain(expected),
            "explanation": explanation}
