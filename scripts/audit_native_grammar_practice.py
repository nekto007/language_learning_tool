#!/usr/bin/env python3
"""Verify local Grammar Lab exercises can be solved through native input widgets.

No seed/import execution or database connection. This checks projection and
canonical-answer reachability, not whether every linguistic answer is complete.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.native_content import _converted, _question
from app.grammar_lab.services.grader import GrammarExerciseGrader


def order_for(words, answer):
    """Find authored token indexes that reproduce the canonical sentence."""
    remaining = answer.strip()
    available = set(range(len(words)))
    indexes = []
    while remaining:
        candidates = [index for index in available if remaining.lower().startswith(words[index].strip().lower())]
        if not candidates:
            raise ValueError("Canonical reorder answer cannot be assembled from the provided tokens")
        index = max(candidates, key=lambda value: len(words[value].strip()))
        indexes.append(str(index))
        available.remove(index)
        remaining = remaining[len(words[index].strip()) :].lstrip()
    # The Grammar Lab normalization permits omission of terminal .!? only.
    if any(words[index].strip() not in (".", "!", "?") for index in available):
        raise ValueError("Canonical reorder answer leaves meaningful tokens unused")
    indexes.extend(str(index) for index in sorted(available))
    return json.dumps(indexes)


def widget_answer(exercise, question):
    content = exercise.content
    correct = content.get("correct_answer")
    kind = question["input"]
    if kind == "match":
        return json.dumps({option["value"]: option["value"] for option in question["left_options"]})
    if kind == "order":
        return order_for(content["words"], correct)
    if kind == "choice":
        if exercise.exercise_type == "true_false":
            expected = str(correct).lower() in ("true", "1", "yes")
            return "true" if expected else "false"
        options = content["options"]
        if isinstance(correct, str) and correct in options:
            return str(options.index(correct))
        if isinstance(correct, int) or (isinstance(correct, str) and correct.isdigit()):
            index = int(correct)
            if not 0 <= index < len(options):
                index -= 1
            if not 0 <= index < len(options):
                raise ValueError("Canonical choice index is outside the options")
            return str(index)
        raise ValueError("Canonical choice answer is not among the options")
    if not isinstance(correct, str) or not correct.strip():
        raise ValueError("Canonical text answer is not nonempty text")
    return correct


def audit(paths, supplement=None):
    sources = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for session in document.get("sessions") or []:
            for exercise in session.get("exercises") or []:
                sources.append((str(path), document["level"], exercise))
    if supplement:
        for topic in json.loads(supplement.read_text(encoding="utf-8"))["topics"]:
            sources.extend(
                (str(supplement) + ":" + topic["slug"], topic["level"], exercise) for exercise in topic["exercises"]
            )
    failures, types = [], Counter()
    grader = GrammarExerciseGrader()
    for index, (path, level, source) in enumerate(sources):
        kind = source["exercise_type"]
        types[kind] += 1
        exercise = SimpleNamespace(id=index + 1, exercise_type=kind, content=source["content"])
        proxy = SimpleNamespace(
            id=index + 1, type="grammar", content={}, module=SimpleNamespace(level=SimpleNamespace(code=level))
        )
        try:
            row = {**source["content"], "type": "match" if kind == "matching" else kind}
            question = _question(proxy, row, 0)
            answer = widget_answer(exercise, question)
            converted = _converted(row, question, answer, grammar=True)
            grade = grader.grade(exercise, converted)
            if grade.get("is_correct") is not True:
                raise ValueError("Existing grader rejected the canonical native-widget answer")
            if {"answer", "correct_answer", "correct", "alternatives", "explanation"} & question.keys():
                raise ValueError("Question projection exposed a private answer/explanation field")
            labels = [option["label"].casefold() for option in question["options"]]
            if question["input"] in ("choice", "match") and len(labels) != len(set(labels)):
                raise ValueError("Duplicate visible option labels make the exercise ambiguous")
        except Exception as error:
            failures.append(
                {
                    "file": path,
                    "key": source.get("key") or source.get("order"),
                    "type": kind,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return {
        "scope": "Native projection + canonical-answer reachability; not linguistic completeness.",
        "summary": {"exercises": len(sources), "types": dict(types), "failures": len(failures)},
        "failures": failures,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "grammar_exercises_extra")
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit(sorted(args.source.glob("*.json")), args.supplement)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["exercises"] and not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
