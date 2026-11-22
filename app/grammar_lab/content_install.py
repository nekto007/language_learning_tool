"""Transactional, repeatable installation of reviewed grammar; no user-data writes."""

from copy import deepcopy
from datetime import datetime, UTC
import json
import os
from pathlib import Path
from uuid import uuid4

from app.grammar_lab.content_catalog import compile_topic, content_digest, load_catalog, validate_catalog_answers


def _snapshot(topics, lessons, exercises):
    return {
        "topics": [{"id": t.id, "slug": t.slug, "title": t.title, "title_ru": t.title_ru, "level": t.level,
                    "content": deepcopy(t.content)} for t in topics],
        "lessons": [{"id": lesson.id, "title": lesson.title, "grammar_topic_id": lesson.grammar_topic_id,
                     "module_id": lesson.module_id, "type": lesson.type,
                     "content": deepcopy(lesson.content), "content_version": lesson.content_version}
                    for lesson in lessons],
        "exercises": [{"id": e.id, "topic_id": e.topic_id, "content": deepcopy(e.content),
                       "exercise_type": e.exercise_type, "difficulty": e.difficulty, "order": e.order}
                      for e in exercises],
    }


def _write_backup(snapshot, documents, directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    destination = path / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".json")
    payload = {"schema": 2, "created_at": datetime.now(UTC).isoformat(), "before": snapshot,
               "catalog_digests": {slug: content_digest(d) for slug, d in documents.items()}}
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    return str(destination)


