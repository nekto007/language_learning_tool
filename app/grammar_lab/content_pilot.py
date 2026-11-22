"""Idempotent pilot import. Existing topic, lessons, exercises and progress survive."""

import json
from copy import deepcopy
from pathlib import Path


def plurals_content():
    authored = json.loads((Path(__file__).parent / "content/plurals_demonstratives.json").read_text())
    content = {"introduction": authored["goal"], "learning_goal": authored["goal"],
               "pilot_version": authored["version"], "sections": [], "exercises": [], "learning_steps": []}
    for step in authored["steps"]:
        block = {"title": step["title"], "body": step["body"], "kind": "text"}
        start = len(content["exercises"])
        for i, exercise in enumerate(step["exercises"]):
            content["exercises"].append({**deepcopy(exercise), "answer": exercise["correct_answer"],
                                        "guided_key": f"{step['id']}:{i}"})
        content["sections"].append({"subtitle": step["title"], "description": step["body"]})
        content["learning_steps"].append({"id": step["id"], "title": step["title"], "theory": [block],
                                          "question_ids": list(map(str, range(start, len(content["exercises"]))))})
    return content


def install_plurals_pilot(*, apply=False):
    from app.curriculum.models import Lessons
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.grammar_lab.guided_learning import learning_steps
    from app.utils.db import db

    topic = GrammarTopic.query.filter_by(slug="a1-4").one()
    content = plurals_content()
    learning_steps(content, len(content["exercises"]))
    # Resolve by explicit relationship or authored external key, never by an
    # assumed database ID (IDs vary across environments).
    lessons = [lesson for lesson in Lessons.query.filter_by(type="grammar").all()
               if lesson.grammar_topic_id == topic.id or (
                   isinstance(lesson.content, dict) and lesson.content.get("external_key") ==
                   "curriculum:grammar:A1:04:mnozhestvennoe_chislo_i_this_that_these_those")]
    report = {"topic_id": topic.id, "lesson_ids": [lesson.id for lesson in lessons],
              "steps": len(content["learning_steps"]), "exercises": len(content["exercises"]), "applied": apply}
    if not apply:
        return report
    existing = {e.content.get("guided_key"): e for e in GrammarExercise.query.filter_by(topic_id=topic.id).all()
                if isinstance(e.content, dict) and e.content.get("guided_key")}
    ids = []
    for index, row in enumerate(content["exercises"]):
        exercise = existing.get(row["guided_key"])
        if exercise is None:
            exercise = GrammarExercise(topic_id=topic.id, exercise_type=row["type"], content=row,
                                       difficulty=1 if index < 15 else 2, order=index)
            db.session.add(exercise)
        else:
            exercise.content = deepcopy(row)
            exercise.exercise_type = row["type"]
        db.session.flush()
        ids.append(exercise.id)
    topic.content = {**deepcopy(content), "guided_exercise_ids": ids}
    for lesson in lessons:
        # Preserve identity, external key and other curriculum metadata.
        metadata = {key: value for key, value in (lesson.content or {}).items()
                    if key in ("external_key", "source_module")}
        lesson.content = {**metadata, **deepcopy(content)}
    db.session.commit()
    return report
