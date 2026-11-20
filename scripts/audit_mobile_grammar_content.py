#!/usr/bin/env python3
"""Read-only inventory and answer-consistency audit of local grammar sources.

No database, network, credentials or imports are performed. --grade additionally
uses the real Grammar Lab validator/grader in memory. A passing gradeability
check is not a semantic or CEFR completeness certification.

    python scripts/audit_mobile_grammar_content.py --grade --output /tmp/grammar-audit.json
    python scripts/audit_mobile_grammar_content.py --source-dir DIR --skip-extras
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_EMPTY = re.compile(r"<(em|strong)>\s*</\1>", re.I)
_HEADING_ONLY = re.compile(r"<strong>[^<>]+</strong>\s*", re.I)
_LEVELS = ("A1", "A2", "B1", "B2", "C1")


def _normal(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).casefold().replace("\u2019", "'")).strip(" .!?,;:")


def audit_sources(source: Path, extras: Path | None = None, *, grade: bool = False) -> dict:
    report: dict[str, Any] = {
        "scope": "local_source_only",
        "database_access": False,
        "semantic_accuracy_certified": False,
        "official_cefr_completeness_certified": False,
        "modules": [],
        "errors": [],
        "warnings": [],
        "extra_exercises": 0,
        "extra_alternatives": 0,
        "graded_answers": 0,
    }

    def issue(level, code, file, **details):
        report[level].append({"code": code, "file": file, **details})

    files = sorted(source.glob("module_*.json"))
    if not files:
        issue("errors", "no_module_sources", str(source))
    identities = set()
    lesson_types: Counter = Counter()
    levels: Counter = Counter()
    for path in files:
        try:
            raw = json.loads(path.read_text())
            module = raw.get("module") if isinstance(raw, dict) else None
            if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
                raise ValueError("Expected module.lessons")
            identity = (module.get("level"), module.get("order") or module.get("id"))
            if identity[0] not in _LEVELS or type(identity[1]) is not int or identity[1] < 1:
                raise ValueError("Invalid module level/order")
            if identity in identities:
                issue("errors", "duplicate_module_identity", path.name, identity=identity)
            identities.add(identity)
            levels[identity[0]] += 1
            lessons = module["lessons"]
            lesson_types.update(str(lesson.get("type")) for lesson in lessons if isinstance(lesson, dict))
            grammar = [lesson for lesson in lessons if isinstance(lesson, dict) and lesson.get("type") == "grammar"]
            if len(grammar) != 1:
                issue("errors", "grammar_lesson_count", path.name, count=len(grammar))
            summaries = []
            for lesson in grammar:
                content = lesson.get("content")
                if not isinstance(content, dict):
                    issue("errors", "invalid_grammar_content", path.name)
                    continue
                recap = content.get("tldr")
                if recap is None or recap == []:
                    issue("warnings", "missing_recap", path.name)
                elif not isinstance(recap, list):
                    issue("errors", "invalid_recap_shape", path.name)
                else:
                    for index, line in enumerate(recap):
                        if not isinstance(line, str) or not line.strip():
                            issue("errors", "empty_recap_rule", path.name, bullet=index)
                        elif _EMPTY.search(line):
                            issue("errors", "empty_recap_markup", path.name, bullet=index)
                        elif _HEADING_ONLY.fullmatch(line):
                            issue("warnings", "heading_only_recap", path.name, bullet=index)
                summaries.append(
                    {
                        "title": lesson.get("title"),
                        "external_key": content.get("external_key"),
                        "rule": content.get("rule"),
                        "recap_bullets": len(recap) if isinstance(recap, list) else 0,
                    }
                )
            report["modules"].append(
                {
                    "file": path.name,
                    "level": identity[0],
                    "order": identity[1],
                    "title": module.get("title"),
                    "lesson_count": len(lessons),
                    "grammar": summaries,
                }
            )
        except (OSError, ValueError, TypeError) as error:
            issue("errors", "invalid_module_source", path.name, detail=str(error))
    report["module_count_by_level"] = dict(sorted(levels.items()))
    report["lesson_types"] = dict(sorted(lesson_types.items()))
    report["lesson_count"] = sum(lesson_types.values())
    report["modules"].sort(key=lambda item: (_LEVELS.index(item["level"]), item["order"]))
    exercise_types: Counter = Counter()
    if extras is not None:
        extra_files = sorted(extras.glob("grammar_extra_*.json"))
        if not extra_files:
            issue("errors", "no_extra_sources", str(extras))
        report["extra_file_count"] = len(extra_files)
        grader = validator = None
        if grade:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            try:
                from app.grammar_lab.content_validator import validate_exercise_content
                from app.grammar_lab.services.grader import GrammarExerciseGrader

                grader, validator = GrammarExerciseGrader(), validate_exercise_content
            except ImportError as error:
                issue("errors", "runtime_grader_unavailable", "<runner>", detail=str(error))
        for path in extra_files:
            try:
                data = json.loads(path.read_text())
                if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
                    raise ValueError("Expected extra.sessions")
                for session in data["sessions"]:
                    if not isinstance(session, dict) or not isinstance(session.get("exercises"), list):
                        raise ValueError("Expected session.exercises")
                    for exercise in session.get("exercises", []):
                        if not isinstance(exercise, dict):
                            raise ValueError("Exercise must be an object")
                        kind, content = exercise.get("exercise_type"), exercise.get("content")
                        if not isinstance(content, dict):
                            raise ValueError("Exercise content must be an object")
                        exercise_types[str(kind)] += 1
                        report["extra_exercises"] += 1
                        slot = {"session": session.get("session_number"), "order": exercise.get("order")}
                        alternatives = content.get("alternatives") or content.get("acceptable_answers") or []
                        if not isinstance(alternatives, list):
                            raise ValueError("Alternatives must be a list")
                        report["extra_alternatives"] += len(alternatives)
                        if kind == "multiple_choice":
                            options = content.get("options") or []
                            if not isinstance(options, list) or not options:
                                issue("errors", "missing_options", path.name, **slot)
                            elif len({_normal(v) for v in options}) != len(options):
                                issue("errors", "duplicate_options", path.name, **slot)
                            correct = content.get("correct_answer")
                            valid_key = (
                                (type(correct) is int and 0 <= correct <= len(options))
                                or (isinstance(correct, str) and (
                                    correct in options or (correct.isdigit() and 0 <= int(correct) <= len(options))
                                ))
                            )
                            if not valid_key:
                                issue("errors", "choice_key_not_in_options", path.name, **slot)
                        if kind != "matching" and (
                            "correct_answer" not in content or content["correct_answer"] is None
                        ):
                            issue("errors", "missing_correct_answer", path.name, **slot)
                        if grader is not None:
                            validator(kind, content)
                            instance = SimpleNamespace(id=exercise.get("order", 0), exercise_type=kind, content=content)
                            expected = content.get("correct_answer")
                            if kind == "matching":
                                expected = {str(i): i for i in range(len(content.get("pairs", [])))}
                            for answer in [expected, *alternatives]:
                                report["graded_answers"] += 1
                                result = grader.grade(instance, answer)
                                if result.get("is_correct") is not True:
                                    issue("errors", "authored_answer_rejected", path.name, answer=answer, **slot)
            except (OSError, ValueError, TypeError, KeyError) as error:
                issue("errors", "invalid_extra_source", path.name, detail=str(error))
        report["extra_exercise_types"] = dict(sorted(exercise_types.items()))
    report["passed"] = not report["errors"]
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "module_completed/fixed")
    parser.add_argument("--extra-dir", type=Path, default=ROOT / "grammar_exercises_extra")
    parser.add_argument("--skip-extras", action="store_true")
    parser.add_argument("--grade", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_sources(args.source_dir, None if args.skip_extras else args.extra_dir, grade=args.grade)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{'PASS' if report['passed'] else 'FAIL'}: {len(report['modules'])} modules, {report['lesson_count']} lessons; "
        f"{report['extra_exercises']} extra exercises, {report['graded_answers']} answers graded; "
        f"{len(report['errors'])} errors, {len(report['warnings'])} advisory warnings. Database access: none."
    )
    for issue in report["errors"]:
        print(f"  {issue['code']}: {issue['file']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
