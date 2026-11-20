"""Add reviewed optional grammar topics without replacing exercises or progress.

Dry-run is the default. Existing rows are never overwritten: an edited topic or
exercise with the same stable identity stops the whole import before writes.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import click
from flask.cli import with_appcontext
from sqlalchemy.exc import IntegrityError

from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db

PACK = "mobile-grammar-20261120"
MARKER = "_llt_supplement"
TOPIC_FIELDS = ("slug", "title", "title_ru", "level", "order", "estimated_time", "difficulty", "content")
EXERCISE_FIELDS = ("exercise_type", "content", "difficulty", "order")
KINDS = frozenset(("fill_blank", "multiple_choice", "reorder", "translation", "error_correction", "transformation", "matching", "true_false"))


@dataclass(frozen=True)
class SupplementReport:
    topics_to_create: int
    exercises_to_create: int
    topics_unchanged: int
    exercises_unchanged: int
    applied: bool


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {field}; expected nonempty text up to {maximum} characters")
    return value


def _integer(value, field, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"Invalid {field}; expected integer {lower}..{upper}")
    return value


def _identity(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", value):
        raise ValueError(f"Invalid {field}; expected stable lowercase slug")
    return value


def _strings(value, field, minimum=1, maximum=100):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"Invalid {field}; expected {minimum}..{maximum} strings")
    for item in value:
        _text(item, field, 5000)
    return value


def _validate_exercise(kind, content):
    validate_exercise_content(kind, content)
    alternatives = content.get("alternatives", [])
    if alternatives is not None:
        _strings(alternatives, "exercise.alternatives", minimum=0, maximum=30)
    expected = content.get("correct_answer")
    if kind == "matching":
        pairs = content.get("pairs")
        if not isinstance(pairs, list) or not 2 <= len(pairs) <= 30:
            raise ValueError("Matching needs 2..30 labelled pairs")
        left, right = [], []
        for pair in pairs:
            if not isinstance(pair, dict) or set(pair) != {"left", "right"}:
                raise ValueError("Matching pair needs left/right labels")
            left.append(_text(pair["left"], "matching.left", 500))
            right.append(_text(pair["right"], "matching.right", 500))
        if len(set(left)) != len(left) or len(set(right)) != len(right):
            raise ValueError("Matching pair labels must be unique")
    elif kind == "true_false":
        if not (type(expected) is bool or (isinstance(expected, str) and expected.lower() in ("true", "false"))):
            raise ValueError("True/false expected answer must be true or false")
    elif kind == "multiple_choice":
        options = _strings(content.get("options"), "exercise.options", minimum=2, maximum=30)
        if len({option.strip().lower() for option in options}) != len(options):
            raise ValueError("Duplicate multiple-choice options")
        if not ((isinstance(expected, str) and expected in options) or (type(expected) is int and 0 <= expected < len(options))):
            raise ValueError("Expected multiple-choice answer is not an offered option")
    else:
        _text(expected, "exercise.correct_answer", 5000)
        if kind == "reorder":
            words = _strings(content.get("words"), "exercise.words", minimum=2, maximum=100)
            # Every word is supplied, punctuation may be a separate token. Do
            # not create a puzzle whose advertised answer needs another word.
            def tokens(text):
                return Counter(re.findall(r"[^\W_]+(?:[\u2019'][^\W_]+)*", text.lower()))
            if tokens(expected) != tokens(" ".join(words)):
                raise ValueError("Reorder answer does not use the supplied words")
        elif kind == "fill_blank" and "options" in content:
            options = _strings(content["options"], "exercise.options", minimum=2, maximum=30)
            if expected not in options:
                raise ValueError("Expected fill-blank answer is not an offered option")


def validate_pack(document):
    """Validate every entry before consulting or changing the database."""
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("Unsupported grammar supplement schema_version")
    topics = document.get("topics")
    if not isinstance(topics, list) or not 1 <= len(topics) <= 20:
        raise ValueError("Expected 1..20 grammar topics")
    normalized, slugs = [], set()
    for source in topics:
        if not isinstance(source, dict) or set(source) != {*TOPIC_FIELDS, "exercises"}:
            raise ValueError("Unexpected or missing grammar topic fields")
        topic = {key: deepcopy(source[key]) for key in TOPIC_FIELDS}
        slug = _identity(topic["slug"], "topic.slug")
        if slug in slugs:
            raise ValueError(f"Duplicate topic slug: {slug}")
        slugs.add(slug)
        _text(topic["title"], "topic.title", 200)
        _text(topic["title_ru"], "topic.title_ru", 200)
        if topic["level"] not in ("A1", "A2", "B1", "B2", "C1"):
            raise ValueError("Invalid public grammar level")
        _integer(topic["order"], "topic.order", 0, 10000)
        _integer(topic["estimated_time"], "topic.estimated_time", 1, 120)
        _integer(topic["difficulty"], "topic.difficulty", 1, 5)
        if not isinstance(topic["content"], dict) or not topic["content"] or MARKER in topic["content"]:
            raise ValueError("Invalid topic content or reserved import marker")
        exercises = source["exercises"]
        if not isinstance(exercises, list) or not 1 <= len(exercises) <= 100:
            raise ValueError(f"Expected 1..100 exercises in {slug}")
        prepared, keys, orders = [], set(), set()
        for value in exercises:
            if not isinstance(value, dict) or set(value) != {*EXERCISE_FIELDS, "key"}:
                raise ValueError(f"Unexpected or missing exercise fields in {slug}")
            exercise = {key: deepcopy(value[key]) for key in EXERCISE_FIELDS}
            key = _identity(value["key"], "exercise.key")
            order = _integer(exercise["order"], "exercise.order", 0, 10000)
            if key in keys or order in orders:
                raise ValueError(f"Duplicate exercise key/order in {slug}")
            keys.add(key)
            orders.add(order)
            if not isinstance(exercise["exercise_type"], str) or exercise["exercise_type"] not in KINDS:
                raise ValueError(f"Unsupported exercise type in {slug}/{key}")
            _integer(exercise["difficulty"], "exercise.difficulty", 1, 3)
            content = exercise["content"]
            if not isinstance(content, dict) or MARKER in content:
                raise ValueError(f"Invalid exercise content in {slug}/{key}")
            _text(content.get("question"), "exercise.question", 5000)
            _validate_exercise(exercise["exercise_type"], content)
            prepared.append((key, exercise))
        normalized.append((topic, prepared))
    return normalized


def _marked(content, *, key, fingerprint):
    value = deepcopy(content)
    value[MARKER] = {"pack": PACK, "key": key, "sha256": fingerprint}
    return value


def _plain_values(row, fields, expected_marker):
    values = {field: deepcopy(getattr(row, field)) for field in fields}
    marker = values["content"].pop(MARKER, None) if isinstance(values["content"], dict) else None
    if marker != expected_marker:
        raise ValueError("Existing record is unmanaged or differs from this reviewed supplement")
    return values


def import_supplements(session, document, *, apply=False):
    """Preflight all topics atomically, then add missing records only.

    The existing parent topic row is locked before its exercises are read, so two
    concurrent imports cannot both add a missing exercise. Preflight errors make
    no writes; the caller must roll back its transaction to release any read locks.
    Newly created topic
    slugs use the database's unique constraint; a race rolls the whole import back.
    """
    prepared = validate_pack(document)
    slugs = [topic["slug"] for topic, _ in prepared]
    query = session.query(GrammarTopic).filter(GrammarTopic.slug.in_(slugs)).order_by(GrammarTopic.slug)
    if apply:
        query = query.populate_existing().with_for_update()
    with session.no_autoflush:
        existing = {topic.slug: topic for topic in query.all()}
        plan = []
        new_topics = new_exercises = old_topics = old_exercises = 0
        for topic, exercises in prepared:
            row = existing.get(topic["slug"])
            topic_marker = {"pack": PACK, "key": topic["slug"], "sha256": _digest(topic)}
            rows = {}
            if row is not None:
                if _plain_values(row, TOPIC_FIELDS, topic_marker) != topic:
                    raise ValueError(f"Topic differs from reviewed content: {topic['slug']}")
                old_topics += 1
                for exercise in session.query(GrammarExercise).filter_by(topic_id=row.id).populate_existing().all():
                    marker = (exercise.content or {}).get(MARKER)
                    if not isinstance(marker, dict) or marker.get("pack") != PACK:
                        raise ValueError(f"Unmanaged exercise in existing topic: {topic['slug']}")
                    key = marker.get("key")
                    if not isinstance(key, str) or key in rows:
                        raise ValueError(f"Duplicate or invalid stored exercise identity: {topic['slug']}")
                    rows[key] = exercise
            else:
                new_topics += 1
            missing = []
            for key, exercise in exercises:
                marker = {"pack": PACK, "key": key, "sha256": _digest(exercise)}
                current = rows.get(key)
                if current is None:
                    missing.append((exercise, marker))
                    new_exercises += 1
                else:
                    if _plain_values(current, EXERCISE_FIELDS, marker) != exercise:
                        raise ValueError(f"Exercise differs from reviewed content: {topic['slug']}/{key}")
                    old_exercises += 1
            if set(rows) - {key for key, _ in exercises}:
                raise ValueError(f"Existing topic has exercises outside this reviewed pack: {topic['slug']}")
            plan.append((topic, topic_marker, row, missing))
    report = SupplementReport(new_topics, new_exercises, old_topics, old_exercises, apply)
    if not apply:
        return report
    try:
        for values, marker, topic, missing in plan:
            if topic is None:
                topic = GrammarTopic(**{**values, "content": _marked(values["content"], key=marker["key"], fingerprint=marker["sha256"])})
                session.add(topic)
                session.flush()
            for exercise, exercise_marker in missing:
                values = {**exercise, "content": _marked(exercise["content"], key=exercise_marker["key"], fingerprint=exercise_marker["sha256"])}
                session.add(GrammarExercise(topic_id=topic.id, **values))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return report


def load_pack(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("Grammar supplement file exceeds 2 MB")
    def reject_constant(_):
        raise ValueError("Non-finite number in grammar supplement")
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON object key in grammar supplement")
            value[key] = item
        return value
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_keys)


@click.command("grammar-supplements")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.option("--apply", is_flag=True, help="Add missing reviewed topics/exercises. Default: dry-run, no writes.")
@with_appcontext
def grammar_supplements_command(file, apply):
    """Preflight a supplemental grammar FILE; add missing content only with --apply."""
    try:
        report = import_supplements(db.session, load_pack(file), apply=apply)
    except (ValueError, OSError) as error:
        db.session.rollback()
        raise click.ClickException(str(error)) from None
    except IntegrityError:
        db.session.rollback()
        raise click.ClickException("Concurrent content conflict; nothing was applied. Run dry-run again.") from None
    click.echo(("APPLIED" if apply else "DRY RUN") + f": topics +{report.topics_to_create}, exercises +{report.exercises_to_create}; unchanged topics {report.topics_unchanged}, exercises {report.exercises_unchanged}")
    if not apply:
        db.session.rollback()
        click.echo("No database changes. Use --apply after reviewing this report.")


def register_grammar_supplements(app):
    app.cli.add_command(grammar_supplements_command)
