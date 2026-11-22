"""Reviewed, versioned grammar content. Pure loading, compilation and validation."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

CONTENT_ROOT = Path(__file__).parent / "content"
LEVEL_COUNTS = {"A1": 16, "A2": 23, "B1": 19, "B2": 14, "C1": 14}
SUPPORTED_EXERCISES = {"fill_blank", "multiple_choice", "transformation", "error_correction", "translation"}


def expected_slugs():
    return [f"{level.lower()}-{number}" for level, count in LEVEL_COUNTS.items()
            for number in range(1, count + 1)]


def content_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_authored_topic(value):
    """Fail before any database writes; this does not replace editorial review."""
    if not isinstance(value, dict):
        raise ValueError("Topic must be an object")
    slug = value.get("topic_slug")

    def fail(message):
        raise ValueError(f"{slug or '<unknown>'}: {message}")

    if slug not in expected_slugs() or type(value.get("version")) is not int or value["version"] < 1:
        fail("unknown topic slug or invalid version")
    for key in ("title", "goal"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            fail(f"missing {key}")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        fail("expected 1-30 authored steps")
    step_ids = set()
    exercise_keys = set()
    for step in steps:
        if not isinstance(step, dict):
            fail("step must be an object")
        for key in ("id", "title", "body"):
            if not isinstance(step.get(key), str) or not step[key].strip():
                fail(f"step is missing {key}")
        if step["id"] in step_ids or len(step["body"]) > 2000:
            fail(f"duplicate step ID or oversized rule: {step['id']}")
        step_ids.add(step["id"])
        exercises = step.get("exercises")
        if not isinstance(exercises, list) or not 1 <= len(exercises) <= 6:
            fail(f"{step['id']}: expected 1-6 exercises")
        for row in exercises:
            if not isinstance(row, dict) or row.get("type") not in SUPPORTED_EXERCISES:
                fail(f"{step['id']}: unsupported exercise")
            for key in ("question", "instruction", "correct_answer", "explanation"):
                if not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > 2000:
                    fail(f"{step['id']}: missing/invalid exercise {key}")
            if len(row["instruction"].split()) < 4:
                fail(f"{step['id']}: instruction must describe the action and answer format")
            options = row.get("options")
            if row["type"] == "multiple_choice" and (
                    not isinstance(options, list) or not 2 <= len(options) <= 8
                    or any(not isinstance(o, str) or not o.strip() for o in options)
                    or len(set(options)) != len(options) or row["correct_answer"] not in options):
                fail(f"{step['id']}: choices must be distinct and include the literal correct answer")
            alternatives = row.get("alternatives", [])
            if not isinstance(alternatives, list) or any(not isinstance(a, str) or not a.strip() for a in alternatives):
                fail(f"{step['id']}: invalid alternatives")
            identity = (row["type"], row["question"], row["correct_answer"])
            if identity in exercise_keys:
                fail(f"{step['id']}: duplicate question/answer instead of fresh practice")
            exercise_keys.add(identity)
    reference = value.get("reference_sections", [])
    if not isinstance(reference, list) or len(reference) > 20:
        fail("invalid reference sections")
    for block in reference:
        if (not isinstance(block, dict) or any(not isinstance(block.get(k), str) or not block[k].strip()
                for k in ("title", "body")) or len(block["body"]) > 2000):
            fail("invalid reference section")
    return value


def load_catalog(slugs=None, root=None):
    root = Path(root) if root is not None else CONTENT_ROOT
    requested = list(dict.fromkeys(slugs if slugs is not None else expected_slugs()))
    unknown = set(requested) - set(expected_slugs())
    if unknown:
        raise ValueError(f"Unknown grammar topics: {', '.join(sorted(unknown))}")
    documents = {}
    for slug in requested:
        path = root / ("plurals_demonstratives.json" if slug == "a1-4" else f"topics/{slug}.json")
        if not path.is_file():
            raise ValueError(f"Missing reviewed content: {slug}")
        value = validate_authored_topic(json.loads(path.read_text()))
        if value["topic_slug"] != slug:
            raise ValueError(f"Wrong topic in {path.name}")
        documents[slug] = value
    return documents


def compile_topic(authored):
    from app.grammar_lab.guided_learning import learning_steps

    validate_authored_topic(authored)
    content = {"introduction": authored["goal"], "learning_goal": authored["goal"],
               "guided_content_version": authored["version"], "sections": [], "exercises": [], "learning_steps": []}
    for step in authored["steps"]:
        block = {"title": step["title"], "body": step["body"], "kind": "text"}
        start = len(content["exercises"])
        for original in step["exercises"]:
            row = deepcopy(original)
            # Preserve the already-installed pilot IDs. Other topics use a
            # content identity so rearranging questions does not move progress
            # onto a different question, and a changed target gets a new ID.
            identity = {k: row.get(k) for k in ("type", "question", "correct_answer", "options")}
            legacy = {}
            if authored["topic_slug"] == "a1-4":
                legacy = json.loads((CONTENT_ROOT / "plurals_legacy_keys.json").read_text())
            key = legacy.get(content_digest(identity)) or f"{step['id']}:{content_digest(identity)[:16]}"
            row.update(answer=row["correct_answer"], guided_key=key,
                       guided_rule_id=step["id"], guided_revision=content_digest(authored), theory_help=[deepcopy(block)])
            content["exercises"].append(row)
        content["sections"].append({"subtitle": step["title"], "description": step["body"]})
        content["learning_steps"].append({"id": step["id"], "title": step["title"], "theory": [block],
                                          "question_ids": list(map(str, range(start, len(content["exercises"]))))})
    for block in authored.get("reference_sections", []):
        content["sections"].append({"subtitle": block["title"], "description": block["body"]})
    learning_steps(content, len(content["exercises"]))
    return content


def validate_catalog_answers(documents):
    """Exercise every canonical answer AND alternatives through the real grader."""
    from types import SimpleNamespace
    from app.api.native_content import _question
    from app.grammar_lab.guided_learning import check_answer

    totals = {"topics": len(documents), "steps": 0, "exercises": 0, "alternatives": 0}
    for slug, document in documents.items():
        compiled = compile_topic(document)
        totals["steps"] += len(compiled["learning_steps"])
        totals["exercises"] += len(compiled["exercises"])
        proxy = SimpleNamespace(id=1, type="grammar", content=compiled,
                                module=SimpleNamespace(level=SimpleNamespace(code=slug.split("-")[0].upper())))
        for i, row in enumerate(compiled["exercises"]):
            question = _question(proxy, row, i)
            variants = [row["correct_answer"], *row.get("alternatives", [])]
            if row["type"] == "multiple_choice":
                variants = [next(o["value"] for o in question["options"] if o["label"] == row["correct_answer"])]
            for answer in variants:
                checked = check_answer(row, question, answer)
                if not checked["correct"]:
                    raise ValueError(f"{slug}/{row['guided_key']}: authored answer rejected by grader")
            totals["alternatives"] += len(variants) - 1
    return totals