def _seal_backup_after(backup_path, after):
    path = Path(backup_path)
    value = json.loads(path.read_text())
    value["after_digest"] = content_digest(after)
    temporary = path.with_name(path.name + ".pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _preflight_existing(topics, lessons, exercises):
    """Reject duplicate keys and drift even when the catalog digest is unchanged."""
    fields = ("introduction", "learning_goal", "guided_content_version", "sections", "exercises", "learning_steps")
    by_topic = {}
    by_id = {exercise.id: exercise for exercise in exercises}
    for exercise in exercises:
        key = (exercise.content or {}).get("guided_key")
        keys = by_topic.setdefault(exercise.topic_id, set())
        if key and key in keys:
            raise ValueError(f"Duplicate guided exercise key in topic {exercise.topic_id}: {key}")
        if key:
            keys.add(key)
    for topic in topics:
        content = topic.content or {}
        if not content.get("guided_catalog_digest"):
            continue
        compiled = {key: content.get(key) for key in fields}
        expected = content.get("guided_content_digest")
        ids = content.get("guided_exercise_ids")
        rows = content.get("exercises")
        title = content.get("guided_display_title")
        drift = (not expected or content_digest(compiled) != expected or not isinstance(ids, list)
                 or not isinstance(rows, list) or len(ids) != len(rows) or len(set(ids)) != len(ids)
                 or topic.title != title or topic.title_ru != title)
        if not drift:
            for index, (key, row) in enumerate(zip(ids, rows, strict=True)):
                exercise = by_id.get(key)
                if (exercise is None or exercise.topic_id != topic.id or exercise.content != row
                        or exercise.order != index or exercise.exercise_type != row.get("type")):
                    drift = True
                    break
        if not drift:
            keep = set(ids)
            drift = any(exercise.topic_id == topic.id and exercise.id not in keep
                        and not (exercise.content or {}).get("guided_retired") for exercise in exercises)
        for lesson in lessons:
            if lesson.grammar_topic_id == topic.id:
                projected = {key: (lesson.content or {}).get(key) for key in fields}
                drift = drift or content_digest(projected) != expected or lesson.title != "Грамматика: " + title
        if drift:
            raise ValueError(f"Installed grammar drift in {topic.slug}; review manual edits before applying")


def install_catalog(*, slugs=None, apply=False, backup_dir=None, root=None):
    from flask import current_app
    from app.curriculum.models import Lessons
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.utils.db import db

    # Validate the ENTIRE selected package, including accepted answers, before
    # creating a single row. A missing topic cannot silently make a partial roll-out.
    documents = load_catalog(slugs, root=root)
    totals = validate_catalog_answers(documents)
    topics = GrammarTopic.query.filter(GrammarTopic.slug.in_(documents)).order_by(GrammarTopic.id).all()
    found = {topic.slug: topic for topic in topics}
    missing = set(documents) - set(found)
    if missing:
        raise ValueError("Topics missing from database: " + ", ".join(sorted(missing)))
    if slugs is None:
        unreviewed = {t.slug for t in GrammarTopic.query.all()} - set(documents)
        if unreviewed:
            raise ValueError("Database contains unreviewed topics: " + ", ".join(sorted(unreviewed)))
    for topic in topics:
        if topic.level != topic.slug.split("-")[0].upper():
            raise ValueError(f"Level/slug mismatch: {topic.slug}")
    topic_ids = [topic.id for topic in topics]
    lessons = (Lessons.query.filter(Lessons.type == "grammar", Lessons.grammar_topic_id.in_(topic_ids))
               .order_by(Lessons.id).all())
    exercises = (GrammarExercise.query.filter(GrammarExercise.topic_id.in_(topic_ids))
                 .order_by(GrammarExercise.id).all())
    _preflight_existing(topics, lessons, exercises)
    before = _snapshot(topics, lessons, exercises)
    changes = [t.slug for t in topics if (t.content or {}).get("guided_catalog_digest") != content_digest(documents[t.slug])]
    planned = {"create": 0, "update": 0, "retire": 0}
    for topic in topics:
        if topic.slug not in changes:
            continue
        desired = compile_topic(documents[topic.slug])["exercises"]
        existing = [exercise for exercise in exercises if exercise.topic_id == topic.id]
        by_key = {(exercise.content or {}).get("guided_key"): exercise for exercise in existing
                  if (exercise.content or {}).get("guided_key")}
        kept_keys = {row["guided_key"] for row in desired}
        for index, row in enumerate(desired):
            exercise = by_key.get(row["guided_key"])
            if exercise is None:
                planned["create"] += 1
            elif exercise.content != row or exercise.order != index or exercise.exercise_type != row["type"]:
                planned["update"] += 1
        planned["retire"] += sum((exercise.content or {}).get("guided_key") not in kept_keys
                                 and not (exercise.content or {}).get("guided_retired") for exercise in existing)
    report = {**totals, "lesson_count": len(lessons), "topics_to_update": changes, "applied": False,
              "planned_exercise_changes": planned,
              "created_exercises": 0, "updated_exercises": 0, "retired_exercises": 0,
              "topic_ids": topic_ids, "lesson_ids": [lesson.id for lesson in lessons]}
    if not apply:
        return report
    if not changes:
        return {**report, "applied": True}
    directory = backup_dir or Path(current_app.instance_path) / "backups" / "guided-grammar"
    backup = _write_backup(before, documents, directory)
    report["backup"] = backup
    try:
        # Serialize against another importer or an editor. If anything changed
        # between review/backup and locking, do not overwrite those edits.
        topics = (GrammarTopic.query.filter(GrammarTopic.id.in_(topic_ids)).order_by(GrammarTopic.id)
                  .with_for_update().populate_existing().all())
        lessons = (Lessons.query.filter(Lessons.type == "grammar", Lessons.grammar_topic_id.in_(topic_ids))
                   .order_by(Lessons.id).with_for_update().populate_existing().all())
        exercises = (GrammarExercise.query.filter(GrammarExercise.topic_id.in_(topic_ids))
                     .order_by(GrammarExercise.id).with_for_update().populate_existing().all())
        if content_digest(_snapshot(topics, lessons, exercises)) != content_digest(before):
            raise ValueError("Grammar changed during preflight; run the dry-run again")
        by_topic = {}
        for exercise in exercises:
            by_topic.setdefault(exercise.topic_id, []).append(exercise)
        for topic in topics:
            if topic.slug not in changes:
                continue
            authored = documents[topic.slug]
            compiled = compile_topic(authored)
            old_content = deepcopy(topic.content or {})
            rows = by_topic.get(topic.id, [])
            by_key = {}
            for exercise in rows:
                key = (exercise.content or {}).get("guided_key")
                if key:
                    if key in by_key:
                        raise ValueError(f"Duplicate guided exercise key in {topic.slug}: {key}")
                    by_key[key] = exercise
            kept = []
            for index, row in enumerate(compiled["exercises"]):
                exercise = by_key.get(row["guided_key"])
                difficulty = 1 if topic.level == "A1" else (2 if topic.level in ("A2", "B1") else 3)
                if exercise is None:
                    exercise = GrammarExercise(topic_id=topic.id, exercise_type=row["type"],
                                               content=deepcopy(row), difficulty=difficulty, order=index)
                    db.session.add(exercise)
                    report["created_exercises"] += 1
                elif exercise.content != row or exercise.order != index or exercise.exercise_type != row["type"]:
                    exercise.content = deepcopy(row)
                    exercise.exercise_type = row["type"]
                    exercise.order = index
                    report["updated_exercises"] += 1
                db.session.flush()
                kept.append(exercise.id)
            for exercise in rows:
                if exercise.id not in kept and not (exercise.content or {}).get("guided_retired"):
                    # Preserve the ID, attempts, intervals, answers and history.
                    # Unreviewed old questions cannot reappear in a fresh queue.
                    exercise.content = {**deepcopy(exercise.content), "guided_retired": True}
                    report["retired_exercises"] += 1
            topic.content = {**deepcopy(compiled), "guided_exercise_ids": kept,
                             "guided_catalog_digest": content_digest(authored),
                             "guided_content_digest": content_digest(compiled), "guided_display_title": authored["title"],
                             "legacy_content": old_content.get("legacy_content", old_content)}
            topic.title = topic.title_ru = authored["title"]
            for lesson in lessons:
                if lesson.grammar_topic_id != topic.id:
                    continue
                previous = deepcopy(lesson.content or {})
                metadata = {key: value for key, value in previous.items()
                            if key in ("external_key", "source_module", "xp_reward")}
                lesson.content = {**metadata, **deepcopy(compiled),
                                  "guided_catalog_digest": content_digest(authored),
                                  "guided_content_digest": content_digest(compiled), "guided_display_title": authored["title"],
                                  "legacy_content": previous.get("legacy_content", previous)}
                lesson.title = "Грамматика: " + authored["title"]
                lesson.content_version = (lesson.content_version or 1) + 1
        db.session.flush()
        after_exercises = (GrammarExercise.query.filter(GrammarExercise.topic_id.in_(topic_ids))
                           .order_by(GrammarExercise.id).all())
        _seal_backup_after(backup, _snapshot(topics, lessons, after_exercises))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {**report, "applied": True}


def restore_catalog(backup_path, *, apply=False):
    """Restore authored content/visibility without deleting any learner history."""
    from app.curriculum.models import Lessons
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.utils.db import db

    backup = json.loads(Path(backup_path).read_text())
    if backup.get("schema") != 2 or not isinstance(backup.get("before"), dict):
        raise ValueError("Unsupported grammar backup")
    saved = backup["before"]
    report = {"topics": len(saved["topics"]), "lessons": len(saved["lessons"]), "applied": False}
    try:
        topic_ids = [row["id"] for row in saved["topics"]]
        current_topics = (GrammarTopic.query.filter(GrammarTopic.id.in_(topic_ids)).order_by(GrammarTopic.id)
                          .with_for_update().populate_existing().all())
        current_lessons = (Lessons.query.filter(Lessons.type == "grammar", Lessons.grammar_topic_id.in_(topic_ids))
                           .order_by(Lessons.id).with_for_update().populate_existing().all())
        current_exercises = (GrammarExercise.query.filter(GrammarExercise.topic_id.in_(topic_ids))
                             .order_by(GrammarExercise.id).with_for_update().populate_existing().all())
        if content_digest(_snapshot(current_topics, current_lessons, current_exercises)) != backup.get("after_digest"):
            raise ValueError("Grammar was edited after installation; this backup cannot overwrite newer edits")
        # The saved catalog fingerprint prevents an old backup from silently
        # overwriting a newer reviewed release. Nothing touches user tables.
        for row in saved["topics"]:
            topic = GrammarTopic.query.filter_by(id=row["id"], slug=row["slug"]).with_for_update().one_or_none()
            if topic is None or (topic.content or {}).get("guided_catalog_digest") != backup["catalog_digests"][row["slug"]]:
                raise ValueError(f"Topic changed since installation: {row['slug']}")
        for row in saved["lessons"]:
            lesson = db.session.get(Lessons, row["id"])
            if lesson is None:
                raise ValueError(f"Lesson missing: {row['id']}")
        for row in saved["exercises"]:
            if db.session.get(GrammarExercise, row["id"]) is None:
                raise ValueError(f"Exercise missing: {row['id']}")
        if not apply:
            db.session.rollback()
            return report
        previous_ids = {row["id"] for row in saved["exercises"]}
        for exercise in GrammarExercise.query.filter(GrammarExercise.topic_id.in_(topic_ids)).all():
            if exercise.id not in previous_ids:
                exercise.content = {**deepcopy(exercise.content), "guided_retired": True}
        for row in saved["exercises"]:
            exercise = db.session.get(GrammarExercise, row["id"])
            for key in ("content", "exercise_type", "difficulty", "order"):
                setattr(exercise, key, deepcopy(row[key]))
        for row in saved["topics"]:
            topic = db.session.get(GrammarTopic, row["id"])
            topic.content = deepcopy(row["content"])
            topic.title, topic.title_ru = row["title"], row["title_ru"]
        for row in saved["lessons"]:
            lesson = db.session.get(Lessons, row["id"])
            lesson.content = deepcopy(row["content"])
            lesson.title = row["title"]
            lesson.content_version = row["content_version"]
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {**report, "applied": True}
